from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app import main
from backend.app.models.models import EvaluationResult, EvaluationRun
from backend.app.services.providers import GeneratedResponse, ModelNotFoundError, ProviderConnectionError


class FakeProvider:
    name = 'ollama'
    model = 'llama3.2'

    def __init__(self, outputs=None, check_error=None, fail_at=None, unexpected_fail_at=None, close_error=None):
        self.outputs = outputs or ['Business plan', 'Other']
        self.check_error = check_error
        self.fail_at = fail_at
        self.unexpected_fail_at = unexpected_fail_at
        self.close_error = close_error
        self.calls = 0

    def check_model(self):
        if self.check_error:
            raise self.check_error

    def generate(self, prompt, temperature):
        if self.fail_at == self.calls:
            raise ProviderConnectionError()
        if self.unexpected_fail_at == self.calls:
            raise RuntimeError('unexpected generation failure')
        from backend.app.services.providers import GeneratedResponse

        text = self.outputs[self.calls % len(self.outputs)]
        self.calls += 1
        return GeneratedResponse(text, 12, 4, 3)

    def close(self):
        if self.close_error:
            raise self.close_error


def prepare_dataset(client, cases=1):
    client.post('/api/datasets', json={
        'id': 'eval-ds',
        'name': 'Evaluation dataset',
        'version': 'v2',
    })
    for index in range(cases):
        client.post('/api/test-cases', json={
            'id': f'case-{index}',
            'datasetId': 'eval-ds',
            'title': f'Case {index}',
            'input': f'Prompt {index}',
            'expected': 'Business plan',
            'expectedKeywords': ['business plan'],
            'category': 'Support',
        })


def test_real_evaluation_persists_actual_responses_and_immutable_expected_snapshots(client, monkeypatch):
    prepare_dataset(client)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: FakeProvider(['Business plan']))
    response = client.post('/api/evaluate', json={
        'datasetId': 'eval-ds',
        'model': 'llama3.2',
        'evaluationMethod': 'exact_match',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['run']['provider'] == 'ollama'
    assert body['run']['status'] == 'Completed'
    assert body['run']['passed'] == 1
    assert body['results'][0]['actual'] == 'Business plan'
    assert body['results'][0]['expected'] == 'Business plan'
    assert body['results'][0]['input'] == 'Prompt 0'
    assert body['results'][0]['tokenUsage'] == 7
    assert body['run']['estimatedCost'] == 0.0

    client.post('/api/test-cases', json={
        'id': 'case-0',
        'datasetId': 'eval-ds',
        'title': 'Changed title',
        'input': 'Changed input',
        'expected': 'Changed expected',
    })
    historical = client.get(f"/api/runs/{body['run']['id']}").json()
    assert historical['results'][0]['expected'] == 'Business plan'
    assert historical['results'][0]['input'] == 'Prompt 0'
    assert historical['results'][0]['testCaseTitle'] == 'Case 0'


def test_provider_connection_error_fails_run_without_creating_a_failed_test_result(client, monkeypatch):
    prepare_dataset(client)
    monkeypatch.setattr(
        main,
        'create_provider',
        lambda name, model=None: FakeProvider(check_error=ProviderConnectionError()),
    )
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})
    assert response.status_code == 503
    detail = response.json()['detail']
    run = client.get(f"/api/runs/{detail['runId']}").json()
    assert run['run']['status'] == 'Failed'
    assert run['run']['errorType'] == 'provider_connection'
    assert run['results'] == []


def test_missing_model_is_distinct_from_a_model_answer_failure(client, monkeypatch):
    prepare_dataset(client)
    monkeypatch.setattr(
        main,
        'create_provider',
        lambda name, model=None: FakeProvider(check_error=ModelNotFoundError('missing-model')),
    )
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'missing-model'})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert detail['code'] == 'model_not_found'
    assert client.get(f"/api/runs/{detail['runId']}").json()['results'] == []


def test_provider_error_mid_run_preserves_completed_work_and_marks_run_failed(client, monkeypatch):
    prepare_dataset(client, cases=2)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: FakeProvider(fail_at=1))
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})
    assert response.status_code == 503
    run_id = response.json()['detail']['runId']
    details = client.get(f'/api/runs/{run_id}').json()
    assert details['run']['status'] == 'Failed'
    assert details['run']['errorType'] == 'provider_connection'
    assert len(details['results']) == 1
    assert details['results'][0]['status'] == 'Completed'


def test_generation_error_keeps_original_http_error_when_close_also_fails(client, monkeypatch):
    prepare_dataset(client, cases=2)
    provider = FakeProvider(fail_at=1, close_error=RuntimeError('cleanup failure'))
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'provider_connection'
    assert provider.calls == 1
    details = client.get(f"/api/runs/{response.json()['detail']['runId']}").json()
    assert details['run']['status'] == 'Failed'
    assert details['run']['errorType'] == 'provider_connection'
    assert details['run']['accuracy'] == 100
    assert len(details['results']) == 1


def test_successful_generation_with_close_error_fails_run_and_preserves_results(client, monkeypatch):
    prepare_dataset(client, cases=2)
    provider = FakeProvider(
        outputs=['Business plan', 'Business plan'],
        close_error=RuntimeError('cleanup failure'),
    )
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'provider_cleanup'
    details = client.get(f"/api/runs/{detail['runId']}").json()
    assert details['run']['status'] == 'Failed'
    assert details['run']['errorType'] == 'provider_cleanup'
    assert details['run']['accuracy'] == 100
    assert len(details['results']) == 2


def test_unexpected_factory_error_fails_run(client, monkeypatch):
    prepare_dataset(client)

    def fail_factory(name, model=None):
        raise RuntimeError('unexpected factory failure')

    monkeypatch.setattr(main, 'create_provider', fail_factory)
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'provider_initialization'
    details = client.get(f"/api/runs/{detail['runId']}").json()
    assert details['run']['status'] == 'Failed'
    assert details['run']['errorType'] == 'provider_initialization'
    assert details['results'] == []


def test_unexpected_generation_error_fails_run_and_preserves_prior_results(client, monkeypatch):
    prepare_dataset(client, cases=2)
    provider = FakeProvider(unexpected_fail_at=1)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'provider_generation'
    details = client.get(f"/api/runs/{detail['runId']}").json()
    assert details['run']['status'] == 'Failed'
    assert details['run']['errorType'] == 'provider_generation'
    assert details['run']['accuracy'] == 100
    assert len(details['results']) == 1


def test_result_persistence_error_marks_run_failed_without_partial_success(client, monkeypatch):
    prepare_dataset(client)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: FakeProvider(['Business plan']))
    original_commit = Session.commit

    def fail_result_commit(session):
        if any(isinstance(item, EvaluationResult) for item in session.new):
            raise SQLAlchemyError('simulated persistence failure')
        original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_result_commit)
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'evaluation_persistence'
    saved = client.get(f"/api/runs/{detail['runId']}").json()
    assert saved['run']['status'] == 'Failed'
    assert saved['run']['errorType'] == 'evaluation_persistence'
    assert saved['results'] == []


def test_provider_model_persistence_error_rolls_back_and_marks_run_failed(client, monkeypatch):
    prepare_dataset(client)
    provider = FakeProvider(['Business plan'])
    provider.model = 'resolved-model'
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)
    original_commit = Session.commit
    original_rollback = Session.rollback
    rollback_calls = []
    failed_once = False

    def fail_model_commit(session):
        nonlocal failed_once
        if not failed_once and any(
            isinstance(item, EvaluationRun) and item.model == 'resolved-model'
            for item in session.dirty
        ):
            failed_once = True
            raise SQLAlchemyError('provider model commit failed')
        original_commit(session)

    def record_rollback(session):
        rollback_calls.append(True)
        original_rollback(session)

    monkeypatch.setattr(Session, 'commit', fail_model_commit)
    monkeypatch.setattr(Session, 'rollback', record_rollback)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'evaluation_persistence'
    assert detail['failureStatusPersisted'] is True
    assert detail['originalError'] == 'provider model commit failed'
    assert rollback_calls
    saved = client.get(f"/api/runs/{detail['runId']}").json()
    assert saved['run']['status'] == 'Failed'
    assert saved['run']['errorType'] == 'evaluation_persistence'
    assert saved['results'] == []


def test_result_and_recovery_commit_failures_preserve_original_error_and_prior_results(client, monkeypatch):
    prepare_dataset(client, cases=2)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: FakeProvider(['Business plan']))
    original_commit = Session.commit
    result_commit_attempts = 0

    def fail_second_result_and_recovery_commits(session):
        nonlocal result_commit_attempts
        if any(isinstance(item, EvaluationResult) for item in session.new):
            result_commit_attempts += 1
            if result_commit_attempts == 2:
                raise SQLAlchemyError('original second-result commit failure')
        if any(
            isinstance(item, EvaluationRun)
            and item.status == 'Failed'
            and item.error_type == 'evaluation_persistence'
            for item in session.dirty
        ):
            raise SQLAlchemyError('recovery commit failure')
        original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_second_result_and_recovery_commits)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'evaluation_persistence'
    assert detail['failureStatusPersisted'] is False
    assert detail['originalError'] == 'original second-result commit failure'
    assert 'recovery commit failure' in detail['recoveryError']
    saved = client.get(f"/api/runs/{detail['runId']}").json()
    assert saved['run']['status'] == 'Running'
    assert len(saved['results']) == 1


def test_unexpected_provider_error_rolls_back_failed_session_before_recovery(client, monkeypatch):
    prepare_dataset(client)

    def fail_factory(name, model=None):
        raise RuntimeError('unexpected factory failure')

    monkeypatch.setattr(main, 'create_provider', fail_factory)
    persist_failure = main._persist_run_failure
    original_rollback = Session.rollback
    rollback_calls = []

    def poison_session_then_persist(db, run_id, user_id, error_type, error_message):
        try:
            db.execute(text('SELECT * FROM missing_test_table'))
        except SQLAlchemyError:
            pass
        return persist_failure(db, run_id, user_id, error_type, error_message)

    def record_rollback(session):
        rollback_calls.append(True)
        original_rollback(session)

    monkeypatch.setattr(main, '_persist_run_failure', poison_session_then_persist)
    monkeypatch.setattr(Session, 'rollback', record_rollback)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['failureStatusPersisted'] is True
    assert rollback_calls
    saved = client.get(f"/api/runs/{detail['runId']}").json()
    assert saved['run']['status'] == 'Failed'
    assert saved['run']['errorType'] == 'provider_initialization'


def test_second_result_commit_failure_recovers_metrics_from_persisted_results(
    client,
    isolated_test_database,
    monkeypatch,
):
    prepare_dataset(client, cases=3)
    provider = FakeProvider(['Business plan'])
    generate = provider.generate

    def generate_100ms(prompt, temperature):
        response = generate(prompt, temperature)
        return GeneratedResponse(response.text, 100, 4, 3)

    provider.generate = generate_100ms
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)
    original_commit = Session.commit
    result_commit_attempts = 0

    def fail_second_result_commit(session):
        nonlocal result_commit_attempts
        if any(isinstance(item, EvaluationResult) for item in session.new):
            result_commit_attempts += 1
            if result_commit_attempts == 2:
                raise SQLAlchemyError('second result commit failed')
        original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_second_result_commit)
    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    run_id = response.json()['detail']['runId']
    details = client.get(f'/api/runs/{run_id}').json()
    assert len(details['results']) == 1
    assert details['results'][0]['status'] == 'Completed'
    assert details['run']['total'] == 3
    assert details['run']['passed'] == 1
    assert details['run']['failed'] == 0
    assert details['run']['accuracy'] == 100
    assert details['run']['passRate'] == 100
    assert details['run']['latency'] == 100
    assert details['run']['tokenUsage'] == 7
    assert details['run']['estimatedCost'] == 0.0
    assert details['metrics']['accuracy'] == details['run']['accuracy']
    assert details['metrics']['passRate'] == details['run']['passRate']
    assert details['metrics']['averageLatency'] == details['run']['latency']
    assert details['metrics']['tokenUsage'] == details['run']['tokenUsage']
    assert details['metrics']['averageScore'] == 1
    with Session(isolated_test_database['engine']) as db:
        saved_run = db.get(EvaluationRun, run_id)
        assert saved_run is not None
        assert saved_run.score == 1

    assert provider.calls == 2


def test_recovery_excludes_persisted_error_from_scoring_and_token_usage(
    client,
    isolated_test_database,
    monkeypatch,
):
    prepare_dataset(client, cases=3)
    provider = FakeProvider(
        outputs=['Business plan', 'engine error'],
        fail_at=2,
    )
    generate = provider.generate

    def generate_partial_latency_and_tokens(prompt, temperature):
        response = generate(prompt, temperature)
        if response.text == 'Business plan':
            return GeneratedResponse(response.text, 100, 4, 3)
        return GeneratedResponse(response.text, 20, 2, 3)

    provider.generate = generate_partial_latency_and_tokens
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)
    original_evaluate = main.evaluate_exact_match
    monkeypatch.setattr(
        main,
        'evaluate_exact_match',
        lambda actual, expected: (_ for _ in ()).throw(ValueError('evaluation failed'))
        if actual == 'engine error' else original_evaluate(actual, expected),
    )

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 503
    run_id = response.json()['detail']['runId']
    details = client.get(f'/api/runs/{run_id}').json()
    assert [result['status'] for result in details['results']] == ['Completed', 'Error']
    assert details['run']['total'] == 3
    assert details['run']['passed'] == 1
    assert details['run']['failed'] == 0
    assert details['run']['accuracy'] == 100
    assert details['run']['passRate'] == 100
    assert details['run']['latency'] == 60
    assert details['run']['tokenUsage'] == 7
    assert details['run']['estimatedCost'] == 0.0
    assert details['metrics']['accuracy'] == details['run']['accuracy']
    assert details['metrics']['passRate'] == details['run']['passRate']
    assert details['metrics']['averageLatency'] == details['run']['latency']
    assert details['metrics']['averageScore'] == 1
    assert details['metrics']['tokenUsage'] == 7
    with Session(isolated_test_database['engine']) as db:
        saved_run = db.get(EvaluationRun, run_id)
        assert saved_run is not None
        assert saved_run.score == 1


def test_provider_cleanup_failure_is_supplemental_to_model_persistence_error(client, monkeypatch):
    prepare_dataset(client)
    provider = FakeProvider(['Business plan'], close_error=RuntimeError('cleanup also failed'))
    provider.model = 'resolved-model'
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: provider)
    original_commit = Session.commit
    failed_once = False

    def fail_model_commit(session):
        nonlocal failed_once
        if not failed_once and any(
            isinstance(item, EvaluationRun) and item.model == 'resolved-model'
            for item in session.dirty
        ):
            failed_once = True
            raise SQLAlchemyError('provider model commit failed')
        original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_model_commit)

    response = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})

    assert response.status_code == 500
    detail = response.json()['detail']
    assert detail['code'] == 'evaluation_persistence'
    assert detail['failureStatusPersisted'] is True
    assert any('cleanup also failed' in note for note in detail['supplementalErrors'])
    saved = client.get(f"/api/runs/{detail['runId']}").json()
    assert saved['run']['status'] == 'Failed'
    assert saved['run']['errorType'] == 'evaluation_persistence'


def test_keyword_configuration_requires_keywords_and_partial_engine_errors_are_visible(client, monkeypatch):
    prepare_dataset(client)
    client.post('/api/test-cases', json={
        'id': 'case-0',
        'datasetId': 'eval-ds',
        'title': 'Case 0',
        'input': 'Prompt 0',
        'expected': 'Business plan',
        'expectedKeywords': [],
    })
    invalid = client.post('/api/evaluate', json={
        'datasetId': 'eval-ds', 'model': 'llama3.2', 'evaluationMethod': 'keyword_match',
    })
    assert invalid.status_code == 422

    prepare_dataset(client, cases=2)
    monkeypatch.setattr(main, 'create_provider', lambda name, model=None: FakeProvider(['first', 'second']))
    original = main.evaluate_exact_match
    monkeypatch.setattr(
        main,
        'evaluate_exact_match',
        lambda actual, expected: (_ for _ in ()).throw(ValueError('engine error'))
        if actual == 'first' else original(actual, expected),
    )
    partial = client.post('/api/evaluate', json={'datasetId': 'eval-ds', 'model': 'llama3.2'})
    assert partial.status_code == 200
    body = partial.json()
    assert body['run']['status'] == 'Failed'
    assert body['errors'] == 1
    assert sorted(result['status'] for result in body['results']) == ['Completed', 'Error']
