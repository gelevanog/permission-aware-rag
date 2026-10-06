"""Engine, sessions and the permission-scoped reader transaction."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class Database:
    def __init__(
        self, url: str, *, reader_role: str = "clearance_reader", iterative_scan: str = "strict_order"
    ) -> None:
        if not _ROLE_RE.match(reader_role):
            raise ValueError(f"invalid reader role name: {reader_role!r}")
        self.url = url
        self.reader_role = reader_role
        self.iterative_scan = iterative_scan
        self.engine: Engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        """Run Alembic migrations to head (schema, indexes, reader role, row-level security)."""
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    @contextmanager
    def owner_session(self) -> Iterator[Session]:
        """Owner connection: ingestion, ACL administration, audit. Not subject to row-level security."""
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def reader(self, principals: Iterable[str]) -> Iterator[Connection]:
        """A read-only transaction as the reader role, scoped to ``principals``.

        Row-level security on documents, chunks and chunk_acl shows this connection only what the principals may
        read. Both settings are transaction-local (``SET LOCAL`` / ``set_config(..., true)``), so a pooled
        connection never carries one user's principals into another user's request.
        """
        payload = json.dumps(sorted(set(principals)))
        with self.engine.connect() as connection, connection.begin() as transaction:
            connection.execute(text(f"SET LOCAL ROLE {self.reader_role}"))
            connection.execute(text("SET LOCAL transaction_read_only = on"))
            connection.execute(text("SELECT set_config('clearance.principals', :p, true)"), {"p": payload})
            if self.iterative_scan != "off":
                connection.execute(
                    text("SELECT set_config('hnsw.iterative_scan', :mode, true)"), {"mode": self.iterative_scan}
                )
            try:
                yield connection
            finally:
                transaction.rollback()  # read-only: nothing to commit, and settings die with the transaction

    def acl_epoch(self) -> int:
        """A counter bumped by every permission change or deletion; part of every cache key."""
        with self.engine.connect() as connection:
            value = connection.execute(text("SELECT value FROM system_state WHERE key = 'acl_epoch'")).scalar()
        return int(value or 0)

    def dispose(self) -> None:
        self.engine.dispose()
