"""Property tests (Hypothesis): for random users and random ACLs, what search returns is always a subset of what the
ACL rules allow, and the pre-filter still returns k rows whenever k permitted rows exist."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from clearance.acl import DocumentAcl, SectionRule, can_read
from clearance.db.session import Database
from clearance.embeddings import HashEmbedder
from clearance.index import IndexWriter
from clearance.retrieval.search import Retriever
from tests.conftest import doc

GROUPS = [f"group:g{i}" for i in range(6)]
USERS = [f"user:u{i}@x.test" for i in range(5)]
PRINCIPALS = GROUPS + USERS
WORDS = ["revenue", "salary", "runway", "deploy", "holiday", "contract", "budget", "travel"]

principal_sets = st.lists(st.sampled_from(PRINCIPALS), max_size=4, unique=True)


@given(reader=principal_sets, allow=principal_sets, deny=principal_sets, section_allow=principal_sets)
def test_section_rule_semantics(reader: list[str], allow: list[str], deny: list[str], section_allow: list[str]) -> None:
    sections = [SectionRule("Secret", tuple(sorted(section_allow)))] if section_allow else []
    acl = DocumentAcl.of(allow, deny, sections)
    body = acl.for_section(("Body",)).permits(reader)
    secret = acl.for_section(("Secret", "Sub")).permits(reader)
    assert body == (bool(set(reader) & set(allow)) and not set(reader) & set(deny))
    expected_secret_allow = section_allow if section_allow else allow
    assert secret == (bool(set(reader) & set(expected_secret_allow)) and not set(reader) & set(deny))
    if set(reader) & set(deny):
        assert not body and not secret  # deny always wins
    assert acl.readable_by(reader) == (body or secret)


document_specs = st.lists(
    st.tuples(
        st.lists(st.sampled_from(PRINCIPALS), min_size=0, max_size=3, unique=True),  # allow
        st.lists(st.sampled_from(PRINCIPALS), max_size=2, unique=True),  # deny
        st.lists(st.sampled_from(PRINCIPALS), max_size=2, unique=True),  # section override allow
        st.lists(st.sampled_from(WORDS), min_size=2, max_size=4),  # vocabulary
    ),
    min_size=3,
    max_size=10,
)


@pytest.mark.db
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    specs=document_specs,
    reader=st.lists(st.sampled_from(PRINCIPALS), min_size=1, max_size=4, unique=True),
    query=st.sampled_from(WORDS),
    k=st.integers(min_value=1, max_value=8),
)
def test_retrieved_chunks_are_a_subset_of_allowed_chunks(
    migrated_db: Database,
    specs: list[tuple[list[str], list[str], list[str], list[str]]],
    reader: list[str],
    query: str,
    k: int,
) -> None:
    db = migrated_db
    with db.owner_session() as session:
        session.execute(text("TRUNCATE documents, chunks, chunk_acl CASCADE"))
    embedder = HashEmbedder()
    writer = IndexWriter(db, embedder)
    rules: dict[str, tuple[list[str], list[str]]] = {}
    for index, (allow, deny, section_allow, words) in enumerate(specs):
        sections = {"Secret": section_allow} if section_allow else None
        body = (
            f"Public {' '.join(words)} text {index}.\n\n## Secret\n\nSecret {' '.join(reversed(words))} text {index}."
        )
        writer.upsert(doc(f"d{index}", body, allow=allow, deny=deny, sections=sections))
        rules[f"Public {' '.join(words)} text {index}."] = (allow, deny)
        rules[f"Secret {' '.join(reversed(words))} text {index}."] = (section_allow or allow, deny)

    permitted = [chunk_text for chunk_text, (allow, deny) in rules.items() if can_read(reader, allow, deny)]
    retriever = Retriever(db)
    vector = embedder.embed_query(query)
    for results in (retriever.search(vector, reader, k), retriever.search_rls_only(vector, reader, k)):
        assert {r.text for r in results} <= set(permitted)
        assert len(results) == min(k, len(permitted))  # pre-filtering never under-fills the top-k
    post = retriever.search_postfilter(vector, reader, k)
    assert {r.text for r in post} <= set(permitted) and len(post) <= min(k, len(permitted))
