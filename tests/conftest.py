"""Shared fixtures. No API keys and no model downloads: the hashing embedder and the extractive model stand in.

Database tests need PostgreSQL with pgvector at TEST_DATABASE_URL (CI starts a service container). They are skipped
when it is not set, unless REQUIRE_TEST_DB=1 (as in CI), which turns a missing database into a failure.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clearance.acl import DocumentAcl, SectionRule, normalize_principals
from clearance.config import Settings
from clearance.db.session import Database
from clearance.embeddings import HashEmbedder
from clearance.index import IndexWriter, SourceDocument
from clearance.llm.extractive import ExtractiveModel
from clearance.services import Services, build_services

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "company"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    if os.environ.get("REQUIRE_TEST_DB") == "1":
        raise pytest.UsageError("REQUIRE_TEST_DB=1 but TEST_DATABASE_URL is not set")
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set (PostgreSQL with pgvector)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": TEST_DATABASE_URL or "postgresql+psycopg://unused@localhost/unused",
        "embedding_provider": "hash",
        "llm_provider": "extractive",
        "llm_fallback_to_extractive": True,
        "local_only": True,
        "corpus_dir": CORPUS,
        "directory_file": ROOT / "data" / "directory.yaml",
        "group_mapping_file": ROOT / "configs" / "group-mapping.yaml",
        "results_dir": ROOT / "results",
        "llm_ledger": None,
        "min_score": 0.0,
        "seed_demo": False,
        "audit_key": "test-audit-key",
        "cors_origins": ["http://localhost:3000"],
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(dev_idp_key_file=tmp_path / "dev-idp.pem")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[Database]:
    db = Database(TEST_DATABASE_URL)
    db.migrate()
    yield db
    db.dispose()


@pytest.fixture
def db(migrated_db: Database) -> Iterator[Database]:
    with migrated_db.owner_session() as session:
        session.execute(text("TRUNCATE documents, chunks, chunk_acl, audit_log, sync_state CASCADE"))
        session.execute(text("UPDATE system_state SET value = 0 WHERE key = 'acl_epoch'"))
    migrated_db.force_index_scan = False
    yield migrated_db


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder(384)


@pytest.fixture
def writer(db: Database, embedder: HashEmbedder) -> IndexWriter:
    return IndexWriter(db, embedder)


@pytest.fixture
def services(db: Database, settings: Settings, embedder: HashEmbedder) -> Services:
    return build_services(settings, embedder=embedder, model=ExtractiveModel(), migrate=False)


@pytest.fixture
def seeded(services: Services) -> Services:
    """The full demo corpus (60 documents) indexed with the hashing embedder."""
    report = services.seed_if_empty()
    assert report is not None and not report.errors
    return services


def doc(
    external_id: str,
    body: str,
    *,
    allow: list[str],
    deny: list[str] | None = None,
    sections: dict[str, list[str]] | None = None,
    title: str | None = None,
    source: str = "test",
) -> SourceDocument:
    acl = DocumentAcl.of(
        allow,
        deny or [],
        [SectionRule(h, normalize_principals(a)) for h, a in (sections or {}).items()],
    )
    content = (f"# {title or external_id}\n\n{body}").encode()
    return SourceDocument(
        source=source, external_id=external_id, filename=f"{external_id}.md", content=content, acl=acl
    )


def identity_for(services: Services, email: str) -> Any:
    assert services.dev_idp is not None
    return services.verifier.verify(services.dev_idp.issue(email))
