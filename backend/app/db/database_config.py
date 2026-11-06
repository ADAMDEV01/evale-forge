import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f'sqlite:///{(ROOT_DIR / "evalforge.db").as_posix()}'

if os.environ.get('FASTAPI_ENV', 'development').strip().lower() not in {'prod', 'production'}:
    load_dotenv(ROOT_DIR / '.env')


def normalize_database_url(database_url: str | URL) -> URL:
    parsed_url = make_url(database_url)
    if parsed_url.drivername == 'postgresql':
        return parsed_url.set(drivername='postgresql+psycopg')
    return parsed_url


def resolve_database_url(
    *,
    for_alembic: bool = False,
    environ: Mapping[str, str] | None = None,
) -> URL:
    """Resolve the shared application target; ALEMBIC_DATABASE_URL overrides Alembic only."""
    environment = os.environ if environ is None else environ
    production = environment.get('FASTAPI_ENV', '').strip().lower() in {'prod', 'production'}
    configured_database_url = environment.get('DATABASE_URL', '').strip()
    if production and not configured_database_url:
        raise RuntimeError('DATABASE_URL must be explicitly configured in production.')
    database_url = configured_database_url or DEFAULT_DATABASE_URL
    if for_alembic:
        database_url = environment.get('ALEMBIC_DATABASE_URL', '').strip() or database_url
    normalized_url = normalize_database_url(database_url)
    if production and normalized_url.get_backend_name() != 'postgresql':
        raise RuntimeError('Production requires a persistent PostgreSQL DATABASE_URL.')
    return normalized_url
