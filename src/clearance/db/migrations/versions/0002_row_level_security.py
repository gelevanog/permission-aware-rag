"""Row-level security: the second line of defence behind the application's pre-filter.

Every search runs inside a transaction that does ``SET LOCAL ROLE clearance_reader`` and
``set_config('clearance.principals', '<json array>', true)``. The reader role can only SELECT the three content
tables, and the policies below show it only rows whose ACL admits one of the session's principals and denies
none. A query that forgets to set principals sees nothing (fail closed), and a bug that drops the
application's WHERE clause still cannot return a forbidden chunk.

The owner role (migrations, ingestion, ACL administration, audit) is not subject to these policies.

Revision ID: 0002_row_level_security
Revises: 0001_schema
Create Date: 2026-10-06
"""

from __future__ import annotations

import os
import re

from alembic import op

revision = "0002_row_level_security"
down_revision = "0001_schema"
branch_labels = None
depends_on = None


def _reader_role() -> str:
    role = os.environ.get("CLEARANCE_READER_ROLE", "clearance_reader")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"invalid reader role name: {role!r}")
    return role


ALLOWED = (
    "{prefix}allow_principals && clearance_principals() AND NOT ({prefix}deny_principals && clearance_principals())"
)


def upgrade() -> None:
    role = _reader_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    # The application connects as the owner and switches to the reader role per search transaction.
    op.execute(f"GRANT {role} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(f"GRANT SELECT ON documents, chunks, chunk_acl TO {role}")

    # The session's principals, from a transaction-local setting. Unset or empty = no principals = no rows.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION clearance_principals() RETURNS text[]
        LANGUAGE sql STABLE PARALLEL SAFE AS $$
            SELECT COALESCE(
                ARRAY(SELECT jsonb_array_elements_text(
                    NULLIF(current_setting('clearance.principals', true), '')::jsonb
                )),
                ARRAY[]::text[]
            )
        $$
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION clearance_principals() TO {role}")

    for table in ("chunk_acl", "chunks", "documents"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute(f"CREATE POLICY chunk_acl_reader ON chunk_acl FOR SELECT TO {role} USING ({ALLOWED.format(prefix='')})")
    op.execute(
        f"""
        CREATE POLICY chunks_reader ON chunks FOR SELECT TO {role} USING (
            EXISTS (SELECT 1 FROM chunk_acl a WHERE a.chunk_id = chunks.id AND {ALLOWED.format(prefix="a.")})
        )
        """
    )
    # A document row (title, path) is visible only if at least one of its chunks is: titles of documents a user
    # cannot open are never shown, not even in a list.
    op.execute(
        f"""
        CREATE POLICY documents_reader ON documents FOR SELECT TO {role} USING (
            EXISTS (SELECT 1 FROM chunk_acl a WHERE a.document_id = documents.id AND {ALLOWED.format(prefix="a.")})
        )
        """
    )


def downgrade() -> None:
    role = _reader_role()
    for table, policy in (
        ("documents", "documents_reader"),
        ("chunks", "chunks_reader"),
        ("chunk_acl", "chunk_acl_reader"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS clearance_principals()")
    op.execute(f"REVOKE SELECT ON documents, chunks, chunk_acl FROM {role}")
