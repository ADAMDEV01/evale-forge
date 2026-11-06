from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from backend.app.services.providers import (
    AIProvider,
    GeneratedResponse,
    ModelCheckableProvider,
    ProviderError,
)


@dataclass
class ProviderExecutionError(Exception):
    error: Exception
    stage: Literal['initialization', 'generation', 'cleanup', 'persistence']
    recovery_error: Exception | None = None

    def __post_init__(self) -> None:
        super().__init__(str(self.error))


def check_model_if_supported(provider: AIProvider) -> bool:
    if not isinstance(provider, ModelCheckableProvider):
        return False
    provider.check_model()
    return True


def execute_provider(
    provider_factory: Callable[[str, str | None], AIProvider],
    provider_name: str,
    model: str | None,
    prompts: Iterable[str],
    temperature: float,
    on_provider_created: Callable[[AIProvider], None],
    on_response: Callable[[GeneratedResponse], None],
) -> None:
    provider: AIProvider | None = None
    active_error: BaseException | None = None
    try:
        try:
            provider = provider_factory(provider_name, model)
        except Exception as error:
            raise ProviderExecutionError(error, 'initialization') from error

        try:
            on_provider_created(provider)
            check_model_if_supported(provider)
        except ProviderExecutionError:
            raise
        except Exception as error:
            raise ProviderExecutionError(error, 'initialization') from error

        for prompt in prompts:
            try:
                response = provider.generate(prompt, temperature)
            except Exception as error:
                raise ProviderExecutionError(error, 'generation') from error
            on_response(response)
    except BaseException as error:
        active_error = error
        raise
    finally:
        if provider is not None:
            try:
                provider.close()
            except Exception as close_error:
                if active_error is not None:
                    active_error.add_note(f'Provider cleanup also failed: {close_error}')
                else:
                    raise ProviderExecutionError(close_error, 'cleanup') from close_error
