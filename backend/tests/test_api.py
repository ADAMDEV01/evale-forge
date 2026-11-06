import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from backend.app.main import app
from backend.app.models.models import Dataset, EvaluationResult, EvaluationRun


def test_health_check(client: TestClient):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_dataset_crud(client: TestClient):
    payload = {
        'id': 'ds-test',
        'name': 'Test dataset',
        'description': 'desc',
        'version': 'v1.0',
        'cases': 2,
        'createdAt': '2025-01-01',
        'modifiedAt': '2025-01-01',
        'color': 'violet',
    }
    create_response = client.post('/api/datasets', json=payload)
    assert create_response.status_code == 200
    assert any(item['id'] == 'ds-test' for item in create_response.json())

    list_response = client.get('/api/datasets')
    assert any(item['id'] == 'ds-test' for item in list_response.json())

    delete_response = client.delete('/api/datasets/ds-test')
    assert delete_response.status_code == 200


def test_dataset_deletion_is_rejected_when_evaluation_history_exists(client: TestClient):
    create_response = client.post('/api/datasets', json={
        'id': 'ds-with-run',
        'name': 'Dataset with evaluation history',
    })
    assert create_response.status_code == 200

    run_response = client.post('/api/runs', json={
        'id': 'run-for-dataset',
        'dataset_id': 'ds-with-run',
        'datasetVersion': 'v1.0',
        'model': 'test-model',
    })
    assert run_response.status_code == 200

    delete_response = client.delete('/api/datasets/ds-with-run')

    assert delete_response.status_code == 409
    assert delete_response.json()['detail'] == (
        'The dataset cannot be permanently deleted because evaluation history exists. '
        'Keep the dataset to preserve its history.'
    )
    assert any(item['id'] == 'ds-with-run' for item in client.get('/api/datasets').json())
    assert any(item['id'] == 'run-for-dataset' for item in client.get('/api/runs').json())


def test_run_creation_uses_dataset_id_and_preserves_response_dataset_name(client: TestClient):
    client.post('/api/datasets', json={
        'id': 'ds-run-create',
        'name': 'Readable dataset name',
        'version': 'v2',
    })

    response = client.post('/api/runs', json={
        'id': 'run-create',
        'dataset_id': 'ds-run-create',
        'datasetVersion': 'v2',
        'model': 'test-model',
    })

    assert response.status_code == 200
    saved_run = next(item for item in response.json() if item['id'] == 'run-create')
    assert saved_run['dataset'] == 'Readable dataset name'
    assert 'dataset_id' not in saved_run


def test_run_creation_rejects_unknown_dataset_id_without_saving_run(client: TestClient):
    response = client.post('/api/runs', json={
        'id': 'run-unknown-dataset',
        'dataset_id': 'missing-dataset',
        'datasetVersion': 'v1.0',
        'model': 'test-model',
    })

    assert response.status_code == 404
    assert response.json()['detail'] == 'Dataset not found'
    assert all(item['id'] != 'run-unknown-dataset' for item in client.get('/api/runs').json())


def test_run_creation_does_not_resolve_dataset_name(client: TestClient):
    client.post('/api/datasets', json={
        'id': 'ds-name-lookup',
        'name': 'Dataset name, not ID',
    })

    response = client.post('/api/runs', json={
        'id': 'run-name-lookup',
        'dataset_id': 'Dataset name, not ID',
        'datasetVersion': 'v1.0',
        'model': 'test-model',
    })

    assert response.status_code == 404
    assert all(item['id'] != 'run-name-lookup' for item in client.get('/api/runs').json())


def test_run_update_rejects_unknown_dataset_without_partially_updating_run(client: TestClient):
    client.post('/api/datasets', json={
        'id': 'ds-existing-run',
        'name': 'Existing dataset',
    })
    client.post('/api/runs', json={
        'id': 'run-existing',
        'dataset_id': 'ds-existing-run',
        'datasetVersion': 'v1.0',
        'model': 'original-model',
    })

    response = client.post('/api/runs', json={
        'id': 'run-existing',
        'dataset_id': 'missing-dataset',
        'datasetVersion': 'v2',
        'model': 'changed-model',
    })

    assert response.status_code == 404
    saved_run = next(item for item in client.get('/api/runs').json() if item['id'] == 'run-existing')
    assert saved_run['dataset'] == 'Existing dataset'
    assert saved_run['datasetVersion'] == 'v1.0'
    assert saved_run['model'] == 'original-model'


def test_run_creation_validates_missing_and_malformed_dataset_id(client: TestClient):
    base_payload = {
        'id': 'run-invalid-dataset-id',
        'datasetVersion': 'v1.0',
        'model': 'test-model',
    }

    missing_id = client.post('/api/runs', json={**base_payload, 'dataset': 'Dataset name'})
    empty_id = client.post('/api/runs', json={**base_payload, 'dataset_id': ''})
    blank_id = client.post('/api/runs', json={**base_payload, 'dataset_id': '   '})
    non_string_id = client.post('/api/runs', json={**base_payload, 'dataset_id': 123})

    assert missing_id.status_code == 422
    assert empty_id.status_code == 422
    assert blank_id.status_code == 422
    assert non_string_id.status_code == 422


def _seed_runs_with_results(isolated_test_database, runs: dict[str, list[str]]) -> None:
    test_session = sessionmaker(bind=isolated_test_database['engine'])
    with test_session() as session:
        session.add(Dataset(
            id='ds-run-counts',
            user_id='test-authenticated-user',
            name='Run counts dataset',
        ))
        for run_id, statuses in runs.items():
            session.add(EvaluationRun(
                id=run_id,
                user_id='test-authenticated-user',
                dataset_id='ds-run-counts',
                dataset_version='v1.0',
                model='test-model',
            ))
            for index, result_status in enumerate(statuses):
                session.add(EvaluationResult(
                    id=f'{run_id}-result-{index}',
                    run_id=run_id,
                    test_case_id=f'{run_id}-case-{index}',
                    status=result_status,
                ))
        session.commit()


def test_run_list_returns_zero_persisted_result_count(client, isolated_test_database):
    _seed_runs_with_results(isolated_test_database, {'run-zero': []})

    response = client.get('/api/runs')

    assert response.status_code == 200
    assert response.json()[0]['persisted_results_count'] == 0


def test_run_list_counts_multiple_completed_results(client, isolated_test_database):
    _seed_runs_with_results(isolated_test_database, {'run-completed': ['Completed', 'Completed', 'Completed']})

    response = client.get('/api/runs')

    assert response.status_code == 200
    assert response.json()[0]['persisted_results_count'] == 3


def test_run_list_counts_multiple_error_results(client, isolated_test_database):
    _seed_runs_with_results(isolated_test_database, {'run-errors': ['Error', 'Error']})

    response = client.get('/api/runs')

    assert response.status_code == 200
    assert response.json()[0]['persisted_results_count'] == 2


def test_run_list_counts_completed_and_error_results(client, isolated_test_database):
    _seed_runs_with_results(isolated_test_database, {'run-mixed': ['Completed', 'Error', 'Completed']})

    response = client.get('/api/runs')

    assert response.status_code == 200
    assert response.json()[0]['persisted_results_count'] == 3


def test_run_list_counts_each_run_without_n_plus_one_queries(client, isolated_test_database):
    _seed_runs_with_results(isolated_test_database, {
        'run-zero': [],
        'run-completed': ['Completed', 'Completed'],
        'run-errors': ['Error', 'Error', 'Error'],
        'run-mixed': ['Completed', 'Error'],
    })
    select_queries = []

    def record_select_query(execute_state):
        if execute_state.is_select:
            select_queries.append(execute_state)

    event.listen(OrmSession, 'do_orm_execute', record_select_query)
    try:
        response = client.get('/api/runs')
    finally:
        event.remove(OrmSession, 'do_orm_execute', record_select_query)

    assert response.status_code == 200
    counts = {run['id']: run['persisted_results_count'] for run in response.json()}
    assert counts == {
        'run-zero': 0,
        'run-completed': 2,
        'run-errors': 3,
        'run-mixed': 2,
    }
    assert len(select_queries) == 3


def _seed_failure_breakdown_data(
    isolated_test_database,
    runs: dict[str, dict[str, str]],
    results: list[dict[str, object]],
) -> None:
    test_session = sessionmaker(bind=isolated_test_database['engine'])
    with test_session() as session:
        session.add(Dataset(
            id='ds-failure-breakdown',
            user_id='test-authenticated-user',
            name='Failure breakdown dataset',
        ))
        for run_id, run_values in runs.items():
            session.add(EvaluationRun(
                id=run_id,
                user_id='test-authenticated-user',
                dataset_id='ds-failure-breakdown',
                dataset_name=f'Dataset for {run_id}',
                dataset_version='v1.0',
                model=f'model-{run_id}',
                provider=run_values['provider'],
                status=run_values['status'],
                date=f'date-{run_id}',
            ))
        for result in results:
            session.add(EvaluationResult(
                id=str(result['id']),
                run_id=str(result['run_id']),
                test_case_id=f"case-{result['id']}",
                test_case_title=f"Case {result['id']}",
                category='General',
                status=str(result['status']),
                passed=bool(result['passed']),
                score=0.25,
            ))
        session.commit()


@pytest.mark.parametrize('run_status', ['Completed', 'Failed'])
def test_failure_breakdown_includes_evaluation_failures_for_eligible_runs(
    client: TestClient,
    isolated_test_database,
    run_status: str,
):
    _seed_failure_breakdown_data(
        isolated_test_database,
        {'eligible-run': {'status': run_status, 'provider': 'ollama'}},
        [{'id': 'eval-failure', 'run_id': 'eligible-run', 'status': 'Completed', 'passed': False}],
    )

    response = client.get('/api/failures')

    assert response.status_code == 200
    failure = response.json()[0]
    assert failure['id'] == 'eval-failure'
    assert failure['run_status'] == run_status
    assert failure['run_provider'] == 'ollama'
    assert failure['failure_type'] == 'evaluation_failure'


@pytest.mark.parametrize('run_status', ['Completed', 'Failed'])
def test_failure_breakdown_includes_evaluation_errors_for_eligible_runs(
    client: TestClient,
    isolated_test_database,
    run_status: str,
):
    _seed_failure_breakdown_data(
        isolated_test_database,
        {'eligible-run': {'status': run_status, 'provider': 'ollama'}},
        [{'id': 'eval-error', 'run_id': 'eligible-run', 'status': 'Error', 'passed': False}],
    )

    response = client.get('/api/failures')

    assert response.status_code == 200
    error = response.json()[0]
    assert error['id'] == 'eval-error'
    assert error['run_status'] == run_status
    assert error['run_provider'] == 'ollama'
    assert error['failure_type'] == 'evaluation_error'


@pytest.mark.parametrize(
    ('run_values', 'result_status', 'passed'),
    [
        ({'status': 'Running', 'provider': 'ollama'}, 'Completed', False),
        ({'status': 'Pending', 'provider': 'ollama'}, 'Error', False),
        ({'status': 'Completed', 'provider': 'mock'}, 'Completed', False),
        ({'status': 'Failed', 'provider': 'ollama'}, 'Completed', True),
        ({'status': 'Completed', 'provider': 'ollama'}, 'Pending', False),
    ],
)
def test_failure_breakdown_excludes_ineligible_parent_or_result(
    client: TestClient,
    isolated_test_database,
    run_values: dict[str, str],
    result_status: str,
    passed: bool,
):
    _seed_failure_breakdown_data(
        isolated_test_database,
        {'ineligible-run': run_values},
        [{'id': 'excluded-result', 'run_id': 'ineligible-run', 'status': result_status, 'passed': passed}],
    )

    response = client.get('/api/failures')

    assert response.status_code == 200
    assert response.json() == []


def test_failure_breakdown_returns_parent_metadata_and_classification_for_multiple_runs(
    client: TestClient,
    isolated_test_database,
):
    _seed_failure_breakdown_data(
        isolated_test_database,
        {
            'completed-run': {'status': 'Completed', 'provider': 'ollama'},
            'failed-run': {'status': 'Failed', 'provider': 'ollama'},
        },
        [
            {'id': 'completed-failure', 'run_id': 'completed-run', 'status': 'Completed', 'passed': False},
            {'id': 'failed-error', 'run_id': 'failed-run', 'status': 'Error', 'passed': False},
        ],
    )

    response = client.get('/api/failures')

    assert response.status_code == 200
    failures = {failure['id']: failure for failure in response.json()}
    assert {
        result_id: (failure['run_status'], failure['run_provider'], failure['failure_type'])
        for result_id, failure in failures.items()
    } == {
        'completed-failure': ('Completed', 'ollama', 'evaluation_failure'),
        'failed-error': ('Failed', 'ollama', 'evaluation_error'),
    }


def test_failure_breakdown_uses_constant_select_count_for_multiple_runs(
    client: TestClient,
    isolated_test_database,
):
    _seed_failure_breakdown_data(
        isolated_test_database,
        {
            'completed-run': {'status': 'Completed', 'provider': 'ollama'},
            'failed-run': {'status': 'Failed', 'provider': 'ollama'},
        },
        [
            {'id': 'first-failure', 'run_id': 'completed-run', 'status': 'Completed', 'passed': False},
            {'id': 'second-error', 'run_id': 'failed-run', 'status': 'Error', 'passed': False},
        ],
    )
    select_queries = []

    def record_select_query(execute_state):
        if execute_state.is_select:
            select_queries.append(execute_state)

    event.listen(OrmSession, 'do_orm_execute', record_select_query)
    try:
        response = client.get('/api/failures')
    finally:
        event.remove(OrmSession, 'do_orm_execute', record_select_query)

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert len(select_queries) == 3


def test_failure_breakdown_returns_empty_list_when_no_results_match(client: TestClient):
    response = client.get('/api/failures')

    assert response.status_code == 200
    assert response.json() == []


def test_deleting_nonexistent_dataset_returns_not_found(client: TestClient):
    response = client.delete('/api/datasets/missing-dataset')

    assert response.status_code == 404
    assert response.json()['detail'] == 'Dataset not found'


def test_test_case_crud(client: TestClient):
    client.post('/api/datasets', json={'id': 'ds-test', 'name': 'Test dataset'})
    payload = {
        'id': 'tc-test',
        'datasetId': 'ds-test',
        'title': 'Test case title',
        'input': 'Which plan includes audit logs?',
        'expected': 'Business plan',
        'criteria': 'Must mention plan tier',
        'category': 'Grounding',
        'tags': ['plan', 'grounding'],
        'importance': 'High',
        'expectedBehavior': 'Answer with correct plan information',
    }
    create_response = client.post('/api/test-cases', json=payload)
    assert create_response.status_code == 200

    list_response = client.get('/api/test-cases')
    assert any(item['id'] == 'tc-test' for item in list_response.json())

    delete_response = client.delete('/api/test-cases/tc-test')
    assert delete_response.status_code == 200


def test_test_case_creation_rejects_missing_dataset(client: TestClient):
    response = client.post('/api/test-cases', json={
        'id': 'orphan-case',
        'datasetId': 'missing-dataset',
        'title': 'Orphan case',
        'input': 'Prompt',
        'expected': 'Answer',
    })

    assert response.status_code == 404
    assert response.json()['detail'] == 'Dataset not found'
    assert all(item['id'] != 'orphan-case' for item in client.get('/api/test-cases').json())


def test_rubric_validation_and_persistence(client: TestClient):
    rubric = {
        'id': 'rubric-test',
        'name': 'Quality rubric',
        'description': 'Balanced weights',
        'active': True,
        'criteria': [
            {'name': 'Accuracy', 'weight': 60, 'description': 'Factual accuracy', 'scale': '0–5', 'expectedKeywords': ['accurate']},
            {'name': 'Clarity', 'weight': 40, 'description': 'Clear response', 'scale': '0–5', 'expectedKeywords': ['clear']},
        ],
    }
    response = client.post('/api/rubrics', json=rubric)
    assert response.status_code == 200
    body = response.json()
    assert any(item['id'] == 'rubric-test' for item in body)

    invalid_rubrics = [
        {**rubric, 'criteria': []},
        {**rubric, 'criteria': [{'name': 'A', 'weight': 0, 'description': 'x', 'scale': '0–5', 'expectedKeywords': ['a']}]},
        {**rubric, 'criteria': [{'name': 'A', 'weight': 100, 'description': 'x', 'scale': '0–5', 'expectedKeywords': []}]},
    ]
    for invalid in invalid_rubrics:
        assert client.post('/api/rubrics', json=invalid).status_code == 422
    assert any(item['id'] == 'rubric-test' for item in client.get('/api/rubrics').json())


def test_evaluation_metrics_and_exact_match(client: TestClient):
    payload = {
        'datasetId': 'missing',
        'models': ['GPT-4o'],
        'metrics': ['accuracy'],
        'rubric': 'Quality rubric',
        'concurrency': 2,
        'temperature': 0.1,
    }
    response = client.post('/api/evaluate', json=payload)
    assert response.status_code == 404


def test_invalid_requests_are_rejected(client: TestClient):
    response = client.post('/api/datasets', json={'id': '', 'name': ''})
    assert response.status_code in {200, 422}
