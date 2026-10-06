"""Permission-aware vector search, plus the two baselines the evaluation compares it with.

Clearance's search (``search``) filters BEFORE ranking: the permission predicate is in the WHERE clause of the
nearest-neighbour query, so the k results are the k most similar chunks *among those the user may read*. The query
also runs as the reader role with the user's principals set, so PostgreSQL row-level security enforces the same
rule a second time, independently of the SQL the application wrote.

Baselines (evaluation only, never used to answer users):

* ``search_unfiltered``: no permission check at all (what a naive RAG does);
* ``search_postfilter``: take the global top-k, then drop what the user may not read (a common retrofit). It does
  not leak, but when forbidden chunks fill the top-k, permitted answers are lost: recall drops.

Ablation: ``search_rls_only`` drops the application's WHERE clause (as if a developer forgot it) and relies on
row-level security alone.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from clearance.acl import can_read
from clearance.db.session import Database

_SELECT = """
SELECT c.id, c.document_id, d.title, d.path, d.source_url, c.section_path, c.text,
       1 - (c.embedding <=> CAST(:q AS vector)) AS score
"""

# The permission predicate uses array overlap (&&) on GIN-indexed principal arrays.
PREFILTER_SQL = f"""{_SELECT}
FROM chunks c
JOIN chunk_acl a ON a.chunk_id = c.id
JOIN documents d ON d.id = c.document_id
WHERE a.allow_principals && CAST(:principals AS text[])
  AND NOT (a.deny_principals && CAST(:principals AS text[]))
ORDER BY c.embedding <=> CAST(:q AS vector)
LIMIT :k
"""

UNFILTERED_SQL = f"""{_SELECT}, a.allow_principals, a.deny_principals
FROM chunks c
JOIN chunk_acl a ON a.chunk_id = c.id
JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> CAST(:q AS vector)
LIMIT :k
"""

# Same query without the application's permission predicate: only row-level security can filter it.
RLS_ONLY_SQL = f"""{_SELECT}
FROM chunks c
JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> CAST(:q AS vector)
LIMIT :k
"""

# Owner-side count for the admin audit log: how many of the k nearest chunks the user's permissions excluded.
# Returns a number only; the excluded rows' text never leaves the database.
EXCLUDED_COUNT_SQL = """
SELECT count(*) FILTER (
    WHERE NOT (t.allow_principals && CAST(:principals AS text[]))
       OR (t.deny_principals && CAST(:principals AS text[]))
)
FROM (
    SELECT a.allow_principals, a.deny_principals
    FROM chunks c JOIN chunk_acl a ON a.chunk_id = c.id
    ORDER BY c.embedding <=> CAST(:q AS vector)
    LIMIT :k
) t
"""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    path: str
    section: str
    text: str
    score: float
    source_url: str | None = None
    section_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentSummary:
    id: str
    title: str
    path: str


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


def _row_to_chunk(row: Sequence[object]) -> RetrievedChunk:
    section_path = row[5] if isinstance(row[5], list) else []
    return RetrievedChunk(
        chunk_id=str(row[0]),
        document_id=str(row[1]),
        title=str(row[2]),
        path=str(row[3] or ""),
        source_url=str(row[4]) if row[4] else None,
        section=" > ".join(str(part) for part in section_path),
        text=str(row[6]),
        score=float(row[7]),  # type: ignore[arg-type]
        section_path=tuple(str(part) for part in section_path),
    )


class Retriever:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- Clearance -------------------------------------------------------------------------------------
    def search(self, vector: Sequence[float], principals: Sequence[str], k: int) -> list[RetrievedChunk]:
        """Pre-filtered nearest neighbours, as the reader role under row-level security."""
        params = {"q": vector_literal(vector), "principals": list(principals), "k": k}
        with self.db.reader(principals) as connection:
            rows = connection.execute(text(PREFILTER_SQL), params).all()
        return [_row_to_chunk(row) for row in rows]

    # ---- baselines and ablation (evaluation only) ------------------------------------------------------
    def search_unfiltered(self, vector: Sequence[float], k: int) -> list[RetrievedChunk]:
        with self.db.engine.connect() as connection:
            rows = connection.execute(text(UNFILTERED_SQL), {"q": vector_literal(vector), "k": k}).all()
        return [_row_to_chunk(row) for row in rows]

    def search_postfilter(self, vector: Sequence[float], principals: Sequence[str], k: int) -> list[RetrievedChunk]:
        with self.db.engine.connect() as connection:
            rows = connection.execute(text(UNFILTERED_SQL), {"q": vector_literal(vector), "k": k}).all()
        return [_row_to_chunk(row) for row in rows if can_read(principals, row[8], row[9])]

    def search_rls_only(self, vector: Sequence[float], principals: Sequence[str], k: int) -> list[RetrievedChunk]:
        with self.db.reader(principals) as connection:
            rows = connection.execute(text(RLS_ONLY_SQL), {"q": vector_literal(vector), "k": k}).all()
        return [_row_to_chunk(row) for row in rows]

    # ---- trace and audit -------------------------------------------------------------------------------
    def excluded_count(self, vector: Sequence[float], principals: Sequence[str], k: int) -> int:
        params = {"q": vector_literal(vector), "principals": list(principals), "k": k}
        with self.db.engine.connect() as connection:
            return int(connection.execute(text(EXCLUDED_COUNT_SQL), params).scalar() or 0)

    def searchable_documents(self, principals: Sequence[str]) -> list[DocumentSummary]:
        """Documents with at least one chunk the principals may read (row-level security does the filtering)."""
        with self.db.reader(principals) as connection:
            return _documents(connection)

    def total_documents(self) -> int:
        with self.db.engine.connect() as connection:
            return int(connection.execute(text("SELECT count(*) FROM documents")).scalar() or 0)

    def chunk_ids_readable(self, principals: Sequence[str], chunk_ids: Sequence[str]) -> set[str]:
        """Which of these chunk ids the principals may read, checked through row-level security."""
        if not chunk_ids:
            return set()
        ids = [uuid.UUID(value) for value in chunk_ids]
        with self.db.reader(principals) as connection:
            rows = connection.execute(text("SELECT id FROM chunks WHERE id = ANY(:ids)"), {"ids": ids}).all()
        return {str(row[0]) for row in rows}


def _documents(connection: Connection) -> list[DocumentSummary]:
    rows = connection.execute(text("SELECT id, title, path FROM documents ORDER BY path, title")).all()
    return [DocumentSummary(str(row[0]), str(row[1]), str(row[2] or "")) for row in rows]


def principals_json(principals: Sequence[str]) -> str:
    return json.dumps(sorted(set(principals)))
