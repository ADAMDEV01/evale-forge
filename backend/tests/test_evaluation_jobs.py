from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app import main
from backend.app.db import database
from backend.app.jobs import evaluation_worker
from backend.app.models.models import EvaluationJob, EvaluationResult, EvaluationRun, User


class QueueFakeProvider:
    name = 'ollama'
    model = 'llama3.2'

    def __init__(self, outputs=None, fail_at=None, on_first_response=None):
        self.outputs = outputs or ['Business plan']
        self.fail_at = fail_at
        self.on_first_response = on_first_response
        self.calls = 0

    def check_model(self):
        return None

    def generate(self, prompt, temperature):
        if self.fail_at is not None and self.calls == self.fail_at:
            from backend.app.services.providers import ProviderConnectionError
            raise ProviderConnectionError()
        if self.on_first_response is not None and self.calls == 0:
            self.on_first_response()
        from backend.app.services.providers import GeneratedResponse
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return GeneratedResponse(output, 12, 4, 3)

    def close(self):
        return None


def enqueue(client, *, cases=2):
    client.post('/api/datasets', json={
        'id': 'queue-ds',
        'name': 'Queue dataset',
        'version': 'v3',
    })
    for index in range(cases):
        client.post('/api/test-cases', json={
            'id': f'queue-case-{index}',
            'datasetId': 'queue-ds',
            'title': f'Queue case {index}',
            'input': f'Prompt {index}',
            'expected': 'Business plan',
            'expectedKeywords': ['business plan'],
            'category': 'Queue tests',
        })
    response = client.post('/api/evaluate/jobs', json={
        'datasetId': 'queue-ds',
        'model': 'llama3.2',
        'evaluationMethod': 'exact_match',
    })
    assert response.status_code == 202, response.text
    return response.json()


def get_job(client, job_id):
    response = client.get(f'/api/evaluate/jobs/{job_id}')
    assert response.status_code == 200, response.text
    return response.json()


def test_enqueue_returns_pending_job_without_running_provider(client, monkeypatch):
    monkeypatch.setattr(
        main,
        'create_provider',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('The API request must not execute the provider inline.')
        ),
    )
    queued = enqueue(client)

    assert queued['status'] == 'Pending'
    assert queued['progress'] == 0
    assert queued['pending'] == 2
    assert queued['run']['status'] == 'Pending'
    assert queued['results'] == []
    assert get_job(client, queued['jobId'])['status'] == 'Pending'


def test_worker_executes_queued_job_and_persists_real_results(client, monkeypatch):
    queued = enqueue(client)
    provider = QueueFakeProvider(outputs=['Business plan', 'Business plan'])
    monkeypatch.setattr(main, 'create_provider', lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(evaluation_worker, 'HEARTBEAT_INTERVAL_SECONDS', 60)

    assert evaluation_worker.run_once(worker_id='queue-test-worker') is True

    details = get_job(client, queued['jobId'])
    assert details['status'] == 'Completed'
    assert details['progress'] == 100
    assert details['pending'] == 0
    assert details['run']['status'] == 'Completed'
    assert len(details['results']) == 2
    assert all(result['actual'] == 'Business plan' for result in details['results'])
    assert provider.calls == 2


def test_job_uses_test_case_snapshot_captured_at_enqueue_time(client, monkeypatch):
    queued = enqueue(client, cases=1)
    client.post('/api/test-cases', json={
        'id': 'queue-case-0',
        'datasetId': 'queue-ds',
        'title': 'Changed after enqueue',
        'input': 'Mutated prompt',
        'expected': 'Mutated expected',
        'expectedKeywords': ['mutated'],
        'category': 'Changed',
    })
    monkeypatch.setattr(
        main,
        'create_provider',
        lambda *_args, **_kwargs: QueueFakeProvider(['Business plan']),
    )

    evaluation_worker.run_once(worker_id='snapshot-worker')

    details = get_job(client, queued['jobId'])
    assert details['status'] == 'Completed'
    assert details['results'][0]['testCaseTitle'] == 'Queue case 0'
    assert details['results'][0]['input'] == 'Prompt 0'
    assert details['results'][0]['expected'] == 'Business plan'


def test_worker_retries_transient_provider_error_without_duplicate_results(
    client,
    isolated_test_database,
    monkeypatch,
):
    queued = enqueue(client, cases=2)
    first_provider = QueueFakeProvider(outputs=['Business plan'], fail_at=1)
    monkeypatch.setattr(main, 'create_provider', lambda *_args, **_kwargs: first_provider)

    evaluation_worker.run_once(worker_id='retry-worker')

    with database.SessionLocal() as db:
        job = db.get(EvaluationJob, queued['jobId'])
        assert job is not None
        assert job.status == 'Pending'
        assert job.attempts == 1
        job.available_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        saved = db.scalars(
            select(EvaluationResult).where(EvaluationResult.run_id == job.run_id)
        ).all()
        assert len(saved) == 1
        first_result_id = saved[0].id
        db.commit()

    second_provider = QueueFakeProvider(outputs=['Business plan'])
    monkeypatch.setattr(main, 'create_provider', lambda *_args, **_kwargs: second_provider)
    evaluation_worker.run_once(worker_id='retry-worker')

    details = get_job(client, queued['jobId'])
    assert details['status'] == 'Completed'
    assert len(details['results']) == 2
    assert second_provider.calls == 1
    assert details['results'][0]['id'] == first_result_id


def test_user_can_cancel_a_running_job_between_test_cases(client, monkeypatch):
    queued = enqueue(client, cases=2)

    def request_cancellation():
        response = client.post(f"/api/evaluate/jobs/{queued['jobId']}/cancel")
        assert response.status_code == 200
        assert response.json()['cancelRequested'] is True

    provider = QueueFakeProvider(
        outputs=['Business plan'],
        on_first_response=request_cancellation,
    )
    monkeypatch.setattr(main, 'create_provider', lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(evaluation_worker, 'HEARTBEAT_INTERVAL_SECONDS', 0.01)

    evaluation_worker.run_once(worker_id='cancel-worker')

    details = get_job(client, queued['jobId'])
    assert details['status'] == 'Cancelled'
    assert details['run']['status'] == 'Cancelled'
    assert len(details['results']) == 1


def test_pending_job_can_be_cancelled_before_a_worker_claims_it(client):
    queued = enqueue(client, cases=1)

    response = client.post(f"/api/evaluate/jobs/{queued['jobId']}/cancel")

    assert response.status_code == 200
    assert response.json()['status'] == 'Cancelled'
    details = get_job(client, queued['jobId'])
    assert details['status'] == 'Cancelled'
    assert details['run']['status'] == 'Cancelled'


def test_job_lookup_is_scoped_to_the_authenticated_owner(client, isolated_test_database):
    queued = enqueue(client, cases=1)
    with database.SessionLocal() as db:
        job = db.get(EvaluationJob, queued['jobId'])
        assert job is not None
        db.add(User(
            id='different-user-id-00000000001',
            email='other-user@example.invalid',
            password_hash='test-hash',
            is_active=True,
        ))
        db.flush()
        job.user_id = 'different-user-id-00000000001'
        db.commit()

    response = client.get(f"/api/evaluate/jobs/{queued['jobId']}")
    assert response.status_code == 404
