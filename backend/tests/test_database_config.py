from pathlib import Path, PureWindowsPath
import sqlite3
from urllib.parse import quote

import pytest
from sqlalchemy import insert
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from backend.app.db.database import (
    Base,
    _create_engine,
    _engine_connect_args,
    _normalize_database_url,
    _sqlite_url_without_create,
)
from backend.app.db.database_config import DEFAULT_DATABASE_URL, resolve_database_url
from backend.app.models.models import DatasetVersion


@pytest.fixture
def application_sqlite_engine(tmp_path: Path):
    database_path = tmp_path / 'application-test.db'
    sqlite3.connect(database_path).close()
    test_engine = _create_engine(
        str(URL.create('sqlite', database=str(database_path)))
    )
    Base.metadata.create_all(bind=test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def test_sqlite_engine_configuration_preserves_thread_option():
    assert _engine_connect_args('sqlite:///./evalforge.db') == {'check_same_thread': False}


def test_engine_enables_pre_ping_for_pooled_connections(tmp_path):
    test_engine = _create_engine(URL.create('sqlite', database=str(tmp_path / 'pool.db')))
    try:
        assert test_engine.pool._pre_ping is True
    finally:
        test_engine.dispose()


@pytest.mark.parametrize(
    'filename',
    ['literal%2F.db', 'file with spaces.db', 'hash#name.db', 'query?name.db'],
)
def test_sqlite_uri_encodes_uri_sensitive_filename_characters(tmp_path: Path, filename: str):
    database_path = tmp_path / filename
    normalized = _sqlite_url_without_create(
        URL.create('sqlite', database=str(database_path))
    )

    expected_path = quote(database_path.resolve().as_posix(), safe='/:')
    assert normalized.database == f'file:{expected_path}'
    assert dict(normalized.query) == {'mode': 'rw', 'uri': 'true'}


def test_relative_sqlite_path_is_resolved_before_uri_encoding(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    relative_path = 'relative%2F path#?.db'

    normalized = _sqlite_url_without_create(
        URL.create('sqlite', database=relative_path)
    )

    expected_path = quote((tmp_path / relative_path).resolve().as_posix(), safe='/:')
    assert normalized.database == f'file:{expected_path}'
    assert normalized.database.startswith('file:')
    assert normalized.query['mode'] == 'rw'
    assert normalized.query['uri'] == 'true'


def test_sqlite_uri_preserves_windows_drive_and_absolute_path():
    database_path = r'C:\EvalForge\folder%2F name#?.db'
    normalized = _sqlite_url_without_create(
        URL.create('sqlite', database=database_path)
    )

    expected_path = quote(PureWindowsPath(database_path).as_posix(), safe='/:')
    assert normalized.database == f'file:{expected_path}'
    assert normalized.database.startswith('file:C:/')
    assert '%252F' in normalized.database
    assert '%20' in normalized.database
    assert '%23' in normalized.database
    assert '%3F' in normalized.database
    assert normalized.query['mode'] == 'rw'
    assert normalized.query['uri'] == 'true'


def test_plain_postgresql_url_uses_psycopg_driver():
    normalized = _normalize_database_url('postgresql://db.example/evalforge')

    assert normalized.drivername == 'postgresql+psycopg'


def test_missing_urls_resolve_to_the_shared_sqlite_default():
    application_url = resolve_database_url(environ={})
    alembic_url = resolve_database_url(for_alembic=True, environ={})

    assert application_url == alembic_url
    assert str(application_url) == DEFAULT_DATABASE_URL


def test_production_requires_an_explicit_postgresql_database_url():
    with pytest.raises(RuntimeError, match='DATABASE_URL must be explicitly configured'):
        resolve_database_url(environ={'FASTAPI_ENV': 'production'})

    with pytest.raises(RuntimeError, match='persistent PostgreSQL'):
        resolve_database_url(environ={
            'FASTAPI_ENV': 'production',
            'DATABASE_URL': 'sqlite:///./production.db',
        })


def test_production_postgresql_url_uses_psycopg():
    resolved = resolve_database_url(environ={
        'FASTAPI_ENV': 'production',
        'DATABASE_URL': 'postgresql://db.example/evalforge',
    })

    assert resolved.drivername == 'postgresql+psycopg'


def test_database_url_is_shared_by_application_and_alembic():
    environment = {'DATABASE_URL': 'postgresql://db.example/evalforge'}

    application_url = resolve_database_url(environ=environment)
    alembic_url = resolve_database_url(for_alembic=True, environ=environment)

    assert application_url == alembic_url
    assert application_url.drivername == 'postgresql+psycopg'


def test_alembic_url_overrides_only_the_alembic_target():
    environment = {
        'DATABASE_URL': 'sqlite:///application.db',
        'ALEMBIC_DATABASE_URL': 'postgresql://migration.example/evalforge',
    }

    application_url = resolve_database_url(environ=environment)
    alembic_url = resolve_database_url(for_alembic=True, environ=environment)

    assert application_url.database == 'application.db'
    assert application_url.get_backend_name() == 'sqlite'
    assert alembic_url.drivername == 'postgresql+psycopg'
    assert alembic_url.host == 'migration.example'


def test_alembic_url_override_takes_precedence_when_both_are_set():
    environment = {
        'DATABASE_URL': 'postgresql://application.example/evalforge',
        'ALEMBIC_DATABASE_URL': 'postgresql+psycopg://migration.example/evalforge',
    }

    assert resolve_database_url(environ=environment).host == 'application.example'
    assert resolve_database_url(for_alembic=True, environ=environment).host == 'migration.example'


def test_empty_url_variables_are_treated_as_unset():
    environment = {'DATABASE_URL': '', 'ALEMBIC_DATABASE_URL': '  '}

    assert resolve_database_url(environ=environment) == resolve_database_url(environ={})
    assert resolve_database_url(for_alembic=True, environ=environment) == resolve_database_url(
        for_alembic=True,
        environ={},
    )


def test_application_url_resolution_normalizes_postgresql_for_both_targets():
    environment = {'DATABASE_URL': 'postgresql://db.example/evalforge'}

    assert resolve_database_url(environ=environment).drivername == 'postgresql+psycopg'
    assert resolve_database_url(for_alembic=True, environ=environment).drivername == 'postgresql+psycopg'


def test_postgresql_psycopg_url_remains_unchanged():
    url = 'postgresql+psycopg://db.example/evalforge'

    assert _normalize_database_url(url).render_as_string(hide_password=False) == url


def test_sqlite_url_remains_unchanged():
    url = 'sqlite:///./evalforge.db'

    assert _normalize_database_url(url).render_as_string(hide_password=False) == url


def test_postgresql_url_components_survive_driver_normalization():
    normalized = _normalize_database_url(
        'postgresql://user:p%40ss%3Aword@db.example:5432/evalforge'
        '?sslmode=require&application_name=evalforge'
    )

    assert normalized.drivername == 'postgresql+psycopg'
    assert normalized.username == 'user'
    assert normalized.password == 'p@ss:word'
    assert normalized.host == 'db.example'
    assert normalized.port == 5432
    assert normalized.database == 'evalforge'
    assert dict(normalized.query) == {
        'sslmode': 'require',
        'application_name': 'evalforge',
    }


def test_unsupported_dialect_url_is_not_rewritten():
    url = 'mysql+pymysql://db.example/evalforge'

    assert _normalize_database_url(url).render_as_string(hide_password=False) == url


def test_application_sqlite_engine_enables_foreign_keys(application_sqlite_engine):
    with application_sqlite_engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1


def test_application_sqlite_engine_rejects_invalid_foreign_key(application_sqlite_engine):
    with pytest.raises(IntegrityError):
        with application_sqlite_engine.begin() as connection:
            connection.execute(insert(DatasetVersion).values(
                id='orphan-version',
                dataset_id='missing-dataset',
                version='v1',
            ))


def test_postgresql_engine_configuration_omits_sqlite_connection_options():
    assert _engine_connect_args('postgresql+psycopg://user:password@host:5432/evalforge') == {}
