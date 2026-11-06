import httpx
import pytest

from backend.app.services.providers import (
    ModelNotFoundError,
    OllamaProvider,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
    GroqProvider,
    ProviderRateLimitError,
    ProviderConfigurationError,
)


def make_provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaProvider(model='llama3.2', base_url='http://ollama.test', client=client)


def test_ollama_provider_checks_models_and_extracts_response_usage_and_latency():
    def handler(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'llama3.2:latest'}]})
        return httpx.Response(200, json={
            'response': 'generated answer',
            'prompt_eval_count': 11,
            'eval_count': 7,
        })

    provider = make_provider(handler)
    provider.check_model()
    response = provider.generate('test prompt', 0.2)
    assert response.text == 'generated answer'
    assert response.total_tokens == 18
    assert response.latency_ms >= 0
    provider.close()


def test_ollama_provider_reports_missing_model():
    provider = make_provider(lambda request: httpx.Response(200, json={'models': []}))
    with pytest.raises(ModelNotFoundError):
        provider.check_model()
    provider.close()


def test_ollama_provider_normalizes_connection_and_timeout_errors():
    def connection_failure(request):
        raise httpx.ConnectError('private connection details', request=request)

    def timeout(request):
        raise httpx.ReadTimeout('private timeout details', request=request)

    with pytest.raises(ProviderConnectionError, match='Could not connect'):
        make_provider(connection_failure).check_model()
    with pytest.raises(ProviderTimeoutError, match='timed out'):
        make_provider(timeout).check_model()


def test_ollama_provider_rejects_malformed_response():
    provider = make_provider(lambda request: httpx.Response(200, json={'unexpected': 'shape'}))
    with pytest.raises(ProviderResponseError):
        provider.generate('prompt', 0)
    provider.close()


def make_groq(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GroqProvider(
        model='openai/gpt-oss-20b',
        api_key='test-key',
        base_url='https://groq.test/openai/v1',
        client=client,
    )


def test_groq_provider_sends_authenticated_chat_request_and_extracts_usage():
    def handler(request):
        assert request.url.path == '/openai/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-key'
        body = __import__('json').loads(request.content)
        assert body['model'] == 'openai/gpt-oss-20b'
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]
        return httpx.Response(200, json={
            'choices': [{'message': {'content': 'real model response'}}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 8},
        })

    provider = make_groq(handler)
    result = provider.generate('hello', 0.1)
    assert result.text == 'real model response'
    assert result.total_tokens == 13
    provider.close()


def test_groq_provider_maps_rate_limit_and_invalid_key():
    rate_limited = make_groq(lambda request: httpx.Response(429, json={'error': 'limit'}))
    with pytest.raises(ProviderRateLimitError):
        rate_limited.generate('hello', 0)
    rate_limited.close()

    invalid_key = make_groq(lambda request: httpx.Response(401, json={'error': 'unauthorized'}))
    with pytest.raises(ProviderConfigurationError, match='API key'):
        invalid_key.generate('hello', 0)
    invalid_key.close()


def test_groq_provider_checks_configured_model_without_generating():
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == '/openai/v1/models/openai/gpt-oss-20b'
        assert request.headers['Authorization'] == 'Bearer test-key'
        return httpx.Response(200, json={'id': 'openai/gpt-oss-20b', 'object': 'model'})

    provider = make_groq(handler)
    provider.check_model()
    provider.close()


def test_groq_provider_health_check_maps_auth_and_missing_model_errors():
    invalid_key = make_groq(lambda request: httpx.Response(401, json={'error': 'unauthorized'}))
    with pytest.raises(ProviderConfigurationError, match='API key'):
        invalid_key.check_model()
    invalid_key.close()

    missing_model = make_groq(lambda request: httpx.Response(404, json={'error': 'not found'}))
    with pytest.raises(ModelNotFoundError):
        missing_model.check_model()
    missing_model.close()


def test_groq_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(ProviderConfigurationError, match='GROQ_API_KEY'):
        GroqProvider(model='openai/gpt-oss-20b')
