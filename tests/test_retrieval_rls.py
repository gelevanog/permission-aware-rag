"""Indexing, the pre-filter query, the baselines, and PostgreSQL row-level security (needs TEST_DATABASE_URL)."""

from __future__ import annotations

import json

import pytest
import sqlalchemy.exc
from sqlalchemy import text

from clearance.acl import AclError, DocumentAcl, SectionRule
from clearance.db.session import Database
from clearance.embeddings import HashEmbedder
from clearance.index import IndexWriter
from clearance.retrieval.search import Retriever
from tests.conftest import doc

pytestmark = pytest.mark.db

FINANCE = ["user:alice@x.test", "group:finance", "group:all"]
ENGINEER = ["user:dan@x.test", "group:engineering", "group:all"]
CONTRACTOR = ["user:bob@x.test", "group:engineering", "group:contractors"]


def _seed(writer: IndexWriter) -> dict[str, str]:
    ids = {}
    ids["handbook"] = str(
        writer.upsert(doc("handbook", "Paid time off is 25 days per year.", allow=["group:all"])).document_id
    )
    ids["budget"] = str(
        writer.upsert(doc("budget", "The engineering budget is 9.4 million.", allow=["group:finance"])).document_id
    )
    ids["ladder"] = str(
        writer.upsert(
            doc(
                "ladder",
                "## Levels\n\nSenior engineers lead projects.\n\n"
                "## Salary bands\n\nSenior engineer salary band 158,000.",
                allow=["group:engineering"],
                deny=["group:contractors"],
                sections={"Salary bands": ["group:hr"]},
            )
        ).document_id
    )
    ids["runbook"] = str(
        writer.upsert(doc("runbook", "Deploy on Tuesday and Thursday.", allow=["group:engineering"])).document_id
    )
    return ids


def _texts(chunks: list) -> str:  # type: ignore[type-arg]
    return " ".join(c.text for c in chunks)


def test_upsert_is_idempotent_and_permission_changes_do_not_reembed(db: Database, embedder: HashEmbedder) -> None:
    calls = {"n": 0}
    original = embedder.embed_documents

    def counting(texts):  # type: ignore[no-untyped-def]
        calls["n"] += len(texts)
        return original(texts)

    embedder.embed_documents = counting  # type: ignore[method-assign]
    writer = IndexWriter(db, embedder)
    first = writer.upsert(doc("d", "## A\n\nalpha\n\n## B\n\nbeta", allow=["group:all"]))
    assert first.action == "created" and first.embedded == 2 and calls["n"] == 2
    assert writer.upsert(doc("d", "## A\n\nalpha\n\n## B\n\nbeta", allow=["group:all"])).action == "unchanged"
    moved = writer.upsert(doc("d", "## A\n\nalpha\n\n## B\n\nbeta", allow=["group:finance"]))
    assert moved.action == "acl_updated" and moved.embedded == 0 and calls["n"] == 2  # no re-embedding
    edited = writer.upsert(doc("d", "## A\n\nalpha two\n\n## B\n\nbeta", allow=["group:finance"]))
    assert edited.action == "content_updated" and calls["n"] == 4


def test_section_override_that_matches_no_heading_fails_closed(writer: IndexWriter) -> None:
    with pytest.raises(AclError, match="match no heading"):
        writer.upsert(doc("d", "## Real heading\n\ntext", allow=["group:all"], sections={"Typo heading": ["group:hr"]}))


def test_prefilter_returns_only_permitted_chunks(db: Database, writer: IndexWriter, embedder: HashEmbedder) -> None:
    _seed(writer)
    retriever = Retriever(db)
    vector = embedder.embed_query("senior engineer salary band budget")
    assert "158,000" not in _texts(retriever.search(vector, ENGINEER, 10))  # section restricted to HR
    assert "9.4 million" not in _texts(retriever.search(vector, ENGINEER, 10))
    assert "9.4 million" in _texts(retriever.search(vector, FINANCE, 10))
    assert "Senior engineers lead" not in _texts(retriever.search(vector, CONTRACTOR, 10))  # deny wins
    hr = ["user:carol@x.test", "group:hr"]
    assert "158,000" in _texts(retriever.search(vector, hr, 10))


def test_baselines_leak_or_lose_results(db: Database, writer: IndexWriter, embedder: HashEmbedder) -> None:
    _seed(writer)
    retriever = Retriever(db)
    vector = embedder.embed_query("engineering budget salary band")
    assert "9.4 million" in _texts(retriever.search_unfiltered(vector, 3))  # no filter: leaks
    post = retriever.search_postfilter(vector, ENGINEER, 3)
    pre = retriever.search(vector, ENGINEER, 3)
    assert "9.4 million" not in _texts(post) and len(post) < len(pre) == 3  # post-filter: no leak, fewer results
    assert retriever.excluded_count(vector, ENGINEER, 3) == 3 - len(post)


def test_prefilter_returns_k_rows_through_the_hnsw_index(
    db: Database, writer: IndexWriter, embedder: HashEmbedder
) -> None:
    """With sequential scans disabled the planner walks the HNSW index; iterative scans keep going until k permitted
    rows are found instead of returning the few permitted rows among the first ef_search candidates."""
    for i in range(60):
        writer.upsert(
            doc(f"secret-{i}", f"Confidential board pack {i} about revenue and runway.", allow=["group:board"])
        )
    for i in range(3):
        writer.upsert(doc(f"public-{i}", f"Public note {i} about revenue.", allow=["group:all"]))
    db.force_index_scan = True
    with db.reader(["group:all"]) as connection:
        plan = "\n".join(
            r[0]
            for r in connection.execute(
                text(
                    "EXPLAIN SELECT id FROM chunks "
                    "ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1) LIMIT 3"
                )
            )
        )
    assert "ix_chunks_embedding_hnsw" in plan
    results = Retriever(db).search(embedder.embed_query("revenue"), ["user:x@x.test", "group:all"], 3)
    assert len(results) == 3 and all("Public note" in r.text for r in results)


def test_rls_without_principals_returns_nothing(db: Database, writer: IndexWriter) -> None:
    _seed(writer)
    with db.engine.connect() as connection, connection.begin():
        connection.execute(text("SET LOCAL ROLE clearance_reader"))  # raw query, principals never set
        assert connection.execute(text("SELECT count(*) FROM chunks")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM chunk_acl")).scalar() == 0
    with db.engine.connect() as connection:  # the owner (ingestion, admin) is not subject to RLS
        assert connection.execute(text("SELECT count(*) FROM chunks")).scalar() > 0


def test_rls_filters_raw_queries_without_any_where_clause(db: Database, writer: IndexWriter) -> None:
    _seed(writer)
    with db.reader(ENGINEER) as connection:
        texts = " ".join(r[0] for r in connection.execute(text("SELECT text FROM chunks")))
        titles = {r[0] for r in connection.execute(text("SELECT title FROM documents"))}
    assert "Paid time off" in texts and "Senior engineers lead" in texts
    assert "9.4 million" not in texts and "158,000" not in texts
    assert titles == {"handbook", "ladder", "runbook"}  # titles of unreadable documents are invisible too


def test_rls_only_ablation_still_filters(db: Database, writer: IndexWriter, embedder: HashEmbedder) -> None:
    _seed(writer)
    results = Retriever(db).search_rls_only(embedder.embed_query("budget salary"), ENGINEER, 10)
    assert results and "9.4 million" not in _texts(results) and "158,000" not in _texts(results)


def test_reader_role_cannot_write(db: Database, writer: IndexWriter) -> None:
    _seed(writer)
    with pytest.raises(sqlalchemy.exc.DBAPIError), db.reader(FINANCE) as connection:
        connection.execute(text("UPDATE chunk_acl SET allow_principals = '{group:everyone}'"))
    with pytest.raises(sqlalchemy.exc.DBAPIError), db.reader(FINANCE) as connection:
        connection.execute(text("SELECT count(*) FROM audit_log"))


def test_principal_settings_are_transaction_local(db: Database, writer: IndexWriter) -> None:
    _seed(writer)
    with db.reader(FINANCE) as connection:
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar() == 2
    # The pooled connection is reused: no role and no principals survive the transaction.
    with db.engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar() != "clearance_reader"
        assert connection.execute(text("SELECT current_setting('clearance.principals', true)")).scalar() in (None, "")


def test_acl_update_and_delete_take_effect_on_the_next_query(
    db: Database, writer: IndexWriter, embedder: HashEmbedder
) -> None:
    ids = _seed(writer)
    retriever = Retriever(db)
    vector = embedder.embed_query("engineering budget 9.4 million")
    epoch = db.acl_epoch()
    import uuid

    writer.set_acl(uuid.UUID(ids["budget"]), DocumentAcl.of(["group:all"]))
    assert db.acl_epoch() == epoch + 1
    assert "9.4 million" in _texts(retriever.search(vector, ENGINEER, 5))
    writer.set_acl(uuid.UUID(ids["budget"]), DocumentAcl.of(["group:all"], ["user:dan@x.test"]))
    assert "9.4 million" not in _texts(retriever.search(vector, ENGINEER, 5))
    assert writer.delete(uuid.UUID(ids["budget"]))
    assert "9.4 million" not in _texts(retriever.search(vector, FINANCE, 5))
    with db.engine.connect() as connection:  # chunks and ACL rows went with the document
        assert (
            connection.execute(
                text("SELECT count(*) FROM chunk_acl WHERE document_id = :d"), {"d": ids["budget"]}
            ).scalar()
            == 0
        )


def test_section_acl_edit_rewrites_only_acl_rows(db: Database, writer: IndexWriter, embedder: HashEmbedder) -> None:
    import uuid

    ids = _seed(writer)
    acl = DocumentAcl.of(
        ["group:engineering"], ["group:contractors"], [SectionRule("Salary bands", ("group:engineering",))]
    )
    result = writer.set_acl(uuid.UUID(ids["ladder"]), acl)
    assert result.chunks_updated == 2
    assert "158,000" in _texts(Retriever(db).search(embedder.embed_query("salary band"), ENGINEER, 5))
    with pytest.raises(AclError):
        writer.set_acl(uuid.UUID(ids["ladder"]), DocumentAcl.of(["group:all"], [], [SectionRule("Nope", ("group:a",))]))


def test_searchable_documents_and_json_principals(db: Database, writer: IndexWriter) -> None:
    _seed(writer)
    titles = {d.title for d in Retriever(db).searchable_documents(CONTRACTOR)}
    assert titles == {"runbook"}
    with db.reader(['user:o"dd@x.test', "group:all"]) as connection:  # principals are passed as JSON, not SQL
        assert (
            json.loads(connection.execute(text("SELECT to_json(clearance_principals())::text")).scalar())[0]
            == "group:all"
        )
