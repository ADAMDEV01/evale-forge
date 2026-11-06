from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, make_url, pool
from sqlalchemy.engine import URL

from backend.app.db.database import Base
from backend.app.db.database_config import resolve_database_url
from backend.app.models import models as _models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> URL:
    return resolve_database_url(for_alembic=True)


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = get_database_url()
    configuration = config.get_section(config.config_ini_section).copy()
    configuration['sqlalchemy.url'] = database_url
    connect_args = (
        {'check_same_thread': False}
        if make_url(database_url).get_backend_name() == 'sqlite'
        else {}
    )
    connectable = engine_from_config(
        configuration,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
