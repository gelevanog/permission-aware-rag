"""Writes documents, chunks, embeddings and chunk ACLs; changes permissions; deletes.

Three kinds of change, three costs:

* **content changed** -> re-parse, re-chunk, re-embed that document (the only path that calls the embedder);
* **permissions changed** -> rewrite that document's `chunk_acl` rows in one transaction, no embedding;
* **deleted** -> one DELETE; chunks and ACL rows go with it (ON DELETE CASCADE).

Every change bumps ``acl_epoch``, which is part of every cache key, so no cache can serve an answer computed
under the old permissions or from the deleted text.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from clearance.acl import AclError, DocumentAcl, section_key
from clearance.db.models import Chunk, ChunkAcl, Document
from clearance.db.session import Database
from clearance.embeddings import Embedder
from clearance.ingest.chunking import chunk_document
from clearance.ingest.parsing import ParsedDocument, parse_file
from clearance.logging_config import get_logger

log = get_logger(__name__)

UpsertAction = Literal["created", "content_updated", "acl_updated", "unchanged"]


@dataclass(frozen=True)
class SourceDocument:
    """A document as a connector delivers it: bytes plus the effective ACL from the source system."""

    source: str
    external_id: str
    filename: str
    content: bytes
    acl: DocumentAcl
    path: str = ""
    mime_type: str | None = None
    title: str | None = None
    owner: str | None = None
    source_url: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class UpsertResult:
    action: UpsertAction
    document_id: uuid.UUID
    chunks: int
    embedded: int = 0
    """How many chunks were embedded (0 for permission-only changes)."""


@dataclass(frozen=True)
class AclUpdateResult:
    document_id: uuid.UUID
    chunks_updated: int
    acl_version: int
    elapsed_ms: float


@dataclass
class IndexReport:
    results: list[UpsertResult] = field(default_factory=list)
    deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def count(self, action: UpsertAction) -> int:
        return sum(1 for result in self.results if result.action == action)


def validate_sections(acl: DocumentAcl, parsed: ParsedDocument, *, name: str) -> None:
    """Fail closed: a section override whose heading is not in the document would leave that text unprotected."""
    headings = {section_key(heading) for heading in parsed.headings}
    missing = [rule.heading for rule in acl.sections if rule.key not in headings]
    if missing:
        raise AclError(f"{name}: section override(s) {missing} match no heading in the document")


def bump_epoch(session: Session) -> None:
    session.execute(text("UPDATE system_state SET value = value + 1 WHERE key = 'acl_epoch'"))


class IndexWriter:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder

    # ---- documents -------------------------------------------------------------------------------------
    def upsert(self, doc: SourceDocument) -> UpsertResult:
        parsed = parse_file(doc.content, filename=doc.filename, mime_type=doc.mime_type)
        validate_sections(doc.acl, parsed, name=doc.external_id)
        title = doc.title or parsed.title
        with self.db.owner_session() as session:
            existing = session.scalar(
                select(Document).where(Document.source == doc.source, Document.external_id == doc.external_id)
            )
            if existing is not None and existing.content_hash == doc.content_hash:
                path = doc.path or existing.path  # incremental feeds may not know the folder path
                changed_meta = (existing.title, existing.path, existing.owner) != (title, path, doc.owner)
                existing.title, existing.path, existing.owner = title, path, doc.owner
                if DocumentAcl.from_json(existing.acl) != doc.acl:
                    count = self._write_acl(session, existing, doc.acl)
                    return UpsertResult("acl_updated", existing.id, count)
                if changed_meta:
                    bump_epoch(session)
                return UpsertResult("unchanged", existing.id, len(existing.chunks))

            chunks = chunk_document(parsed)
            vectors = self.embedder.embed_documents([chunk.embedding_text(title) for chunk in chunks]) if chunks else []
            if existing is None:
                document = Document(id=uuid.uuid4(), source=doc.source, external_id=doc.external_id)
                session.add(document)
                action: UpsertAction = "created"
            else:
                document = existing
                session.execute(delete(Chunk).where(Chunk.document_id == document.id))
                action = "content_updated"
            document.title = title
            document.path = doc.path or (existing.path if existing is not None else "")
            document.mime_type = doc.mime_type or "text/markdown"
            document.owner = doc.owner
            document.source_url = doc.source_url
            document.content_hash = doc.content_hash
            document.acl = doc.acl.to_json()
            document.acl_version = (existing.acl_version + 1) if existing is not None else 1
            document.updated_at = datetime.now(UTC)
            session.flush()
            for chunk, vector in zip(chunks, vectors, strict=True):
                rule = doc.acl.for_section(chunk.section_path)
                row = Chunk(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    ordinal=chunk.ordinal,
                    section_path=list(chunk.section_path),
                    text=chunk.text,
                    embedding=vector,
                )
                session.add(row)
                session.flush()
                session.add(
                    ChunkAcl(
                        chunk_id=row.id,
                        document_id=document.id,
                        allow_principals=list(rule.allow),
                        deny_principals=list(rule.deny),
                        acl_version=document.acl_version,
                    )
                )
            bump_epoch(session)
            log.info("index.upsert", action=action, document_id=str(document.id), chunks=len(chunks))
            return UpsertResult(action, document.id, len(chunks), embedded=len(chunks))

    def _write_acl(self, session: Session, document: Document, acl: DocumentAcl) -> int:
        document.acl = acl.to_json()
        document.acl_version += 1
        document.updated_at = datetime.now(UTC)
        rows = session.execute(select(Chunk.id, Chunk.section_path).where(Chunk.document_id == document.id)).all()
        for chunk_id, section_path in rows:
            rule = acl.for_section(tuple(section_path))
            session.execute(
                update(ChunkAcl)
                .where(ChunkAcl.chunk_id == chunk_id)
                .values(
                    allow_principals=list(rule.allow),
                    deny_principals=list(rule.deny),
                    acl_version=document.acl_version,
                    updated_at=datetime.now(UTC),
                )
            )
        bump_epoch(session)
        log.info("index.acl_update", document_id=str(document.id), chunks=len(rows), version=document.acl_version)
        return len(rows)

    # ---- permissions -----------------------------------------------------------------------------------
    def set_acl(self, document_id: uuid.UUID, acl: DocumentAcl) -> AclUpdateResult:
        """Change who may read a document. Takes effect for the next query; nothing is re-embedded."""
        started = time.perf_counter()
        with self.db.owner_session() as session:
            document = session.get(Document, document_id, with_for_update=True)
            if document is None:
                raise KeyError(str(document_id))
            if acl.sections:
                headings = {
                    section_key(h)
                    for (path,) in session.execute(select(Chunk.section_path).where(Chunk.document_id == document_id))
                    for h in path
                }
                missing = [rule.heading for rule in acl.sections if rule.key not in headings]
                if missing:
                    raise AclError(f"section override(s) {missing} match no heading in the document")
            count = self._write_acl(session, document, acl)
            version = document.acl_version
        return AclUpdateResult(document_id, count, version, (time.perf_counter() - started) * 1000)

    def delete(self, document_id: uuid.UUID) -> bool:
        """Remove a document; its chunks and ACL rows disappear from search in the same transaction."""
        with self.db.owner_session() as session:
            deleted = session.execute(delete(Document).where(Document.id == document_id).returning(Document.id)).first()
            if deleted:
                bump_epoch(session)
        return bool(deleted)

    def delete_by_external_id(self, source: str, external_id: str) -> bool:
        with self.db.owner_session() as session:
            document_id = session.scalar(
                select(Document.id).where(Document.source == source, Document.external_id == external_id)
            )
        return self.delete(document_id) if document_id is not None else False

    def external_ids(self, source: str) -> set[str]:
        with self.db.owner_session() as session:
            return set(session.scalars(select(Document.external_id).where(Document.source == source)))

    # ---- batch -----------------------------------------------------------------------------------------
    def sync_full(self, source: str, documents: list[SourceDocument], *, prune: bool = True) -> IndexReport:
        """Upsert every document of a source; with ``prune``, delete the ones the source no longer has."""
        report = IndexReport()
        seen: set[str] = set()
        for doc in documents:
            seen.add(doc.external_id)
            try:
                report.results.append(self.upsert(doc))
            except (AclError, ValueError) as exc:
                report.errors.append(f"{doc.external_id}: {exc}")
                log.warning("index.skip", external_id=doc.external_id, error=str(exc)[:200])
        if prune:
            for external_id in self.external_ids(source) - seen:
                report.deleted += int(self.delete_by_external_id(source, external_id))
        return report
