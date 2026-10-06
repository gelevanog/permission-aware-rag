"""Wiring: builds the database, embedder, model, assistant, identity and audit objects from Settings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from clearance.assistant import Assistant
from clearance.audit import AuditLog
from clearance.auth.devidp import DevIdentityProvider, Directory
from clearance.auth.mapping import GroupMapping
from clearance.auth.tokens import KeySource, RemoteJwks, StaticKeys, TokenVerifier, discover_jwks_url
from clearance.config import Settings
from clearance.connectors.local import iter_folder
from clearance.db.session import Database
from clearance.embeddings import Embedder, build_embedder
from clearance.index import IndexReport, IndexWriter
from clearance.llm.base import ChatModel
from clearance.llm.factory import build_chat_model
from clearance.retrieval.cache import PermissionScopedCache


@dataclass
class Services:
    settings: Settings
    db: Database
    embedder: Embedder
    model: ChatModel

    @cached_property
    def directory(self) -> Directory | None:
        path = self.settings.directory_file
        return Directory.load(path) if path.exists() else None

    @cached_property
    def mapping(self) -> GroupMapping:
        return GroupMapping.load(
            self.settings.group_mapping_file, passthrough=self.settings.unmapped_groups == "passthrough"
        )

    @cached_property
    def dev_idp(self) -> DevIdentityProvider | None:
        if not (self.settings.dev_idp_enabled and self.directory is not None):
            return None
        return DevIdentityProvider(
            issuer=self.settings.dev_idp_issuer,
            audience=self.settings.oidc_audience,
            key_file=self.settings.dev_idp_key_file,
            directory=self.directory,
            ttl_seconds=self.settings.token_ttl_seconds,
        )

    @cached_property
    def verifier(self) -> TokenVerifier:
        settings = self.settings
        keys: KeySource
        if settings.auth_mode == "dev":
            if self.dev_idp is None:
                raise RuntimeError(
                    "CLEARANCE_AUTH_MODE=dev needs the dev IdP (CLEARANCE_DEV_IDP_ENABLED and a directory)"
                )
            issuer, keys = self.dev_idp.issuer, StaticKeys(self.dev_idp.jwks())
        else:
            if not settings.oidc_issuer:
                raise RuntimeError("CLEARANCE_AUTH_MODE=oidc needs CLEARANCE_OIDC_ISSUER")
            issuer = settings.oidc_issuer
            keys = RemoteJwks(settings.oidc_jwks_url or discover_jwks_url(issuer))
        return TokenVerifier(
            issuer=issuer,
            audience=settings.oidc_audience,
            keys=keys,
            mapping=self.mapping,
            algorithms=settings.oidc_algorithms,
            groups_claim=settings.groups_claim,
            email_claim=settings.email_claim,
            admin_principals=settings.admin_principals,
        )

    @cached_property
    def audit(self) -> AuditLog:
        return AuditLog(self.db, self.settings.audit_key)

    @cached_property
    def cache(self) -> PermissionScopedCache[Any]:
        return PermissionScopedCache(
            max_entries=self.settings.cache_max_entries,
            ttl_seconds=self.settings.cache_ttl_seconds,
            enabled=self.settings.cache_enabled,
        )

    @cached_property
    def writer(self) -> IndexWriter:
        return IndexWriter(self.db, self.embedder)

    @cached_property
    def assistant(self) -> Assistant:
        return Assistant(
            settings=self.settings,
            db=self.db,
            embedder=self.embedder,
            model=self.model,
            audit=self.audit,
            cache=self.cache,
            company=self.directory.company if self.directory else "the company",
        )

    def seed_if_empty(self) -> IndexReport | None:
        """Index the demo corpus when the database has no documents yet."""
        if self.assistant.retriever.total_documents() > 0 or not self.settings.corpus_dir.exists():
            return None
        return self.writer.sync_full("local", list(iter_folder(self.settings.corpus_dir)))


def build_services(
    settings: Settings, *, embedder: Embedder | None = None, model: ChatModel | None = None, migrate: bool | None = None
) -> Services:
    db = Database(settings.database_url, reader_role=settings.reader_role, iterative_scan=settings.hnsw_iterative_scan)
    if settings.auto_migrate if migrate is None else migrate:
        db.migrate()
    return Services(
        settings=settings,
        db=db,
        embedder=embedder or build_embedder(settings),
        model=model or build_chat_model(settings),
    )
