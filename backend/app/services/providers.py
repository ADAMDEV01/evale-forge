from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderConnectionError(ProviderError):
    def __init__(self, message: str = 'Could not connect to Ollama.'):
        super().__init__('provider_connection', message)


class ModelNotFoundError(ProviderError):
    def __init__(self, model: str):
        super().__init__('model_not_found', f'Ollama model "{model}" is not installed.')


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = 'Ollama did not respond before the request timed out.'):
        super().__init__('provider_timeout', message)


class ProviderResponseError(ProviderError):
    def __init__(self, message: str = 'Ollama returned an invalid response.'):
        super().__init__('provider_response', message)


class ProviderConfigurationError(ProviderError):
    def __init__(self, message: str):
        super().__init__('provider_configuration', message)


@dataclass(frozen=True)
class GeneratedResponse:
    text: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class AIProvider(Protocol):
    name: str
    model: str

    def generate(self, prompt: str, temperature: float) -> GeneratedResponse: ...

    def close(self) -> None: ...


@runtime_checkable
class ModelCheckableProvider(Protocol):
    def check_model(self) -> None: ...


class OllamaProvider:
    name = 'ollama'

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ):
        self.model = (model or os.getenv('OLLAMA_MODEL', 'llama3.2')).strip()
        self.base_url = (base_url or os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')).rstrip('/')
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv('OLLAMA_TIMEOUT_SECONDS', '120'))
        except ValueError as error:
            raise ProviderConfigurationError('OLLAMA_TIMEOUT_SECONDS must be a positive number.') from error
        if not self.model:
            raise ProviderConfigurationError('An Ollama model name is required.')
        if self.timeout <= 0:
            raise ProviderConfigurationError('OLLAMA_TIMEOUT_SECONDS must be a positive number.')
        self._client = client or httpx.Client(timeout=self.timeout)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, f'{self.base_url}{path}', **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError() from error
        except (httpx.ConnectError, httpx.NetworkError) as error:
            raise ProviderConnectionError() from error
        except httpx.HTTPStatusError as error:
            body = error.response.text.lower()
            if error.response.status_code == 404 or 'model' in body and 'not found' in body:
                raise ModelNotFoundError(self.model) from error
            raise ProviderResponseError(f'Ollama request failed with status {error.response.status_code}.') from error
        except httpx.RequestError as error:
            raise ProviderConnectionError() from error

    def _json(self, response: httpx.Response) -> dict:
        try:
            value = response.json()
        except ValueError as error:
            raise ProviderResponseError() from error
        if not isinstance(value, dict):
            raise ProviderResponseError()
        return value

    def check_model(self) -> None:
        tags = self._json(self._request('GET', '/api/tags'))
        installed = tags.get('models')
        if not isinstance(installed, list):
            raise ProviderResponseError('Ollama returned an invalid model list.')
        available: set[str] = set()
        for item in installed:
            if isinstance(item, dict):
                name = item.get('name') or item.get('model')
                if isinstance(name, str):
                    available.add(name)
                    available.add(re.sub(r':latest$', '', name))
        if self.model not in available and re.sub(r':latest$', '', self.model) not in available:
            raise ModelNotFoundError(self.model)

    def close(self) -> None:
        self._client.close()

    def generate(self, prompt: str, temperature: float) -> GeneratedResponse:
        started = time.perf_counter()
        payload = self._json(
            self._request(
                'POST',
                '/api/generate',
                json={
                    'model': self.model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {'temperature': temperature},
                },
            )
        )
        text = payload.get('response')
        if not isinstance(text, str):
            raise ProviderResponseError()
        prompt_tokens = payload.get('prompt_eval_count')
        completion_tokens = payload.get('eval_count')
        if prompt_tokens is not None and (not isinstance(prompt_tokens, int) or prompt_tokens < 0):
            raise ProviderResponseError()
        if completion_tokens is not None and (not isinstance(completion_tokens, int) or completion_tokens < 0):
            raise ProviderResponseError()
        elapsed = round((time.perf_counter() - started) * 1000)
        return GeneratedResponse(text, elapsed, prompt_tokens, completion_tokens)



class GroqProvider:
    """OpenAI-compatible Groq chat completions provider."""

    name = 'groq'

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ):
        self.model = (model or os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b')).strip()
        self.base_url = (base_url or os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1')).rstrip('/')
        self.api_key = api_key or os.getenv('GROQ_API_KEY', '')
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv('GROQ_TIMEOUT_SECONDS', '60'))
        except ValueError as error:
            raise ProviderConfigurationError('GROQ_TIMEOUT_SECONDS must be a positive number.') from error
        if not self.api_key:
            raise ProviderConfigurationError('GROQ_API_KEY is required when using the Groq provider.')
        if not self.model:
            raise ProviderConfigurationError('A Groq model name is required.')
        if self.timeout <= 0:
            raise ProviderConfigurationError('GROQ_TIMEOUT_SECONDS must be a positive number.')
        self._client = client or httpx.Client(timeout=self.timeout)

    def _request(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.post(
                f'{self.base_url}{path}',
                headers={'Authorization': f'Bearer {self.api_key}'},
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError('Groq did not respond before the request timed out.') from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 429:
                raise ProviderRateLimitError() from error
            if status in (401, 403):
                raise ProviderConfigurationError('Groq rejected the API key or its permissions.') from error
            if status == 404:
                raise ModelNotFoundError(self.model) from error
            raise ProviderResponseError(f'Groq request failed with status {status}.') from error
        except httpx.RequestError as error:
            raise ProviderConnectionError('Could not connect to Groq.') from error

    def check_model(self) -> None:
        """Validate the API key and configured model without generating a completion."""
        try:
            response = self._client.get(
                f'{self.base_url}/models/{self.model}',
                headers={'Authorization': f'Bearer {self.api_key}'},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError('Groq did not respond before the request timed out.') from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 429:
                raise ProviderRateLimitError() from error
            if status in (401, 403):
                raise ProviderConfigurationError('Groq rejected the API key or its permissions.') from error
            if status == 404:
                raise ModelNotFoundError(self.model) from error
            raise ProviderResponseError(f'Groq request failed with status {status}.') from error
        except httpx.RequestError as error:
            raise ProviderConnectionError('Could not connect to Groq.') from error
        except ValueError as error:
            raise ProviderResponseError('Groq returned an invalid model response.') from error
        if not isinstance(payload, dict) or payload.get('id') != self.model:
            raise ProviderResponseError('Groq returned an unexpected model response.')

    def generate(self, prompt: str, temperature: float) -> GeneratedResponse:
        started = time.perf_counter()
        try:
            response = self._request(
                '/chat/completions',
                json={
                    'model': self.model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': temperature,
                    'stream': False,
                },
            )
            payload = response.json()
        except ValueError as error:
            raise ProviderResponseError('Groq returned an invalid JSON response.') from error
        if not isinstance(payload, dict):
            raise ProviderResponseError('Groq returned an invalid response.')
        choices = payload.get('choices')
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderResponseError('Groq returned no completion choices.')
        message = choices[0].get('message')
        text = message.get('content') if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ProviderResponseError('Groq returned an invalid completion.')
        usage = payload.get('usage') or {}
        prompt_tokens = usage.get('prompt_tokens') if isinstance(usage, dict) else None
        completion_tokens = usage.get('completion_tokens') if isinstance(usage, dict) else None
        for count in (prompt_tokens, completion_tokens):
            if count is not None and (not isinstance(count, int) or count < 0):
                raise ProviderResponseError('Groq returned invalid token usage.')
        elapsed = round((time.perf_counter() - started) * 1000)
        return GeneratedResponse(text, elapsed, prompt_tokens, completion_tokens)

    def close(self) -> None:
        self._client.close()


class ProviderRateLimitError(ProviderError):
    def __init__(self):
        super().__init__('provider_rate_limit', 'Groq free-tier rate limit reached. Wait for the limit to reset and try again.')

PROVIDERS: dict[str, type] = {'ollama': OllamaProvider, 'groq': GroqProvider}


def configured_model(name: str) -> str | None:
    """Return the model the backend is configured to use for a provider, if any."""
    key = name.strip().lower()
    if key == 'ollama':
        return os.getenv('OLLAMA_MODEL', 'llama3.2').strip()
    if key == 'groq':
        return os.getenv('GROQ_MODEL', 'openai/gpt-oss-20b').strip()
    return None


def create_provider(name: str, model: str | None = None) -> AIProvider:
    provider_type = PROVIDERS.get(name.strip().lower())
    if provider_type is None:
        raise ProviderConfigurationError(f'Unsupported provider "{name}".')
    return provider_type(model=model)
