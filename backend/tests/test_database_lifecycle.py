from pathlib import Path
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

from backend.app import main
from backend.app.db import database
from backend.app.db.database import Base
from backend.app.db.schema_lifecycle import (
    DatabaseSchemaError,
    DatabaseUnavailableError,
    _compare_check_constraints,
    _extract_sqlite_check_constraints,
    check_schema_compatibility,
    create_readonly_engine,
    verify_database_readiness,
)
from backend.app.db.initial_schema import INITIAL_REVISION, INITIAL_SCHEMA_METADATA


def test_application_startup_does_not_create_tables_or_run_legacy_migration(
    isolated_test_database,
    monkeypatch,
):
    assert not hasattr(main, 'migrate_existing_schema')

    def reject_create_all(*_args, **_kwargs):
        raise AssertionError('Application startup must not create tables.')

    monkeypatch.setattr(Base.metadata, 'create_all', reject_create_all)

    with TestClient(main.app):
        assert inspect(isolated_test_database['engine']).has_table('datasets')


def test_application_startup_rejects_missing_schema(tmp_path: Path, monkeypatch):
    database_path = (tmp_path / 'empty-database.db').resolve()
    sqlite3.connect(database_path).close()
    empty_engine = database._create_engine(
        URL.create('sqlite', database=str(database_path))
    )
    monkeypatch.setattr(main, 'engine', empty_engine)
    try:
        with pytest.raises(DatabaseSchemaError, match='Apply the required Alembic migrations'):
            with TestClient(main.app):
                pass
    finally:
        empty_engine.dispose()


def test_application_startup_does_not_create_missing_sqlite_database(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    database_path = Path('missing-database.db')
    assert not database_path.exists()
    missing_engine = database._create_engine(URL.create('sqlite', database=str(database_path)))
    monkeypatch.setattr(main, 'engine', missing_engine)

    try:
        with pytest.raises(DatabaseUnavailableError, match='configured database is unavailable'):
            with TestClient(main.app):
                pass
        assert not database_path.exists()
    finally:
        missing_engine.dispose()


def test_application_startup_distinguishes_database_connection_failure(monkeypatch):
    class UnavailableEngine:
        def connect(self):
            raise OperationalError('connect', {}, RuntimeError('unavailable'))

    monkeypatch.setattr(main, 'engine', UnavailableEngine())

    with pytest.raises(DatabaseUnavailableError, match='database is unavailable'):
        with TestClient(main.app):
            pass


def test_readiness_succeeds_for_migrated_disposable_database(migrated_test_engine):
    report = verify_database_readiness(migrated_test_engine)

    assert report.status == 'exact_match'
    assert report.alembic_revision_status == 'current'


def test_initial_schema_baseline_matches_alembic_migration(initial_migration_test_engine):
    with initial_migration_test_engine.connect() as connection:
        report = check_schema_compatibility(connection)

    assert report.status == 'exact_match'
    assert not report.differences
    assert report.alembic_revisions == (INITIAL_REVISION,)
    assert set(inspect(initial_migration_test_engine).get_table_names()) >= set(
        INITIAL_SCHEMA_METADATA.tables
    )


def test_initial_compatibility_is_independent_of_future_orm_metadata(initial_migration_test_engine):
    future_table = Table(
        'future_only_model_table',
        Base.metadata,
        Column('id', Integer, primary_key=True),
    )
    try:
        with initial_migration_test_engine.connect() as connection:
            report = check_schema_compatibility(connection)
    finally:
        Base.metadata.remove(future_table)

    assert report.status == 'exact_match'
    assert not report.differences


def test_compatibility_checker_does_not_create_version_tracking(tmp_path: Path):
    database_path = tmp_path / 'unversioned-database.db'
    sqlite3.connect(database_path).close()
    engine = database._create_engine(
        URL.create('sqlite', database=str(database_path))
    )
    try:
        INITIAL_SCHEMA_METADATA.create_all(bind=engine)
        with engine.connect() as connection:
            before_tables = set(inspect(connection).get_table_names())
            report = check_schema_compatibility(connection)
            after_tables = set(inspect(connection).get_table_names())

        assert report.status == 'exact_match'
        assert report.alembic_revision_status == 'missing'
        assert 'alembic_version' not in before_tables
        assert after_tables == before_tables
    finally:
        engine.dispose()


def test_compatibility_checker_opens_existing_sqlite_file_read_only(tmp_path: Path):
    database_path = tmp_path / 'readonly-database.db'
    sqlite3.connect(database_path).close()
    source_engine = database._create_engine(URL.create('sqlite', database=str(database_path)))
    INITIAL_SCHEMA_METADATA.create_all(bind=source_engine)
    source_engine.dispose()

    readonly_engine = create_readonly_engine(
        URL.create('sqlite', database=str(database_path))
    )
    try:
        with readonly_engine.connect() as connection:
            report = check_schema_compatibility(connection)
            with pytest.raises(OperationalError):
                connection.execute(text('CREATE TABLE forbidden_write (id INTEGER)'))

        assert report.status == 'exact_match'
        assert 'forbidden_write' not in inspect(readonly_engine).get_table_names()
    finally:
        readonly_engine.dispose()


def test_compatibility_checker_does_not_create_missing_sqlite_file(tmp_path: Path):
    database_path = tmp_path / 'not-created.db'

    with pytest.raises(FileNotFoundError, match='no file was created'):
        create_readonly_engine(URL.create('sqlite', database=str(database_path)))

    assert not database_path.exists()


def test_empty_alembic_version_does_not_imply_empty_schema(initial_migration_test_engine):
    with initial_migration_test_engine.begin() as connection:
        connection.execute(text('DELETE FROM alembic_version'))
        report = check_schema_compatibility(connection)

    assert report.status == 'exact_match'
    assert report.alembic_revision_status == 'empty'
    assert set(inspect(initial_migration_test_engine).get_table_names()) >= set(
        INITIAL_SCHEMA_METADATA.tables
    )


def test_unknown_alembic_revision_is_reported_without_rewriting_it(migrated_test_engine):
    with migrated_test_engine.begin() as connection:
        connection.execute(text('UPDATE alembic_version SET version_num = :revision'), {
            'revision': 'unknown-revision',
        })
        report = check_schema_compatibility(connection)
        stored_revision = connection.execute(
            text('SELECT version_num FROM alembic_version')
        ).scalar_one()

    assert report.status == 'incompatible'
    assert report.alembic_revision_status == 'unknown_revision'
    assert stored_revision == 'unknown-revision'


def test_readiness_and_compatibility_checks_attempt_no_ddl(migrated_test_engine, monkeypatch):
    ddl_attempts = []
    ddl_pattern = re.compile(
        r'^\s*(?:CREATE|ALTER|DROP|TRUNCATE|REINDEX|VACUUM|ATTACH|DETACH|ANALYZE)\b'
        r'|^\s*PRAGMA\s+[^;=]+\s*=',
        re.IGNORECASE,
    )

    def reject_ddl(_connection, _cursor, statement, _parameters, _context, _executemany):
        if ddl_pattern.match(statement):
            ddl_attempts.append(statement)
            raise AssertionError(f'Schema mutation attempted: {statement}')

    event.listen(migrated_test_engine, 'before_cursor_execute', reject_ddl)
    monkeypatch.setattr(main, 'engine', migrated_test_engine)
    try:
        with TestClient(main.app):
            pass

        with migrated_test_engine.connect() as connection:
            revisions_before = tuple(connection.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalars())
            report = check_schema_compatibility(connection)

        readiness = verify_database_readiness(migrated_test_engine)

        with migrated_test_engine.connect() as connection:
            revisions_after = tuple(connection.execute(
                text('SELECT version_num FROM alembic_version')
            ).scalars())
    finally:
        event.remove(migrated_test_engine, 'before_cursor_execute', reject_ddl)

    assert report.status == 'incompatible'
    assert report.alembic_revision_status == 'known_non_head_revision'
    assert readiness.status == 'exact_match'
    assert ddl_attempts == []
    assert revisions_after == revisions_before == ('d41e0a6b9c12',)


def test_check_constraint_comparison_accepts_matching_constraint(migrated_test_engine):
    expected = Table(
        'check_probe',
        MetaData(),
        Column('value', Integer),
        CheckConstraint('value > 0'),
    )
    with migrated_test_engine.begin() as connection:
        connection.execute(text('CREATE TABLE check_probe (value INTEGER, CHECK (value > 0))'))
        differences = []
        _compare_check_constraints(connection, expected, differences)
        connection.execute(text('DROP TABLE check_probe'))
    assert differences == []


def test_check_constraint_comparison_reports_missing_constraint(migrated_test_engine):
    expected = Table(
        'check_probe',
        MetaData(),
        Column('value', Integer),
        CheckConstraint('value > 0'),
    )
    with migrated_test_engine.begin() as connection:
        connection.execute(text('CREATE TABLE check_probe (value INTEGER)'))
        differences = []
        _compare_check_constraints(connection, expected, differences)
        connection.execute(text('DROP TABLE check_probe'))
    assert differences == ['check_probe: missing CHECK constraint (value > 0)']


def test_check_constraint_comparison_reports_unexpected_constraint(migrated_test_engine):
    expected = Table(
        'check_probe',
        MetaData(),
        Column('value', Integer),
    )
    with migrated_test_engine.begin() as connection:
        connection.execute(text('CREATE TABLE check_probe (value INTEGER, CHECK (value > 0))'))
        differences = []
        _compare_check_constraints(connection, expected, differences)
        connection.execute(text('DROP TABLE check_probe'))
    assert differences == ['check_probe: unexpected CHECK constraint (value > 0)']
    assert differences == ['check_probe: unexpected CHECK constraint (value > 0)']

def test_check_constraint_comparison_preserves_string_literal_case(migrated_test_engine):
    expected = Table(
        'check_probe',
        MetaData(),
        Column('value', Integer),
        CheckConstraint("value = 'A'"),
    )
    with migrated_test_engine.begin() as connection:
        connection.execute(text("CREATE TABLE check_probe (value TEXT, CHECK (value = 'a'))"))
        differences = []
        _compare_check_constraints(connection, expected, differences)
        connection.execute(text('DROP TABLE check_probe'))

    assert differences == [
        "check_probe: missing CHECK constraint (value = 'A')",
        "check_probe: unexpected CHECK constraint (value = 'a')",
    ]


@pytest.mark.parametrize(
    ('create_sql', 'expected'),
    [
        ("CREATE TABLE t (value INTEGER -- CHECK (value < 0)\n)", ()),
        ("CREATE TABLE t (value INTEGER /* CHECK (value < 0) */)", ()),
        ("CREATE TABLE t (value TEXT DEFAULT 'CHECK (x) /* not a comment */')", ()),
        (
            'CREATE TABLE t (value INTEGER, CHECK ((value > 0) AND (value < 10)))',
            ('(value > 0) AND (value < 10)',),
        ),
        (
            "CREATE TABLE t (value TEXT, CHECK (value <> 'x(y) CHECK'))",
            ("value <> 'x(y) CHECK'",),
        ),
        (
            "CREATE TABLE t (value TEXT, CHECK (value <> 'it''s CHECK (ok)'))",
            ("value <> 'it''s CHECK (ok)'",),
        ),
        (
            'CREATE TABLE t (value INTEGER, CHECK (value > 0) /* CHECK (x) */)',
            ('value > 0',),
        ),
    ],
)
def test_sqlite_check_parser_ignores_comments_and_respects_quoted_expressions(
    create_sql: str,
    expected: tuple[str, ...],
):
    assert _extract_sqlite_check_constraints(create_sql) == expected


@pytest.mark.parametrize(
    'create_sql',
    [
        'CREATE TABLE t (value INTEGER, CHECK (value > 0)',
        'CREATE TABLE t (value INTEGER, CHECK ())',
        'CREATE TABLE t (value INTEGER, CHECK value > 0)',
        'CREATE TABLE t (value INTEGER /* unterminated comment',
        "CREATE TABLE t (value TEXT, CHECK (value = 'unterminated))",
    ],
)
def test_sqlite_check_parser_rejects_ambiguous_or_malformed_sql(create_sql: str):
    assert _extract_sqlite_check_constraints(create_sql) is None


def test_check_text_in_comment_cannot_hide_a_missing_constraint(migrated_test_engine):
    expected = Table(
        'check_probe',
        MetaData(),
        Column('value', Integer),
        CheckConstraint('value > 0'),
        CheckConstraint('value > 0'),
    )
    with migrated_test_engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE check_probe (value INTEGER, CHECK (value > 0) '
            '/* CHECK (value > 0) */)'
        ))
        differences = []
        _compare_check_constraints(connection, expected, differences)
        connection.execute(text('DROP TABLE check_probe'))

    assert differences == ['check_probe: missing CHECK constraint (value > 0)']
