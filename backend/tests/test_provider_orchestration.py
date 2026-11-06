import pytest

from backend.app.services.provider_orchestration import ProviderExecutionError, execute_provider
from backend.app.services.providers import GeneratedResponse, ProviderConnectionError


class ProviderWithoutModelCheck:
    name = 'example'
    model = 'example-model'

    def __init__(self, fail_at=None, close_error=None):
        self.fail_at = fail_at
        self.close_error = close_error
        self.calls = 0
        self.closed = False

    def generate(self, prompt, temperature):
        if self.calls == self.fail_at:
            raise ProviderConnectionError()
        self.calls += 1
        return GeneratedResponse(prompt, 1)

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def test_provider_without_model_check_generates_and_closes():
    provider = ProviderWithoutModelCheck()
    initialized = []
    responses = []

    execute_provider(
        lambda name, model: provider,
        'example',
        'example-model',
        ['first', 'second'],
        0.1,
        initialized.append,
        responses.append,
    )

    assert [response.text for response in responses] == ['first', 'second']
    assert initialized == [provider]
    assert provider.closed


def test_generation_error_preserves_prior_responses_and_closes_provider():
    provider = ProviderWithoutModelCheck(fail_at=1)
    responses = []

    with pytest.raises(ProviderExecutionError) as error:
        execute_provider(
            lambda name, model: provider,
            'example',
            'example-model',
            ['first', 'second'],
            0,
            lambda initialized: None,
            responses.append,
        )

    assert error.value.stage == 'generation'
    assert isinstance(error.value.error, ProviderConnectionError)
    assert [response.text for response in responses] == ['first']
    assert provider.closed


def test_model_check_error_is_classified_as_initialization_and_closes_provider():
    class ModelCheckProvider(ProviderWithoutModelCheck):
        def check_model(self):
            raise ProviderConnectionError()

    provider = ModelCheckProvider()

    with pytest.raises(ProviderExecutionError) as error:
        execute_provider(
            lambda name, model: provider,
            'example',
            'example-model',
            ['first'],
            0,
            lambda initialized: None,
            lambda response: None,
        )

    assert error.value.stage == 'initialization'
    assert isinstance(error.value.error, ProviderConnectionError)
    assert provider.closed


def test_cleanup_error_is_reported_after_successful_generation():
    provider = ProviderWithoutModelCheck(close_error=RuntimeError('cleanup failure'))
    responses = []

    with pytest.raises(ProviderExecutionError) as error:
        execute_provider(
            lambda name, model: provider,
            'example',
            'example-model',
            ['first'],
            0,
            lambda initialized: None,
            responses.append,
        )

    assert error.value.stage == 'cleanup'
    assert str(error.value.error) == 'cleanup failure'
    assert [response.text for response in responses] == ['first']
    assert provider.closed
