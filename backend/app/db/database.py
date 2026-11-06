from pathlib import Path, PureWindowsPath
import re
from urllib.parse import quote

from sqlalchemy import create_engine, event, make_url
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.db.database_config import (
    normalize_database_url as _normalize_database_url,
    resolve_database_url,
)


DATABASE_URL = resolve_database_url()


def _engine_connect_args(database_url: str | URL) -> dict[str, bool]:
    if make_url(database_url).get_backend_name() == 'sqlite':
        return {'check_same_thread': False}
    return {}


def _sqlite_url_without_create(database_url: str | URL) -> URL:
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != 'sqlite':
        return parsed_url

    database_path = parsed_url.database
    if not database_path or database_path == ':memory:':
        return parsed_url

    query = dict(parsed_url.query)
    if database_path.startswith('file:'):
        if query.get('mode') == 'memory':
            return parsed_url
        sqlite_database = database_path
    elif re.match(r'^[A-Za-z]:[\\/]', database_path):
        # A drive-qualified Windows path is already absolute. Do not pass it
        # through the host OS Path implementation: on Linux that would prefix
        # the runner's working directory and corrupt the drive path.
        windows_path = PureWindowsPath(database_path)
        sqlite_database = f'file:{quote(windows_path.as_posix(), safe="/:")}'
    else:
        resolved_path = Path(database_path).resolve().as_posix()
        sqlite_database = f'file:{quote(resolved_path, safe="/:")}'

    query.update({'mode': 'rw', 'uri': 'true'})
    return parsed_url.set(database=sqlite_database, query=query)


class Base(DeclarativeBase):
    pass


def _create_engine(database_url: str | URL):
    normalized_url = _normalize_database_url(database_url)
    if normalized_url.get_backend_name() == 'sqlite':
        normalized_url = _sqlite_url_without_create(normalized_url)
    configured_engine = create_engine(
        normalized_url,
        connect_args=_engine_connect_args(database_url),
        pool_pre_ping=True,
    )
    if configured_engine.dialect.name == 'sqlite':
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        event.listen(configured_engine, 'connect', enable_sqlite_foreign_keys)
    return configured_engine


engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
