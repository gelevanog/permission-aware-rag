"""Audit log: who asked what, what was retrieved, and how much the permissions held back.

Stored per question: the user principal, a keyed hash of the principal set and of the question (so repeated
questions can be correlated without storing them), a short masked preview (emails, numbers and long tokens
replaced), the ids of retrieved and cited documents, and how many of the nearest candidates the user's
permissions excluded. Never stored: the full question, the answer, or anything about the excluded chunks beyond
that count.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from clearance.db.models import AuditEntry
from clearance.db.session import Database
from clearance.retrieval.cache import principals_hash

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"https?://\S+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")
_DIGIT = re.compile(r"\d")


def mask_preview(question: str, *, limit: int = 60) -> str:
    """A short, masked snippet: enough to recognize a question in the log, not to reconstruct sensitive values."""
    text = " ".join(question.split())
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[url]", text)
    text = _LONG_TOKEN.sub("[token]", text)
    text = _DIGIT.sub("#", text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass
class AuditRecord:
    actor: str
    principals: Sequence[str]
    question: str | None = None
    event: str = "ask"
    retrieved_document_ids: Sequence[str] = ()
    retrieved_chunk_ids: Sequence[str] = ()
    cited_document_ids: Sequence[str] = ()
    candidates_excluded: int | None = None
    outcome: str = ""
    model: str | None = None
    cache_hit: bool = False
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    def __init__(self, db: Database, key: str = "") -> None:
        self.db = db
        self._key = (key or secrets.token_hex(32)).encode("utf-8")

    def question_hash(self, question: str) -> str:
        normalized = " ".join(question.lower().split())
        return hmac.new(self._key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def write(self, record: AuditRecord) -> None:
        entry = AuditEntry(
            event=record.event,
            actor=record.actor,
            principals_hash=principals_hash(record.principals) if record.principals else "",
            question_hash=self.question_hash(record.question) if record.question else None,
            question_preview=mask_preview(record.question) if record.question else None,
            retrieved_document_ids=list(dict.fromkeys(record.retrieved_document_ids)),
            retrieved_chunk_ids=list(record.retrieved_chunk_ids),
            cited_document_ids=list(dict.fromkeys(record.cited_document_ids)),
            candidates_excluded=record.candidates_excluded,
            outcome=record.outcome,
            model=record.model,
            cache_hit=record.cache_hit,
            latency_ms=record.latency_ms,
            details=record.details,
        )
        with self.db.owner_session() as session:
            session.add(entry)

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.owner_session() as session:
            rows = session.scalars(select(AuditEntry).order_by(desc(AuditEntry.id)).limit(limit)).all()
            return [_as_dict(row) for row in rows]


def _as_dict(row: AuditEntry) -> dict[str, Any]:
    ts: datetime = row.ts
    return {
        "id": row.id,
        "ts": ts.isoformat(timespec="seconds"),
        "event": row.event,
        "actor": row.actor,
        "principals_hash": row.principals_hash,
        "question_hash": row.question_hash,
        "question_preview": row.question_preview,
        "retrieved_document_ids": row.retrieved_document_ids,
        "retrieved_chunk_ids": row.retrieved_chunk_ids,
        "cited_document_ids": row.cited_document_ids,
        "candidates_excluded": row.candidates_excluded,
        "outcome": row.outcome,
        "model": row.model,
        "cache_hit": row.cache_hit,
        "latency_ms": row.latency_ms,
        "details": row.details,
    }
