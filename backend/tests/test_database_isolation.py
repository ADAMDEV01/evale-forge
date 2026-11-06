from datetime import datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from backend.app.models.models import DatasetVersion


def test_isolated_sqlite_database_enforces_foreign_keys(isolated_test_database):
    test_engine = isolated_test_database['engine']

    with test_engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1

    with pytest.raises(IntegrityError):
        with test_engine.begin() as connection:
            connection.execute(insert(DatasetVersion).values(
                id='orphan-version',
                dataset_id='missing-dataset',
                version='v1',
                created_at=datetime.now(),
                case_count=0,
            ))


def test_application_lifespan_never_connects_to_global_database(client, isolated_test_database):
    assert isolated_test_database['application_connect_attempts'] == []
    assert isolated_test_database['test_connect_count']
