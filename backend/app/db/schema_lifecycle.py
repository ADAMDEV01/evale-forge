from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, Engine, Integer, MetaData, String, Table as SQLTable, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.schema import CheckConstraint, Column, Table
from sqlalchemy.sql.sqltypes import DateTime, Text

from backend.app.db.database_config import normalize_database_url
from backend.app.db.initial_schema import INITIAL_REVISION, INITIAL_SCHEMA_METADATA

ALEMBIC_DIRECTORY = Path(__file__).resolve().parents[2] / 'alembic'


@dataclass(frozen=True)
class SchemaCompatibilityReport:
    status: str
    differences: tuple[str, ...]
    alembic_revision_status: str
    alembic_revisions: tuple[str, ...]


class DatabaseUnavailableError(RuntimeError):
    pass


class DatabaseSchemaError(RuntimeError):
    pass


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory(str(ALEMBIC_DIRECTORY))


def _type_matches(expected, actual, dialect) -> bool:
    expected_affinity = expected._type_affinity
    actual_affinity = actual._type_affinity
    if expected_affinity is not actual_affinity:
        if not (
            dialect.name == 'sqlite'
            and isinstance(expected, Boolean)
            and isinstance(actual, Integer)
        ):
            return False

    if isinstance(expected, Text) != isinstance(actual, Text):
        return False

    expected_length = getattr(expected, 'length', None)
    if expected_length != getattr(actual, 'length', None):
        return False

    expected_precision = getattr(expected, 'precision', None)
    if expected_precision is not None and expected_precision != getattr(actual, 'precision', None):
        return False

    if isinstance(expected, DateTime) and expected.timezone != actual.timezone:
        return False

    return True


def _constraint_columns(constraints: Iterable[dict]) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.get('column_names') or ())
        for constraint in constraints
    }


def _expected_foreign_keys(table: Table) -> set[tuple]:
    expected = set()
    for constraint in table.foreign_key_constraints:
        elements = tuple(constraint.elements)
        expected.add((
            tuple(element.parent.name for element in elements),
            elements[0].column.table.name,
            tuple(element.column.name for element in elements),
            (elements[0].ondelete or '').upper(),
            (elements[0].onupdate or '').upper(),
        ))
    return expected


def _actual_foreign_keys(constraints: Iterable[dict]) -> set[tuple]:
    actual = set()
    for constraint in constraints:
        options = constraint.get('options') or {}
        actual.add((
            tuple(constraint.get('constrained_columns') or ()),
            constraint.get('referred_table'),
            tuple(constraint.get('referred_columns') or ()),
            (options.get('ondelete') or '').upper(),
            (options.get('onupdate') or '').upper(),
        ))
    return actual


def _expected_indexes(table: Table) -> set[tuple]:
    return {
        (index.name, tuple(column.name for column in index.columns), bool(index.unique))
        for index in table.indexes
    }


def _actual_indexes(indexes: Iterable[dict], unique_constraints: set[tuple[str, ...]]) -> set[tuple]:
    actual = set()
    for index in indexes:
        columns = tuple(index.get('column_names') or ())
        if index.get('duplicates_constraint'):
            continue
        if index.get('unique') and columns in unique_constraints:
            continue
        actual.add((index.get('name'), columns, bool(index.get('unique'))))
    return actual


def _normalize_check_expression(expression: str) -> str:
    normalized = expression.strip()
    while normalized.startswith('(') and normalized.endswith(')'):
        depth = 0
        wraps_all = True
        quote = None
        index = 0
        while index < len(normalized):
            character = normalized[index]
            if quote:
                if character == quote:
                    if index + 1 < len(normalized) and normalized[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                index += 1
                continue
            if character in {"'", '"', '`'}:
                quote = character
                index += 1
                continue
            if character == '(':
                depth += 1
            elif character == ')':
                depth -= 1
                if depth == 0 and index != len(normalized) - 1:
                    wraps_all = False
                    break
            index += 1
        if not wraps_all or depth != 0:
            break
        normalized = normalized[1:-1].strip()
    return normalized


def _quoted_sql_end(sql: str, start: int) -> int | None:
    opening = sql[start]
    closing = ']' if opening == '[' else opening
    index = start + 1
    while index < len(sql):
        if sql[index] == closing:
            if index + 1 < len(sql) and sql[index + 1] == closing:
                index += 2
                continue
            return index + 1
        index += 1
    return None


def _remove_sqlite_comments(sql: str) -> str | None:
    output: list[str] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character in {"'", '"', '`', '['}:
            quoted_end = _quoted_sql_end(sql, index)
            if quoted_end is None:
                return None
            output.append(sql[index:quoted_end])
            index = quoted_end
        elif sql.startswith('--', index):
            line_end = sql.find('\n', index + 2)
            if line_end == -1:
                output.append(' ' * (len(sql) - index))
                break
            output.append(' ' * (line_end - index))
            index = line_end
        elif sql.startswith('/*', index):
            comment_end = sql.find('*/', index + 2)
            if comment_end == -1:
                return None
            comment = sql[index:comment_end + 2]
            output.append(''.join('\n' if char == '\n' else ' ' for char in comment))
            index = comment_end + 2
        else:
            output.append(character)
            index += 1
    return ''.join(output)


def _extract_sqlite_check_constraints(create_sql: str) -> tuple[str, ...] | None:
    sql = _remove_sqlite_comments(create_sql)
    if sql is None:
        return None

    parenthesis_depth = 0
    index = 0
    while index < len(sql):
        character = sql[index]
        if character in {"'", '"', '`', '['}:
            quoted_end = _quoted_sql_end(sql, index)
            if quoted_end is None:
                return None
            index = quoted_end
            continue
        if character == '(':
            parenthesis_depth += 1
        elif character == ')':
            parenthesis_depth -= 1
            if parenthesis_depth < 0:
                return None
        index += 1
    if parenthesis_depth:
        return None

    checks: list[str] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character in {"'", '"', '`', '['}:
            quoted_end = _quoted_sql_end(sql, index)
            if quoted_end is None:
                return None
            index = quoted_end
            continue

        if not (character.isalpha() or character == '_'):
            index += 1
            continue

        token_start = index
        index += 1
        while index < len(sql) and (sql[index].isalnum() or sql[index] in {'_', '$'}):
            index += 1
        if sql[token_start:index].upper() != 'CHECK':
            continue

        opening = index
        while opening < len(sql) and sql[opening].isspace():
            opening += 1
        if opening >= len(sql) or sql[opening] != '(':
            return None

        depth = 1
        expression_start = opening + 1
        index = expression_start
        while index < len(sql):
            character = sql[index]
            if character in {"'", '"', '`', '['}:
                quoted_end = _quoted_sql_end(sql, index)
                if quoted_end is None:
                    return None
                index = quoted_end
                continue
            if character == '(':
                depth += 1
            elif character == ')':
                depth -= 1
                if depth == 0:
                    expression = sql[expression_start:index].strip()
                    if not expression:
                        return None
                    checks.append(expression)
                    index += 1
                    break
            index += 1
        else:
            return None

    return tuple(checks)


def _compare_check_constraints(
    connection: Connection,
    expected: Table,
    differences: list[str],
) -> bool:
    table_name = expected.name
    expected_checks = Counter(
        _normalize_check_expression(str(constraint.sqltext))
        for constraint in expected.constraints
        if isinstance(constraint, CheckConstraint)
    )
    if connection.dialect.name == 'sqlite':
        create_sql = connection.execute(
            text('SELECT sql FROM sqlite_master WHERE type = :type AND name = :name'),
            {'type': 'table', 'name': table_name},
        ).scalar_one_or_none()
        if not isinstance(create_sql, str):
            differences.append(f'{table_name}: CHECK constraints could not be reliably inspected')
            return False
        parsed_checks = _extract_sqlite_check_constraints(create_sql)
        if parsed_checks is None:
            differences.append(
                f'{table_name}: CHECK constraints could not be reliably interpreted'
            )
            return False
        actual_checks = Counter(
            _normalize_check_expression(expression)
            for expression in parsed_checks
        )
    else:
        try:
            actual_constraints = inspect(connection).get_check_constraints(table_name)
        except (NotImplementedError, SQLAlchemyError):
            differences.append(f'{table_name}: CHECK constraints could not be reliably inspected')
            return False

        actual_checks: Counter[str] = Counter()
        for constraint in actual_constraints:
            expression = constraint.get('sqltext')
            if not isinstance(expression, str) or not expression.strip():
                differences.append(
                    f'{table_name}: CHECK constraint could not be reliably interpreted'
                )
                return False
            actual_checks[_normalize_check_expression(expression)] += 1

    missing = expected_checks - actual_checks
    unexpected = actual_checks - expected_checks
    for expression, count in sorted(missing.items()):
        differences.append(
            f'{table_name}: missing CHECK constraint ({expression})' +
            (f' x{count}' if count > 1 else '')
        )
    for expression, count in sorted(unexpected.items()):
        differences.append(
            f'{table_name}: unexpected CHECK constraint ({expression})' +
            (f' x{count}' if count > 1 else '')
        )
    return True


def _compare_table(connection: Connection, expected: Table, differences: list[str]) -> None:
    inspector = inspect(connection)
    table_name = expected.name
    actual_columns = {column['name']: column for column in inspector.get_columns(table_name)}
    expected_columns = {column.name: column for column in expected.columns}

    for name in sorted(expected_columns.keys() - actual_columns.keys()):
        differences.append(f'{table_name}: missing column {name}')
    for name in sorted(actual_columns.keys() - expected_columns.keys()):
        differences.append(f'{table_name}: unexpected column {name}')

    for name in sorted(expected_columns.keys() & actual_columns.keys()):
        expected_column: Column = expected_columns[name]
        actual_column = actual_columns[name]
        if not _type_matches(expected_column.type, actual_column['type'], connection.dialect):
            differences.append(
                f'{table_name}.{name}: type mismatch '
                f'(expected {expected_column.type}, found {actual_column["type"]})'
            )
        if expected_column.nullable != actual_column['nullable']:
            differences.append(
                f'{table_name}.{name}: nullability mismatch '
                f'(expected nullable={expected_column.nullable})'
            )
        expected_default = expected_column.server_default
        actual_default = actual_column.get('default')
        if (expected_default is None) != (actual_default is None):
            differences.append(f'{table_name}.{name}: server-default mismatch')
        elif expected_default is not None:
            expected_value = str(expected_default.arg).strip().lower()
            actual_value = str(actual_default).strip().lower()
            if expected_value != actual_value:
                differences.append(f'{table_name}.{name}: server-default mismatch')

    expected_pk = tuple(column.name for column in expected.primary_key.columns)
    actual_pk = tuple((inspector.get_pk_constraint(table_name).get('constrained_columns') or ()))
    if expected_pk != actual_pk:
        differences.append(f'{table_name}: primary-key mismatch')

    expected_fks = _expected_foreign_keys(expected)
    actual_fks = _actual_foreign_keys(inspector.get_foreign_keys(table_name))
    if expected_fks != actual_fks:
        differences.append(f'{table_name}: foreign-key mismatch')

    expected_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in expected.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    actual_unique = _constraint_columns(inspector.get_unique_constraints(table_name))
    if expected_unique != actual_unique:
        differences.append(f'{table_name}: unique-constraint mismatch')

    expected_indexes = _expected_indexes(expected)
    actual_indexes = _actual_indexes(inspector.get_indexes(table_name), expected_unique)
    if expected_indexes != actual_indexes:
        differences.append(f'{table_name}: index mismatch')

    _compare_check_constraints(connection, expected, differences)


def _check_schema_against(
    connection: Connection,
    expected_metadata: MetaData,
    expected_revisions: set[str],
    optional_tables: dict[str, Table] | None = None,
) -> SchemaCompatibilityReport:
    inspector = inspect(connection)
    actual_tables = set(inspector.get_table_names())
    optional_tables = optional_tables or {}
    expected_table_definitions = dict(expected_metadata.tables)
    expected_table_definitions.update(optional_tables)
    expected_tables = set(expected_table_definitions)
    optional_table_names = set(optional_tables)
    differences: list[str] = []

    for table_name in sorted(expected_tables - actual_tables - optional_table_names):
        differences.append(f'missing table {table_name}')
    for table_name in sorted(actual_tables - expected_tables - {'alembic_version'}):
        differences.append(f'unexpected table {table_name}')

    for table_name in sorted(expected_tables & actual_tables):
        _compare_table(connection, expected_table_definitions[table_name], differences)

    revision_status, revisions, revision_difference = _inspect_revision_state(
        connection,
        inspector,
        expected_revisions,
    )
    if revision_difference:
        differences.append(revision_difference)

    return SchemaCompatibilityReport(
        status='exact_match' if not differences else 'incompatible',
        differences=tuple(differences),
        alembic_revision_status=revision_status,
        alembic_revisions=revisions,
    )


def check_schema_compatibility(connection: Connection) -> SchemaCompatibilityReport:
    """Compare a connected database with the immutable initial migration baseline."""
    return _check_schema_against(
        connection,
        INITIAL_SCHEMA_METADATA,
        {INITIAL_REVISION},
    )


def _inspect_revision_state(
    connection: Connection,
    inspector,
    expected_revisions: set[str],
) -> tuple[str, tuple[str, ...], str | None]:
    if 'alembic_version' not in inspector.get_table_names():
        return 'missing', (), None

    columns = {column['name'] for column in inspector.get_columns('alembic_version')}
    if 'version_num' not in columns:
        return 'invalid_version_table', (), 'alembic_version is missing its version_num column'

    revisions = tuple(sorted(connection.execute(text('SELECT version_num FROM alembic_version')).scalars()))
    if not revisions:
        return 'empty', (), None

    script = _script_directory()
    known_revisions = {revision.revision for revision in script.walk_revisions()}
    unknown = tuple(revision for revision in revisions if revision not in known_revisions)
    if unknown:
        return (
            'unknown_revision',
            revisions,
            f'Unknown Alembic revision(s): {", ".join(unknown)}; manual investigation is required',
        )

    if len(revisions) != 1 or revisions[0] not in expected_revisions:
        return (
            'known_non_head_revision',
            revisions,
            'Alembic revision tracking is not at the current migration head',
        )

    return 'current', revisions, None


def verify_database_readiness(engine: Engine) -> SchemaCompatibilityReport:
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
            from backend.app.db.database import Base
            from backend.app.models import models as _models

            # The bridge release accepts either side of the additive login
            # rate-limit migration. The old app remains healthy before migration;
            # after migration it ignores no unknown schema: this one optional
            # table is checked against its exact expected definition.
            optional_metadata = MetaData()
            optional_login_attempts = SQLTable(
                'auth_login_attempts',
                optional_metadata,
                Column('key_hash', String(length=64), primary_key=True, nullable=False),
                Column('window_started_at', DateTime(), nullable=False),
                Column('attempts', Integer(), nullable=False),
                Column('updated_at', DateTime(), nullable=False),
            )
            migration_revisions = set(_script_directory().get_heads()) | {'ce4d8129ab31'}
            report = _check_schema_against(
                connection,
                Base.metadata,
                migration_revisions,
                optional_tables={'auth_login_attempts': optional_login_attempts},
            )
    except SQLAlchemyError:
        raise DatabaseUnavailableError(
            'The configured database is unavailable or could not be inspected. '
            'Verify database connectivity and the configured URL.'
        ) from None

    if report.status != 'exact_match' or report.alembic_revision_status != 'current':
        details = '; '.join(report.differences) or (
            f'Alembic revision tracking is {report.alembic_revision_status}'
        )
        raise DatabaseSchemaError(
            f'The database schema is missing or incompatible: {details}. '
            'Apply the required Alembic migrations before starting EvalForge.'
        )
    return report


def create_readonly_engine(database_url: str | URL) -> Engine:
    url = normalize_database_url(database_url)
    if url.get_backend_name() != 'sqlite':
        return create_engine(url, pool_pre_ping=True)

    database_path = url.database
    if not database_path or database_path == ':memory:' or database_path.startswith('file:'):
        raise ValueError('The compatibility checker requires an existing SQLite file database.')

    path = Path(database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise FileNotFoundError('The selected SQLite database file does not exist; no file was created.')

    query = dict(url.query)
    query.update({'mode': 'ro', 'uri': 'true'})
    readonly_url = url.set(database=f'file:{path.resolve().as_posix()}', query=query)
    return create_engine(readonly_url, connect_args={'check_same_thread': False}, pool_pre_ping=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only database schema compatibility report')
    parser.add_argument(
        '--database-url',
        required=True,
        help='Explicitly selected database URL; SQLite files are opened read-only',
    )
    arguments = parser.parse_args()

    try:
        engine = create_readonly_engine(arguments.database_url)
        try:
            with engine.connect() as connection:
                report = check_schema_compatibility(connection)
        finally:
            engine.dispose()
    except (OSError, ValueError, SQLAlchemyError):
        print('Unable to inspect the selected database; verify the target and its availability.')
        return 2

    print(f'Schema status: {report.status}')
    print(f'Alembic revision status: {report.alembic_revision_status}')
    if report.alembic_revisions:
        print(f'Alembic revisions: {", ".join(report.alembic_revisions)}')
    for difference in report.differences:
        print(f'- {difference}')
    return 0 if report.status == 'exact_match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
