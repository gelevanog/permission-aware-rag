"""FastAPI application: chat (JSON and SSE), documents, admin (ACLs, upload, audit), evaluation, dev IdP."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import yaml
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from clearance.acl import AclError, DocumentAcl, SectionRule, normalize_principals
from clearance.api.evaluation import load_results
from clearance.audit import AuditRecord
from clearance.auth.tokens import AuthError, Identity
from clearance.config import Settings, get_settings
from clearance.db.models import Chunk, Document
from clearance.index import SourceDocument
from clearance.ingest.parsing import UnsupportedFormatError
from clearance.llm.base import LLMError, PolicyViolationError
from clearance.logging_config import configure_logging, get_logger
from clearance.services import Services, build_services

log = get_logger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# ---- request / response models ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    k: int | None = Field(default=None, ge=1, le=20)


class SectionRuleIn(BaseModel):
    heading: str
    allow: list[str]
    deny: list[str] = []


class AclIn(BaseModel):
    allow: list[str] = []
    deny: list[str] = []
    sections: list[SectionRuleIn] = []

    def to_acl(self) -> DocumentAcl:
        return DocumentAcl.of(
            self.allow,
            self.deny,
            [
                SectionRule(s.heading, normalize_principals(s.allow), normalize_principals(s.deny))
                for s in self.sections
            ],
        )


class TokenRequest(BaseModel):
    email: str


# ---- app factory ------------------------------------------------------------------------------------------
def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or (services.settings if services else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "services", None) is None:
            configure_logging(settings.log_level, settings.log_format)
            app.state.services = build_services(settings)
            if settings.seed_demo:
                report = app.state.services.seed_if_empty()
                if report is not None:
                    log.info("seed.done", documents=len(report.results), errors=len(report.errors))
        yield

    app = FastAPI(
        title="Clearance",
        version="0.1.0",
        description="Permission-aware RAG: answers only from documents each user is allowed to see.",
        lifespan=lifespan,
    )
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def svc(request: Request) -> Services:
        services_: Services | None = request.app.state.services
        if services_ is None:
            raise HTTPException(503, "starting up")
        return services_

    def identity(request: Request, authorization: Annotated[str | None, Header()] = None) -> Identity:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        try:
            return svc(request).verifier.verify(authorization.split(" ", 1)[1].strip())
        except AuthError as exc:
            raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc

    def admin(user: Annotated[Identity, Depends(identity)]) -> Identity:
        if not user.is_admin:
            raise HTTPException(403, "administrators only")
        return user

    Svc = Annotated[Services, Depends(svc)]
    User = Annotated[Identity, Depends(identity)]
    Admin = Annotated[Identity, Depends(admin)]

    # ---- health ---------------------------------------------------------------------------------------
    @app.get("/health")
    def health(services_: Svc) -> dict[str, Any]:
        with services_.db.engine.connect() as connection:
            documents = connection.execute(text("SELECT count(*) FROM documents")).scalar()
        return {
            "status": "ok",
            "documents": documents,
            "model": services_.model.label,
            "model_is_local": services_.model.is_local,
            "local_only": services_.settings.local_only,
            "embedding_model": services_.embedder.name,
            "auth_mode": services_.settings.auth_mode,
        }

    # ---- dev identity provider ------------------------------------------------------------------------
    def dev_idp(services_: Services) -> Any:
        if services_.dev_idp is None:
            raise HTTPException(404, "the dev identity provider is disabled")
        return services_.dev_idp

    @app.get("/dev-idp/.well-known/openid-configuration")
    def dev_discovery(services_: Svc) -> dict[str, Any]:
        result: dict[str, Any] = dev_idp(services_).discovery()
        return result

    @app.get("/dev-idp/jwks.json")
    def dev_jwks(services_: Svc) -> dict[str, Any]:
        result: dict[str, Any] = dev_idp(services_).jwks()
        return result

    @app.get("/dev-idp/users")
    def dev_users(services_: Svc) -> list[dict[str, Any]]:
        idp = dev_idp(services_)
        return [asdict(user) for user in idp.directory.users]

    @app.post("/dev-idp/token")
    def dev_token(body: TokenRequest, services_: Svc) -> dict[str, Any]:
        idp = dev_idp(services_)
        try:
            token = idp.issue(body.email)
        except KeyError as exc:
            raise HTTPException(404, "unknown demo user") from exc
        return {"id_token": token, "token_type": "Bearer", "expires_in": idp.ttl_seconds}

    # ---- me, documents ----------------------------------------------------------------------------------
    @app.get("/api/me")
    def me(user: User) -> dict[str, Any]:
        return asdict(user)

    @app.get("/api/documents")
    def my_documents(user: User, services_: Svc) -> dict[str, Any]:
        docs = services_.assistant.retriever.searchable_documents(user.principals)
        total = services_.assistant.retriever.total_documents()
        return {
            "documents": [asdict(d) for d in docs],
            "excluded": total - len(docs) if services_.settings.trace_show_excluded_total else None,
        }

    @app.get("/api/documents/{document_id}")
    def open_document(document_id: uuid.UUID, user: User, services_: Svc) -> dict[str, Any]:
        """The parts of a document this user may read (row-level security filters the sections)."""
        with services_.db.reader(user.principals) as connection:
            doc = connection.execute(
                text("SELECT id, title, path FROM documents WHERE id = :id"), {"id": document_id}
            ).first()
            if doc is None:
                raise HTTPException(404, "not found")  # same response whether it is missing or not permitted
            rows = connection.execute(
                text("SELECT section_path, text FROM chunks WHERE document_id = :id ORDER BY ordinal"),
                {"id": document_id},
            ).all()
        return {
            "id": str(doc[0]),
            "title": doc[1],
            "path": doc[2],
            "chunks": [{"section": " > ".join(row[0] or []), "text": row[1]} for row in rows],
        }

    # ---- ask ------------------------------------------------------------------------------------------
    @app.post("/api/ask")
    def ask(body: AskRequest, user: User, services_: Svc) -> dict[str, Any]:
        try:
            return services_.assistant.ask(user, body.question, k=body.k).to_dict()
        except PolicyViolationError as exc:
            raise HTTPException(403, str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(502, f"model error: {exc}") from exc

    @app.post("/api/ask/stream")
    def ask_stream(body: AskRequest, user: User, services_: Svc) -> StreamingResponse:
        def events() -> Iterator[str]:
            try:
                for event in services_.assistant.ask_stream(user, body.question, k=body.k):
                    payload: dict[str, Any] = {"type": event["type"]}
                    if event["type"] == "trace":
                        payload["trace"] = asdict(event["trace"])
                    elif event["type"] in {"token", "replace"}:
                        payload["text"] = event["text"]
                    elif event["type"] == "done":
                        payload["answer"] = event["answer"].to_dict()
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except LLMError as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)[:300]})}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        )

    # ---- admin --------------------------------------------------------------------------------------------
    @app.get("/api/admin/documents")
    def admin_documents(_: Admin, services_: Svc) -> list[dict[str, Any]]:
        with services_.db.owner_session() as session:
            counts = dict(
                session.execute(select(Chunk.document_id, func.count()).group_by(Chunk.document_id)).tuples().all()
            )
            headings: dict[uuid.UUID, list[str]] = {}
            for document_id, path in session.execute(select(Chunk.document_id, Chunk.section_path)):
                for heading in path or []:
                    if heading not in headings.setdefault(document_id, []):
                        headings[document_id].append(heading)
            documents = session.scalars(select(Document).order_by(Document.path, Document.title)).all()
            return [
                {
                    "id": str(d.id),
                    "title": d.title,
                    "path": d.path,
                    "source": d.source,
                    "external_id": d.external_id,
                    "acl": d.acl,
                    "acl_version": d.acl_version,
                    "chunks": counts.get(d.id, 0),
                    "headings": headings.get(d.id, []),
                    "updated_at": d.updated_at.isoformat(timespec="seconds"),
                }
                for d in documents
            ]

    @app.get("/api/admin/directory")
    def admin_directory(_: Admin, services_: Svc) -> dict[str, Any]:
        directory = services_.directory
        users = []
        for person in directory.users if directory else ():
            principals, unmapped = services_.mapping.principals_for_claims(person.idp_groups)
            users.append(
                {
                    **asdict(person),
                    "principals": list(normalize_principals([f"user:{person.email}", *principals])),
                    "unmapped_groups": unmapped,
                }
            )
        return {
            "company": directory.company if directory else "",
            "users": users,
            "groups": [asdict(g) for g in directory.groups] if directory else [],
        }

    @app.put("/api/admin/documents/{document_id}/acl")
    def update_acl(document_id: uuid.UUID, body: AclIn, user: Admin, services_: Svc) -> dict[str, Any]:
        try:
            acl = body.to_acl()
            result = services_.writer.set_acl(document_id, acl)
        except AclError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "document not found") from exc
        services_.audit.write(
            AuditRecord(
                actor=user.user_principal,
                principals=user.principals,
                event="acl_update",
                outcome="ok",
                latency_ms=round(result.elapsed_ms),
                details={"document_id": str(document_id), "acl": acl.to_json(), "chunks": result.chunks_updated},
            )
        )
        return {**asdict(result), "document_id": str(result.document_id)}

    @app.delete("/api/admin/documents/{document_id}")
    def delete_document(document_id: uuid.UUID, user: Admin, services_: Svc) -> dict[str, Any]:
        if not services_.writer.delete(document_id):
            raise HTTPException(404, "document not found")
        services_.audit.write(
            AuditRecord(
                actor=user.user_principal,
                principals=user.principals,
                event="delete",
                outcome="ok",
                details={"document_id": str(document_id)},
            )
        )
        return {"deleted": str(document_id)}

    @app.post("/api/admin/documents")
    async def upload_document(
        user: Admin,
        services_: Svc,
        file: Annotated[UploadFile, File()],
        acl: Annotated[str, Form(description="ACL as YAML or JSON: allow, deny, sections")],
        path: Annotated[str, Form()] = "uploads",
    ) -> dict[str, Any]:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file too large (5 MB max)")
        try:
            parsed = yaml.safe_load(acl) or {}
            if not isinstance(parsed, dict):
                raise AclError("the ACL must be a mapping")
            document_acl = DocumentAcl.from_json(parsed)
            if not document_acl.allow and not document_acl.sections:
                raise AclError("the ACL must allow at least one principal")
            filename = file.filename or "upload.md"
            result = services_.writer.upsert(
                SourceDocument(
                    source="upload",
                    external_id=f"{path.strip('/')}/{filename}",
                    filename=filename,
                    content=data,
                    acl=document_acl,
                    path=path.strip("/"),
                    mime_type=file.content_type,
                    owner=user.user_principal,
                )
            )
        except (AclError, UnsupportedFormatError, yaml.YAMLError) as exc:
            raise HTTPException(422, str(exc)) from exc
        services_.audit.write(
            AuditRecord(
                actor=user.user_principal,
                principals=user.principals,
                event="ingest",
                outcome=result.action,
                details={"document_id": str(result.document_id), "chunks": result.chunks},
            )
        )
        return {**asdict(result), "document_id": str(result.document_id)}

    @app.post("/api/admin/resync")
    def resync(user: Admin, services_: Svc) -> dict[str, Any]:
        """Re-read the demo folder: restores the source ACLs (like a connector sync overwriting local edits)."""
        from clearance.connectors.local import iter_folder

        report = services_.writer.sync_full("local", list(iter_folder(services_.settings.corpus_dir)), prune=False)
        services_.audit.write(
            AuditRecord(
                actor=user.user_principal,
                principals=user.principals,
                event="sync",
                outcome="ok",
                details={a: report.count(a) for a in ("created", "content_updated", "acl_updated", "unchanged")},
            )
        )
        return {a: report.count(a) for a in ("created", "content_updated", "acl_updated", "unchanged")} | {
            "errors": report.errors
        }

    @app.get("/api/admin/audit")
    def audit_log(_: Admin, services_: Svc, limit: int = 200) -> list[dict[str, Any]]:
        return services_.audit.recent(min(max(limit, 1), 1000))

    # ---- evaluation results -----------------------------------------------------------------------------
    @app.get("/api/eval")
    def evaluation(_: User, services_: Svc) -> dict[str, Any]:
        return load_results(services_.settings.results_dir)

    return app


def create_default_app() -> FastAPI:
    return create_app()
