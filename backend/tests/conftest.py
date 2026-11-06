import os
import secrets
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite://'

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from backend.app import main
from backend.app.db import database
from backend.app.db.database import get_db
from backend.app.db.initial_schema import INITIAL_REVISION
from backend.app.models.models import User
from backend.app.security.auth import create_access_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_test_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> URL:
    database_path = (tmp_path / 'backend-test.db').resolve()
    if (
        database_path.parent != tmp_path.resolve()
        or database_path == (PROJECT_ROOT / 'evalforge.db').resolve()
    ):
        raise AssertionError('Test database must never target the application database.')

    database_url = URL.create('sqlite', database=str(database_path))
    monkeypatch.setenv('ALEMBIC_DATABASE_URL', database_url.render_as_string(hide_password=True))
    command.upgrade(Config(str(PROJECT_ROOT / 'alembic.ini')), 'head')
    return database_url


@pytest.fixture
def migrated_test_engine(migrated_test_database_url: URL):
    test_engine = database._create_engine(migrated_test_database_url)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture
def initial_migration_test_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = (tmp_path / 'initial-migration-test.db').resolve()
    if (
        database_path.parent != tmp_path.resolve()
        or database_path == (PROJECT_ROOT / 'evalforge.db').resolve()
    ):
        raise AssertionError('Test database must never target the application database.')

    database_url = URL.create('sqlite', database=str(database_path))
    monkeypatch.setenv('ALEMBIC_DATABASE_URL', database_url.render_as_string(hide_password=True))
    command.upgrade(Config(str(PROJECT_ROOT / 'alembic.ini')), INITIAL_REVISION)
    test_engine = database._create_engine(database_url)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture
def isolated_test_database(migrated_test_engine, monkeypatch: pytest.MonkeyPatch):
    application_engine = database.engine
    application_connect_attempts = []
    test_connect_count = []

    def reject_application_database_connection(*args, **kwargs):
        application_connect_attempts.append(True)
        raise AssertionError('Backend tests must not connect to the application database.')

    monkeypatch.setattr(application_engine, 'connect', reject_application_database_connection)
    event.listen(application_engine, 'do_connect', reject_application_database_connection)

    test_engine = migrated_test_engine

    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()

    def record_test_connection(_connection):
        test_connect_count.append(True)

    event.listen(test_engine, 'connect', enable_foreign_keys)
    event.listen(test_engine, 'engine_connect', record_test_connection)
    test_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, 'engine', test_engine)
    monkeypatch.setattr(database, 'SessionLocal', test_session)
    monkeypatch.setattr(main, 'engine', test_engine)

    try:
        test_connect_count.clear()
        yield {
            'engine': test_engine,
            'application_connect_attempts': application_connect_attempts,
            'test_connect_count': test_connect_count,
        }
    finally:
        event.remove(application_engine, 'do_connect', reject_application_database_connection)


@pytest.fixture
def unauthenticated_client(isolated_test_database, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('JWT_SECRET_KEY', secrets.token_urlsafe(48))
    monkeypatch.setenv('AUTH_COOKIE_SECURE', 'false')
    test_session = sessionmaker(
        bind=isolated_test_database['engine'],
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db():
        with test_session() as session:
            yield session

    previous_overrides = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous_overrides)


@pytest.fixture
def client(unauthenticated_client, isolated_test_database):
    test_session = sessionmaker(bind=isolated_test_database['engine'])
    with test_session() as session:
        user = User(
            id='test-authenticated-user',
            email='test@example.invalid',
            password_hash='test-fixture-hash-not-used-for-login',
            is_active=True,
        )
        session.add(user)
        session.commit()
        access_token = create_access_token(user.id)

    unauthenticated_client.headers.update({
        'Authorization': f'Bearer {access_token}',
    })
    yield unauthenticated_client
