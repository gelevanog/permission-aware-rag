"""Schema: documents, chunks with embeddings, chunk ACLs (separate table), sync state, audit log.

Revision ID: 0001_schema
Revises:
Create Date: 2026-10-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.Text(), nullable=False, server_default="text/markdown"),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("acl", postgresql.JSONB(), nullable=False),
        sa.Column("acl_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "external_id", name="uq_documents_source_external_id"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_path", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # Approximate nearest-neighbour index. With a selective permission filter, HNSW alone would return fewer than
    # k rows (the filter runs after the index produced ef_search candidates); searches therefore enable pgvector's
    # iterative index scans (hnsw.iterative_scan), so the index keeps walking until k *permitted* rows are found.
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "chunk_acl",
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("allow_principals", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("deny_principals", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("acl_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # GIN indexes make `allow_principals && :principals` (array overlap) an index lookup, not a scan.
    op.execute("CREATE INDEX ix_chunk_acl_allow_gin ON chunk_acl USING gin (allow_principals)")
    op.execute("CREATE INDEX ix_chunk_acl_deny_gin ON chunk_acl USING gin (deny_principals)")
    op.create_index("ix_chunk_acl_document_id", "chunk_acl", ["document_id"])

    op.create_table(
        "system_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute("INSERT INTO system_state (key, value) VALUES ('acl_epoch', 0)")

    op.create_table(
        "sync_state",
        sa.Column("connector", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event", sa.Text(), nullable=False, server_default="ask"),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("principals_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_hash", sa.Text(), nullable=True),
        sa.Column("question_preview", sa.Text(), nullable=True),
        sa.Column("retrieved_document_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("retrieved_chunk_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("cited_document_ids", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("candidates_excluded", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("sync_state")
    op.drop_table("system_state")
    op.drop_table("chunk_acl")
    op.drop_table("chunks")
    op.drop_table("documents")
