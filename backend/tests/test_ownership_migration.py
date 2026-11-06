from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import database
from backend.app.db.ownership_adoption import (
    OwnershipAdoptionError,
    adopt_unowned_records,
)
from backend.app.models.models import (
    Dataset,
    DatasetVersion,
    EvaluationResult,
    EvaluationRun,
    HumanReview,
    Rubric,
    RubricCriterion,
    TestCase as CaseModel,
    User,
)
from backend.app.security.auth import hash_password

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTH_REVISION = 'b762c47d8e10'
OWNERSHIP_REVISION = 'ce4d8129ab31'
TEST_ADMIN_ID = 'explicit-test-admin'


def _upgrade_to_auth_revision(database_path: Path, monkeypatch) -> URL:
    database_url = URL.create('sqlite', database=str(database_path.resolve()))
    monkeypatch.setenv(
        'ALEMBIC_DATABASE_URL',
        database_url.render_as_string(hide_password=True),
    )
    command.upgrade(Config(str(PROJECT_ROOT / 'alembic.ini')), AUTH_REVISION)
    return database_url


def _upgrade_to_head(database_url: URL) -> None:
    command.upgrade(Config(str(PROJECT_ROOT / 'alembic.ini')), 'head')


def _add_admin(session: Session, user_id: str = TEST_ADMIN_ID) -> User:
    user = User(
        id=user_id,
        email=f'{user_id}@example.test',
        password_hash=hash_password('disposable test password'),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def test_fresh_migration_adds_nullable_ownership_and_indexes(
    migrated_test_engine,
):
    inspector = inspect(migrated_test_engine)

    for table_name in ('datasets', 'rubrics', 'evaluation_runs'):
        columns = {column['name']: column for column in inspector.get_columns(table_name)}
        assert columns['user_id']['nullable'] is True
        foreign_keys = inspector.get_foreign_keys(table_name)
        assert any(
            foreign_key['constrained_columns'] == ['user_id']
            and foreign_key['referred_table'] == 'users'
            and foreign_key.get('options', {}).get('ondelete') == 'RESTRICT'
            for foreign_key in foreign_keys
        )
        assert any(
            index['column_names'] == ['user_id']
            for index in inspector.get_indexes(table_name)
        )

    test_case_uniques = {
        tuple(constraint['column_names'])
        for constraint in inspector.get_unique_constraints('test_cases')
    }
    assert ('dataset_id', 'title') in test_case_uniques

    with Session(migrated_test_engine) as session:
        _add_admin(session)
        session.commit()
        session.add(Dataset(id='invalid-owner', name='Invalid owner', user_id='missing-user'))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_existing_auth_installation_preserves_rows_as_pending_adoption(
    tmp_path: Path,
    monkeypatch,
):
    database_path = tmp_path / 'existing-auth-installation.db'
    database_url = _upgrade_to_auth_revision(database_path, monkeypatch)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO datasets "
                "(id, name, description, version, cases, created_at, modified_at, color) "
                "VALUES ('legacy-dataset', 'Legacy dataset', '', 'v1', 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'violet')"
            ))
            connection.execute(text(
                "INSERT INTO rubrics "
                "(id, name, description, active, created_at, updated_at) "
                "VALUES ('legacy-rubric', 'Legacy rubric', '', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO evaluation_runs "
                "(id, dataset_id, dataset_version, model, provider, dataset_name, "
                "evaluation_method, rubric_id, rubric_snapshot_json, status, accuracy, "
                "pass_rate, latency, score, passed, failed, total, date, config_json, created_at) "
                "VALUES ('legacy-run', 'legacy-dataset', 'v1', 'legacy-model', 'mock', "
                "'Legacy dataset', 'exact_match', 'legacy-rubric', '{}', 'Completed', "
                "0, 0, 0, 0, 0, 0, 0, '', '{}', CURRENT_TIMESTAMP)"
            ))
    finally:
        engine.dispose()

    _upgrade_to_head(database_url)
    migrated_engine = database._create_engine(database_url)
    try:
        with Session(migrated_engine) as session:
            assert session.get(Dataset, 'legacy-dataset').user_id is None
            assert session.get(Rubric, 'legacy-rubric').user_id is None
            assert session.get(EvaluationRun, 'legacy-run').user_id is None
    finally:
        migrated_engine.dispose()


def test_ownership_migration_aborts_before_ddl_on_orphaned_reference(
    tmp_path: Path,
    monkeypatch,
):
    database_path = tmp_path / 'orphaned-legacy-installation.db'
    database_url = _upgrade_to_auth_revision(database_path, monkeypatch)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO dataset_versions "
                "(id, dataset_id, version, created_at, case_count) "
                "VALUES ('orphan-version', 'missing-dataset', 'v1', CURRENT_TIMESTAMP, 0)"
            ))
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match='dataset_versions.dataset_id'):
        _upgrade_to_head(database_url)

    verify_engine = create_engine(database_url)
    try:
        inspector = inspect(verify_engine)
        assert 'user_id' not in {
            column['name'] for column in inspector.get_columns('datasets')
        }
        with verify_engine.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == AUTH_REVISION
    finally:
        verify_engine.dispose()


def test_adoption_requires_explicit_active_administrator(migrated_test_engine):
    with Session(migrated_test_engine) as session:
        _add_admin(session)
        session.commit()
        with pytest.raises(OwnershipAdoptionError, match='designated administrator user ID'):
            adopt_unowned_records(session, None)
        with pytest.raises(OwnershipAdoptionError, match='must exist and be active'):
            adopt_unowned_records(session, 'not-a-user')
        assert session.get(Dataset, 'any-dataset') is None


def test_adoption_assigns_owner_and_is_idempotent(migrated_test_engine):
    with Session(migrated_test_engine) as session:
        _add_admin(session)
        session.add_all([
            Dataset(id='adopt-dataset', name='Adopt dataset'),
            Rubric(id='adopt-rubric', name='Adopt rubric'),
        ])
        session.flush()
        session.add(DatasetVersion(
            id='adopt-version',
            dataset_id='adopt-dataset',
            version='v1',
        ))
        session.add(CaseModel(
            id='adopt-case',
            dataset_id='adopt-dataset',
            dataset_version_id='adopt-version',
            title='Adopt case',
            input='Input',
            expected='Expected',
        ))
        session.add(RubricCriterion(
            id='adopt-criterion',
            rubric_id='adopt-rubric',
            name='Accuracy',
        ))
        session.add(EvaluationRun(
            id='adopt-run',
            dataset_id='adopt-dataset',
            dataset_version='v1',
            model='test-model',
            rubric_id='adopt-rubric',
        ))
        session.flush()
        session.add(EvaluationResult(
            id='adopt-result',
            run_id='adopt-run',
            test_case_id='adopt-case',
        ))
        session.flush()
        session.add(HumanReview(
            id='adopt-review',
            result_id='adopt-result',
            reviewer='legacy-reviewer',
        ))
        session.commit()

        updates = adopt_unowned_records(session, TEST_ADMIN_ID)
        retry_updates = adopt_unowned_records(session, TEST_ADMIN_ID)

        assert updates == {'datasets': 1, 'rubrics': 1, 'evaluation_runs': 1}
        assert retry_updates == {'datasets': 0, 'rubrics': 0, 'evaluation_runs': 0}
        assert session.get(Dataset, 'adopt-dataset').user_id == TEST_ADMIN_ID
        assert session.get(Rubric, 'adopt-rubric').user_id == TEST_ADMIN_ID
        assert session.get(EvaluationRun, 'adopt-run').user_id == TEST_ADMIN_ID
        assert session.get(CaseModel, 'adopt-case').dataset.user_id == TEST_ADMIN_ID
        assert session.get(DatasetVersion, 'adopt-version').dataset.user_id == TEST_ADMIN_ID
        assert session.get(RubricCriterion, 'adopt-criterion').rubric.user_id == TEST_ADMIN_ID
        assert session.get(EvaluationResult, 'adopt-result').run.user_id == TEST_ADMIN_ID
        assert (
            session.get(EvaluationResult, 'adopt-result')
            .run.user_id == TEST_ADMIN_ID
        )


def test_adoption_rejects_test_case_version_from_another_dataset(migrated_test_engine):
    with Session(migrated_test_engine) as session:
        _add_admin(session)
        session.add_all([
            Dataset(id='dataset-one', name='Dataset one'),
            Dataset(id='dataset-two', name='Dataset two'),
        ])
        session.flush()
        session.add(DatasetVersion(
            id='version-one',
            dataset_id='dataset-one',
            version='v1',
        ))
        session.flush()
        session.add(CaseModel(
            id='inconsistent-case',
            dataset_id='dataset-two',
            dataset_version_id='version-one',
            title='Inconsistent case',
            input='Input',
            expected='Expected',
        ))
        session.commit()

        with pytest.raises(
            OwnershipAdoptionError,
            match='test_cases.dataset_version_id',
        ):
            adopt_unowned_records(session, TEST_ADMIN_ID)

        assert session.get(Dataset, 'dataset-one').user_id is None
        assert session.get(Dataset, 'dataset-two').user_id is None


def test_adoption_refuses_records_already_assigned_to_another_user(migrated_test_engine):
    with Session(migrated_test_engine) as session:
        _add_admin(session)
        other_user = _add_admin(session, 'other-test-user')
        session.add(Dataset(
            id='conflicting-dataset',
            name='Conflicting dataset',
            user_id=other_user.id,
        ))
        session.commit()

        with pytest.raises(OwnershipAdoptionError, match='already belong to another user'):
            adopt_unowned_records(session, TEST_ADMIN_ID)

        assert session.get(Dataset, 'conflicting-dataset').user_id == other_user.id
