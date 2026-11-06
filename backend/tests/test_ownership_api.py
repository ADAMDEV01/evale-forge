import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app import main
from backend.app.models.models import (
    Dataset,
    EvaluationResult,
    EvaluationRun,
    HumanReview,
    Rubric,
    RubricCriterion,
    TestCase as CaseModel,
    User,
)
from backend.app.security.auth import create_access_token
from backend.app.services.providers import GeneratedResponse


PROTECTED_REQUESTS = [
    ('GET', '/api/auth/me', None),
    ('POST', '/api/auth/logout-all', None),
    ('GET', '/api/datasets', None),
    ('POST', '/api/datasets', {'id': 'd', 'name': 'Dataset'}),
    ('DELETE', '/api/datasets/d', None),
    ('GET', '/api/test-cases', None),
    ('POST', '/api/test-cases', {
        'id': 'c', 'datasetId': 'd', 'title': 'Case', 'input': 'in', 'expected': 'out',
    }),
    ('DELETE', '/api/test-cases/c', None),
    ('GET', '/api/failures', None),
    ('PUT', '/api/failures/f', {
        'id': 'f', 'testCase': 'Case', 'dataset': 'Dataset', 'model': 'model',
        'category': 'General',
    }),
    ('GET', '/api/runs', None),
    ('POST', '/api/runs', {
        'id': 'r', 'dataset_id': 'd', 'datasetVersion': 'v1', 'model': 'model',
    }),
    ('GET', '/api/runs/r', None),
    ('GET', '/api/rubrics', None),
    ('POST', '/api/rubrics', {'id': 'r', 'name': 'Rubric'}),
    ('POST', '/api/evaluate', {'datasetId': 'd'}),
]


def _request(client: TestClient, method: str, path: str, payload: dict | None, headers: dict):
    return client.request(method, path, json=payload, headers=headers)


def _insert_user(engine, user_id: str, email: str) -> dict[str, str]:
    with Session(engine) as session:
        session.add(User(
            id=user_id,
            email=email,
            password_hash='unused test hash',
            is_active=True,
        ))
        session.commit()
    return {'Authorization': f'Bearer {create_access_token(user_id)}'}


@pytest.mark.parametrize(('method', 'path', 'payload'), PROTECTED_REQUESTS)
@pytest.mark.parametrize('auth_header', [None, 'Bearer invalid-token'])
def test_every_business_route_rejects_anonymous_and_invalid_credentials(
    unauthenticated_client: TestClient,
    method: str,
    path: str,
    payload: dict | None,
    auth_header: str | None,
):
    headers = {'Authorization': auth_header} if auth_header else {}

    response = _request(unauthenticated_client, method, path, payload, headers)

    assert response.status_code == 401


def test_health_routes_remain_public(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(
        main,
        'create_provider',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            main.ProviderError('provider_connection', 'provider unavailable')
        ),
    )

    assert unauthenticated_client.get('/api/health').status_code == 200
    assert unauthenticated_client.get('/api/providers/ollama/health').status_code == 200


def test_lists_failures_and_aggregates_are_scoped_to_user_and_hide_unowned_rows(
    client,
    isolated_test_database,
):
    other_headers = _insert_user(
        isolated_test_database['engine'],
        'other-owner',
        'other-owner@example.test',
    )
    own_dataset = client.post('/api/datasets', json={
        'id': 'own-dataset',
        'name': 'Own dataset',
        'user_id': 'other-owner',
    })
    other_dataset = client.post(
        '/api/datasets',
        json={'id': 'other-dataset', 'name': 'Other dataset'},
        headers=other_headers,
    )
    assert own_dataset.status_code == other_dataset.status_code == 200
    with Session(isolated_test_database['engine']) as session:
        assert session.get(Dataset, 'own-dataset').user_id == 'test-authenticated-user'

    client.post('/api/test-cases', json={
        'id': 'own-case',
        'datasetId': 'own-dataset',
        'title': 'Own case',
        'input': 'input',
        'expected': 'expected',
    })
    client.post(
        '/api/test-cases',
        json={
            'id': 'other-case',
            'datasetId': 'other-dataset',
            'title': 'Other case',
            'input': 'private input',
            'expected': 'private expected',
        },
        headers=other_headers,
    )
    client.post('/api/runs', json={
        'id': 'own-run',
        'dataset_id': 'own-dataset',
        'datasetVersion': 'v1',
        'model': 'own-model',
        'provider': 'ollama',
        'status': 'Completed',
    })
    client.post(
        '/api/runs',
        json={
            'id': 'other-run',
            'dataset_id': 'other-dataset',
            'datasetVersion': 'v1',
            'model': 'private-model',
            'provider': 'ollama',
            'status': 'Completed',
        },
        headers=other_headers,
    )
    with Session(isolated_test_database['engine']) as session:
        session.add_all([
            EvaluationResult(
                id='own-failure',
                run_id='own-run',
                test_case_id='own-case',
                test_case_title='Own case',
                status='Completed',
                passed=False,
                input_snapshot='own input',
            ),
            EvaluationResult(
                id='other-failure',
                run_id='other-run',
                test_case_id='other-case',
                test_case_title='Other case',
                status='Completed',
                passed=False,
                input_snapshot='private input',
            ),
            Dataset(id='unowned-dataset', name='Legacy private dataset'),
        ])
        session.flush()
        session.add(EvaluationRun(
            id='unowned-run',
            dataset_id='unowned-dataset',
            dataset_version='v1',
            model='legacy-model',
        ))
        session.commit()

    assert {row['id'] for row in client.get('/api/datasets').json()} == {'own-dataset'}
    assert {row['id'] for row in client.get('/api/test-cases').json()} == {'own-case'}
    assert {row['id'] for row in client.get('/api/runs').json()} == {'own-run'}
    own_failures = client.get('/api/failures').json()
    assert {row['id'] for row in own_failures} == {'own-failure'}
    assert 'private input' not in str(own_failures)

    assert {row['id'] for row in client.get('/api/datasets', headers=other_headers).json()} == {'other-dataset'}
    assert {row['id'] for row in client.get('/api/test-cases', headers=other_headers).json()} == {'other-case'}
    assert {row['id'] for row in client.get('/api/runs', headers=other_headers).json()} == {'other-run'}
    assert {row['id'] for row in client.get('/api/failures', headers=other_headers).json()} == {'other-failure'}
    assert client.get('/api/runs/unowned-run').status_code == 404


def test_cross_user_reads_writes_deletes_and_parent_attachments_are_hidden(
    client,
    isolated_test_database,
    monkeypatch,
):
    engine = isolated_test_database['engine']
    other_headers = _insert_user(engine, 'another-owner', 'another@example.test')
    client.post('/api/datasets', json={'id': 'owner-dataset', 'name': 'Owner'})
    client.post('/api/test-cases', json={
        'id': 'owner-case', 'datasetId': 'owner-dataset',
        'title': 'Owner case', 'input': 'private input', 'expected': 'expected',
    })
    client.post('/api/rubrics', json={
        'id': 'owner-rubric',
        'name': 'Owner rubric',
        'criteria': [{
            'id': 'owner-criterion',
            'name': 'Criterion',
            'weight': 100,
            'expectedKeywords': ['criterion'],
        }],
    })
    client.post('/api/runs', json={
        'id': 'owner-run',
        'dataset_id': 'owner-dataset',
        'datasetVersion': 'v1',
        'model': 'owner-model',
        'provider': 'ollama',
        'status': 'Completed',
    })
    with Session(engine) as session:
        session.add_all([
            Dataset(id='legacy-unowned', name='Legacy'),
            Rubric(id='legacy-rubric', name='Legacy rubric'),
        ])
        session.add(EvaluationResult(
            id='owner-result',
            run_id='owner-run',
            test_case_id='owner-case',
            status='Completed',
            passed=False,
        ))
        session.add(HumanReview(
            id='owner-review',
            result_id='owner-result',
            reviewer='owner@example.test',
            verdict='fail',
            note='private review',
        ))
        session.commit()

    monkeypatch.setattr(
        main,
        'execute_provider',
        lambda *_args, **_kwargs: pytest.fail('Provider invoked for unauthorized data'),
    )
    foreign_operations = [
        client.delete('/api/datasets/owner-dataset', headers=other_headers),
        client.post('/api/datasets', json={'id': 'owner-dataset', 'name': 'overwrite'}, headers=other_headers),
        client.post('/api/test-cases', json={
            'id': 'owner-case', 'datasetId': 'owner-dataset',
            'title': 'overwrite', 'input': 'x', 'expected': 'y',
        }, headers=other_headers),
        client.delete('/api/test-cases/owner-case', headers=other_headers),
        client.post('/api/rubrics', json={'id': 'owner-rubric', 'name': 'overwrite'}, headers=other_headers),
        client.post('/api/rubrics', json={
            'id': 'new-other-rubric',
            'name': 'New rubric',
            'criteria': [{'id': 'owner-criterion', 'name': 'Hijack', 'weight': 100}],
        }, headers=other_headers),
        client.get('/api/runs/owner-run', headers=other_headers),
        client.post('/api/runs', json={
            'id': 'new-other-run', 'dataset_id': 'owner-dataset',
            'datasetVersion': 'v1', 'model': 'model',
        }, headers=other_headers),
        client.put('/api/failures/owner-result', json={
            'id': 'owner-result', 'testCase': 'Case', 'dataset': 'Dataset',
            'model': 'model', 'category': 'General', 'reviewed': True,
            'humanJudgment': 'pass', 'note': 'hijack',
        }, headers=other_headers),
        client.post('/api/evaluate', json={'datasetId': 'owner-dataset'}, headers=other_headers),
        client.post('/api/evaluate', json={
            'datasetId': 'owner-dataset',
            'evaluationMethod': 'rubric',
            'rubric': 'owner-rubric',
        }, headers=other_headers),
    ]
    assert [response.status_code for response in foreign_operations] == [404] * len(foreign_operations)

    assert client.delete('/api/datasets/legacy-unowned', headers=other_headers).status_code == 404
    assert client.post('/api/rubrics', json={
        'id': 'legacy-rubric', 'name': 'Overwrite legacy',
    }, headers=other_headers).status_code == 404
    with Session(engine) as session:
        assert session.get(Dataset, 'owner-dataset').user_id == 'test-authenticated-user'
        assert session.get(CaseModel, 'owner-case').input == 'private input'
        assert session.get(RubricCriterion, 'owner-criterion').name == 'Criterion'
        assert session.get(HumanReview, 'owner-review').note == 'private review'


def test_unowned_children_and_failure_reviews_are_not_exposed(client, isolated_test_database):
    engine = isolated_test_database['engine']
    with Session(engine) as session:
        session.add(Dataset(id='unowned-parent', name='Legacy'))
        session.flush()
        session.add(CaseModel(
            id='unowned-case',
            dataset_id='unowned-parent',
            title='Legacy case',
            input='legacy secret',
            expected='legacy expected',
        ))
        session.add(Rubric(id='unowned-parent-rubric', name='Legacy rubric'))
        session.flush()
        session.add(EvaluationRun(
            id='unowned-parent-run',
            dataset_id='unowned-parent',
            dataset_version='v1',
            model='legacy-model',
        ))
        session.flush()
        session.add(EvaluationResult(
            id='unowned-parent-result',
            run_id='unowned-parent-run',
            test_case_id='unowned-case',
            input_snapshot='legacy secret',
        ))
        session.commit()

    assert client.get('/api/test-cases').json() == []
    assert client.get('/api/runs').json() == []
    assert client.get('/api/runs/unowned-parent-run').status_code == 404
    assert client.delete('/api/test-cases/unowned-case').status_code == 404
    assert client.put('/api/failures/unowned-parent-result', json={
        'id': 'unowned-parent-result',
        'testCase': 'Legacy',
        'dataset': 'Legacy',
        'model': 'model',
        'category': 'General',
        'reviewed': True,
        'humanJudgment': 'fail',
    }).status_code == 404


def test_registered_users_are_isolated_through_dataset_rubric_and_evaluation_routes(
    unauthenticated_client,
    isolated_test_database,
    monkeypatch,
):
    password = 'correct horse battery staple'
    registrations = [
        unauthenticated_client.post('/api/auth/register', json={
            'email': f'{name}@example.com',
            'password': password,
        })
        for name in ('owner', 'other')
    ]
    assert [response.status_code for response in registrations] == [201, 201]
    owner_headers, other_headers = [
        {'Authorization': f'Bearer {response.json()["access_token"]}'}
        for response in registrations
    ]

    dataset_response = unauthenticated_client.post('/api/datasets', json={
        'id': 'integration-private-dataset',
        'name': 'Private integration dataset',
        'user_id': registrations[1].json()['user']['id'],
    }, headers=owner_headers)
    assert dataset_response.status_code == 200
    case_response = unauthenticated_client.post('/api/test-cases', json={
        'id': 'integration-private-case',
        'datasetId': 'integration-private-dataset',
        'title': 'Private evaluation case',
        'input': 'private prompt',
        'expected': 'expected answer',
    }, headers=owner_headers)
    assert case_response.status_code == 200
    rubric_response = unauthenticated_client.post('/api/rubrics', json={
        'id': 'integration-private-rubric',
        'name': 'Private rubric',
        'user_id': registrations[1].json()['user']['id'],
        'criteria': [{
            'id': 'integration-private-criterion',
            'name': 'Contains required term',
            'weight': 100,
            'expectedKeywords': ['private'],
        }],
    }, headers=owner_headers)
    assert rubric_response.status_code == 200

    class SuccessfulProvider:
        name = 'ollama'
        model = 'integration-model'

        def check_model(self):
            return None

        def generate(self, _prompt, _temperature):
            return GeneratedResponse('private actual response', 10, 2, 1)

        def close(self):
            return None

    monkeypatch.setattr(main, 'create_provider', lambda *_args, **_kwargs: SuccessfulProvider())
    evaluation_response = unauthenticated_client.post('/api/evaluate', json={
        'datasetId': 'integration-private-dataset',
        'model': 'integration-model',
        'user_id': registrations[1].json()['user']['id'],
    }, headers=owner_headers)
    assert evaluation_response.status_code == 200
    run_id = evaluation_response.json()['run']['id']
    result_id = evaluation_response.json()['results'][0]['id']
    assert evaluation_response.json()['results'][0]['actual'] == 'private actual response'

    session_factory = sessionmaker(bind=isolated_test_database['engine'])
    with session_factory() as session:
        assert session.get(Dataset, 'integration-private-dataset').user_id == registrations[0].json()['user']['id']
        assert session.get(Rubric, 'integration-private-rubric').user_id == registrations[0].json()['user']['id']
        assert session.get(EvaluationRun, run_id).user_id == registrations[0].json()['user']['id']

    assert {row['id'] for row in unauthenticated_client.get('/api/datasets', headers=owner_headers).json()} == {
        'integration-private-dataset',
    }
    assert {row['id'] for row in unauthenticated_client.get('/api/rubrics', headers=owner_headers).json()} == {
        'integration-private-rubric',
    }
    assert {row['id'] for row in unauthenticated_client.get('/api/runs', headers=owner_headers).json()} == {run_id}
    owner_run_details = unauthenticated_client.get(f'/api/runs/{run_id}', headers=owner_headers)
    assert owner_run_details.status_code == 200
    assert owner_run_details.json()['results'][0]['input'] == 'private prompt'
    owner_failures = unauthenticated_client.get('/api/failures', headers=owner_headers).json()
    assert {row['id'] for row in owner_failures} == {result_id}

    assert unauthenticated_client.get('/api/datasets', headers=other_headers).json() == []
    assert unauthenticated_client.get('/api/test-cases', headers=other_headers).json() == []
    assert unauthenticated_client.get('/api/rubrics', headers=other_headers).json() == []
    assert unauthenticated_client.get('/api/runs', headers=other_headers).json() == []
    assert unauthenticated_client.get('/api/failures', headers=other_headers).json() == []
    assert unauthenticated_client.get(f'/api/runs/{run_id}', headers=other_headers).status_code == 404
    assert unauthenticated_client.post('/api/test-cases', json={
        'id': 'foreign-child-case',
        'datasetId': 'integration-private-dataset',
        'title': 'Foreign child',
        'input': 'attempt',
        'expected': 'attempt',
    }, headers=other_headers).status_code == 404
    assert unauthenticated_client.post('/api/runs', json={
        'id': 'foreign-run',
        'dataset_id': 'integration-private-dataset',
        'datasetVersion': 'v1',
        'model': 'integration-model',
    }, headers=other_headers).status_code == 404
    assert unauthenticated_client.post('/api/evaluate', json={
        'datasetId': 'integration-private-dataset',
        'model': 'integration-model',
    }, headers=other_headers).status_code == 404
    assert unauthenticated_client.put(f'/api/failures/{result_id}', json={
        'id': result_id,
        'testCase': 'Private evaluation case',
        'dataset': 'Private integration dataset',
        'model': 'integration-model',
        'category': 'General',
        'reviewed': True,
        'humanJudgment': 'fail',
        'note': 'foreign review',
    }, headers=other_headers).status_code == 404

    with session_factory() as session:
        assert session.get(EvaluationResult, result_id).input_snapshot == 'private prompt'
        assert session.scalar(
            select(HumanReview).where(HumanReview.result_id == result_id)
        ) is None

    owner_review = unauthenticated_client.put(f'/api/failures/{result_id}', json={
        'id': result_id,
        'testCase': 'Private evaluation case',
        'dataset': 'Private integration dataset',
        'model': 'integration-model',
        'category': 'General',
        'reviewed': True,
        'humanJudgment': 'fail',
        'note': 'owner review',
    }, headers=owner_headers)
    assert owner_review.status_code == 200
    assert owner_review.json()[0]['note'] == 'owner review'
