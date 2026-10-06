"""Tables. Embeddings live in `chunks`; who may read a chunk lives in `chunk_acl`, a separate table.

Keeping ACLs out of the embedding rows is what makes permission changes cheap and immediate: revoking access or
moving a document rewrites a few short `chunk_acl` rows in one transaction and never re-embeds anything.
The schema itself (including the row-level security policies) is created by the Alembic migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_documents_source_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text)
    """local | upload | gdrive | sharepoint"""
    external_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, default="")
    mime_type: Mapped[str] = mapped_column(Text, default="text/markdown")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text)
    acl: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """The document's effective ACL (allow, deny, section overrides): the source of truth for `chunk_acl`."""
    acl_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True, order_by="Chunk.ordinal"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChunkAcl(Base):
    __tablename__ = "chunk_acl"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    allow_principals: Mapped[list[str]] = mapped_column(ARRAY(Text))
    deny_principals: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    acl_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class SyncState(Base):
    __tablename__ = "sync_state"

    connector: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    event: Mapped[str] = mapped_column(Text, default="ask")
    """ask | acl_update | delete | ingest | sync"""
    actor: Mapped[str] = mapped_column(Text)
    principals_hash: Mapped[str] = mapped_column(Text, default="")
    question_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_document_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    cited_document_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    candidates_excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
