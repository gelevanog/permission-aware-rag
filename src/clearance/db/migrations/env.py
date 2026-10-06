"""Alembic environment. The URL comes from the caller (clearance.db.migrate) or CLEARANCE_DATABASE_URL."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from clearance.config import get_settings
from clearance.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return str(config.attributes.get("url") or config.get_main_option("sqlalchemy.url") or get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
