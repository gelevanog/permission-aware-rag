"""Command line: ingest, sync, ask, acl, users, token, serve, eval."""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from clearance.acl import DocumentAcl, normalize_principals
from clearance.config import LLMProviderKind, Settings
from clearance.logging_config import configure_logging

app = typer.Typer(help="Clearance: permission-aware RAG over company documents.", no_args_is_help=True)
acl_app = typer.Typer(help="Show or change a document's ACL.", no_args_is_help=True)
eval_app = typer.Typer(help="Evaluation runs (results go to results/).", no_args_is_help=True)
app.add_typer(acl_app, name="acl")
app.add_typer(eval_app, name="eval")
console = Console()
err = Console(stderr=True)


def _settings(**overrides: Any) -> Settings:
    settings = Settings()  # read the environment now (not the process-wide cached settings)
    configure_logging(settings.log_level, settings.log_format)
    return settings.model_copy(update={k: v for k, v in overrides.items() if v is not None})


def _services(settings: Settings, **kwargs: Any) -> Any:
    from clearance.services import build_services

    return build_services(settings, **kwargs)


# ---- data ---------------------------------------------------------------------------------------------------
@app.command()
def migrate() -> None:
    """Create or upgrade the schema (tables, indexes, reader role, row-level security)."""
    from clearance.db.session import Database

    settings = _settings()
    Database(settings.database_url, reader_role=settings.reader_role).migrate()
    console.print("[green]migrated[/green]")


@app.command()
def ingest(
    folder: Annotated[Path, typer.Argument(help="Folder with documents and *.acl.yaml sidecars")] = Path(
        "data/company"
    ),
    source: Annotated[str, typer.Option(help="Source name stored with the documents")] = "local",
    prune: Annotated[
        bool, typer.Option(help="Delete documents of this source that are no longer in the folder")
    ] = True,
) -> None:
    """Index a local folder: new and changed files are embedded, ACL-only changes rewrite ACL rows only."""
    from clearance.connectors.local import iter_folder

    services = _services(_settings(), model=_extractive())
    report = services.writer.sync_full(source, list(iter_folder(folder, source=source)), prune=prune)
    counts = {a: report.count(a) for a in ("created", "content_updated", "acl_updated", "unchanged")}
    console.print(counts | {"deleted": report.deleted})
    for error in report.errors:
        err.print(f"[red]skipped[/red] {error}")
    raise typer.Exit(1 if report.errors else 0)


@app.command()
def sync(
    connector: Annotated[str, typer.Argument(help="local | gdrive | sharepoint")],
    full: Annotated[bool, typer.Option(help="Ignore the stored cursor and do a full sync")] = False,
) -> None:
    """Sync documents AND permissions from a connector (incremental after the first run)."""
    settings = _settings()
    services = _services(settings, model=_extractive())
    if connector == "local":
        from clearance.connectors.local import iter_folder

        report = services.writer.sync_full("local", list(iter_folder(settings.corpus_dir)))
    elif connector == "gdrive":
        from clearance.connectors.gdrive import GoogleDriveConnector
        from clearance.connectors.oauth import GoogleServiceAccount
        from clearance.connectors.sync import sync_gdrive

        if not (settings.gdrive_folder_id and settings.gdrive_service_account_file):
            raise typer.BadParameter("set CLEARANCE_GDRIVE_FOLDER_ID and CLEARANCE_GDRIVE_SERVICE_ACCOUNT_FILE")
        google_tokens = GoogleServiceAccount(
            settings.gdrive_service_account_file, subject=settings.gdrive_subject or None
        )
        drive = GoogleDriveConnector(
            tokens=google_tokens, mapping=services.mapping, root_folder_id=settings.gdrive_folder_id
        )
        report = sync_gdrive(services.db, services.writer, drive, full=full)
    elif connector == "sharepoint":
        from clearance.connectors.oauth import MicrosoftClientCredentials
        from clearance.connectors.sharepoint import SharePointConnector
        from clearance.connectors.sync import sync_sharepoint

        if not (settings.sharepoint_tenant_id and settings.sharepoint_client_id and settings.sharepoint_client_secret):
            raise typer.BadParameter("set CLEARANCE_SHAREPOINT_TENANT_ID, _CLIENT_ID and _CLIENT_SECRET")
        tokens = MicrosoftClientCredentials(
            settings.sharepoint_tenant_id, settings.sharepoint_client_id, settings.sharepoint_client_secret
        )
        sharepoint = SharePointConnector(
            tokens=tokens,
            mapping=services.mapping,
            site_id=settings.sharepoint_site_id or None,
            drive_id=settings.sharepoint_drive_id or None,
            organization_domain=settings.sharepoint_organization_domain or None,
        )
        report = sync_sharepoint(services.db, services.writer, sharepoint, full=full)
    else:
        raise typer.BadParameter("connector must be local, gdrive or sharepoint")
    counts = {a: report.count(a) for a in ("created", "content_updated", "acl_updated", "unchanged")}
    console.print(counts | {"deleted": report.deleted, "errors": len(report.errors)})


def _extractive() -> Any:
    from clearance.llm.extractive import ExtractiveModel

    return ExtractiveModel()


# ---- asking -------------------------------------------------------------------------------------------------
@app.command()
def ask(
    question: Annotated[str, typer.Argument()],
    as_user: Annotated[str, typer.Option("--as", help="Demo user email (signed in through the dev IdP)")],
    provider: Annotated[
        str | None, typer.Option(help="LLM provider override (extractive, ollama, openrouter, ...)")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model override")] = None,
    show_trace: Annotated[bool, typer.Option("--trace/--no-trace")] = True,
) -> None:
    """Ask a question as a demo user and print the answer, citations and permission trace."""
    settings = _settings(llm_provider=provider, llm_model=model)
    services = _services(settings)
    if services.dev_idp is None:
        raise typer.BadParameter("the dev IdP is disabled (CLEARANCE_DEV_IDP_ENABLED=false)")
    email = as_user if "@" in as_user else f"{as_user}@{services.dev_idp.directory.domain}"
    identity = services.verifier.verify(services.dev_idp.issue(email))
    answer = services.assistant.ask(identity, question)
    console.print(f"[bold]{identity.name}[/bold] ({', '.join(identity.principals)})\n")
    console.print(answer.text)
    for citation in answer.citations:
        console.print(
            f"  [{citation.number}] {citation.title}" + (f" > {citation.section}" if citation.section else "")
        )
    if show_trace:
        trace = answer.trace
        console.print(
            f"\n[dim]searchable documents: {trace.searchable_documents}"
            + (f", not searchable for you: {trace.excluded_documents}" if trace.excluded_documents is not None else "")
            + f" | model: {trace.model}"
            + (f" | fallback: {trace.fallback}" if trace.fallback else "")
            + " | "
            + ", ".join(f"{k} {v:.0f} ms" for k, v in trace.timings_ms.items())
            + "[/dim]"
        )


@app.command()
def users() -> None:
    """Demo users and the principals their identity-provider groups map to."""
    settings = _settings()
    from clearance.auth.devidp import Directory
    from clearance.auth.mapping import GroupMapping

    directory = Directory.load(settings.directory_file)
    mapping = GroupMapping.load(settings.group_mapping_file)
    table = Table("user", "title", "IdP groups", "principals")
    for user in directory.users:
        principals, _ = mapping.principals_for_claims(user.idp_groups)
        table.add_row(user.email, user.title, ", ".join(user.idp_groups), ", ".join(sorted(principals)))
    console.print(table)


@app.command()
def token(email: Annotated[str, typer.Argument(help="Demo user email")]) -> None:
    """Print a dev IdP token for a demo user (for curl against the API)."""
    services = _services(_settings(), model=_extractive(), migrate=False)
    if services.dev_idp is None:
        raise typer.BadParameter("the dev IdP is disabled")
    print(services.dev_idp.issue(email))


# ---- ACLs -----------------------------------------------------------------------------------------------
def _find_document(services: Any, ref: str) -> Any:
    from sqlalchemy import or_, select

    from clearance.db.models import Document

    with services.db.owner_session() as session:
        query = select(Document).where(or_(Document.external_id == ref, Document.title == ref))
        with contextlib.suppress(ValueError):
            query = select(Document).where(Document.id == uuid.UUID(ref))
        document = session.scalar(query)
        if document is None:
            raise typer.BadParameter(f"no document {ref!r}")
        return document


@acl_app.command("show")
def acl_show(document: Annotated[str, typer.Argument(help="Document id, external id or title")]) -> None:
    services = _services(_settings(), model=_extractive())
    doc = _find_document(services, document)
    console.print_json(json.dumps({"id": str(doc.id), "external_id": doc.external_id, "acl": doc.acl}))


@acl_app.command("set")
def acl_set(
    document: Annotated[str, typer.Argument(help="Document id, external id or title")],
    allow: Annotated[list[str] | None, typer.Option(help="Principal to allow (repeatable)")] = None,
    deny: Annotated[list[str] | None, typer.Option(help="Principal to deny (repeatable)")] = None,
    keep_sections: Annotated[bool, typer.Option(help="Keep existing section overrides")] = True,
) -> None:
    """Replace a document's allow/deny lists. Takes effect on the next query; nothing is re-embedded."""
    services = _services(_settings(), model=_extractive())
    doc = _find_document(services, document)
    current = DocumentAcl.from_json(doc.acl)
    acl = DocumentAcl(
        normalize_principals(allow or []), normalize_principals(deny or []), current.sections if keep_sections else ()
    )
    result = services.writer.set_acl(doc.id, acl)
    console.print(
        f"updated {result.chunks_updated} chunk ACL rows in {result.elapsed_ms:.1f} ms (version {result.acl_version})"
    )


# ---- server ---------------------------------------------------------------------------------------------
@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the API (and the dev IdP) with uvicorn."""
    import uvicorn

    uvicorn.run("clearance.api.app:create_default_app", factory=True, host=host, port=port, reload=reload)


# ---- evaluation -----------------------------------------------------------------------------------------
def _cloud_settings(settings: Settings) -> Settings:
    # The evaluation's cloud calls are explicit: local-only is lifted for this process only, the free-only guard stays.
    return settings.model_copy(update={"local_only": False})


@eval_app.command("leak")
def eval_leak(
    generate: Annotated[str, typer.Option(help="Comma-separated systems to also generate answers for")] = "",
    provider: Annotated[str | None, typer.Option(help="Generator provider for answer leaks")] = None,
    model: Annotated[str | None, typer.Option()] = None,
    output: Annotated[Path, typer.Option()] = Path("results/leak.json"),
) -> None:
    """Leak test: every user x adversarial question; Clearance vs RLS-only vs post-filter vs no filter."""
    from clearance.eval.runner import prepare, run_leak, run_recall, run_recall_study, write_json
    from clearance.llm.factory import build_chat_model

    settings = _settings()
    targets = [name.strip() for name in generate.split(",") if name.strip()]
    generator = build_chat_model(settings, provider=_provider(provider), model=model) if targets else None
    ctx = prepare(settings, model=_extractive())
    result = run_leak(ctx, generator, generate_for=targets)
    result["postfilter_recall"] = run_recall(ctx)
    result["postfilter_recall_study"] = run_recall_study(ctx)
    write_json(output, result)
    _print_leak(result)


def _provider(value: str | None) -> LLMProviderKind | None:
    return value  # type: ignore[return-value]


def _print_leak(result: dict[str, Any]) -> None:
    table = Table("system", "pairs", "restricted chunk in context", "hidden canary in context", "canary in answer")
    for name, s in result["systems"].items():
        table.add_row(
            name,
            str(s["pairs"]),
            f"{s['pairs_with_restricted_chunk_in_context']} ({s['context_leak_rate']:.1%})",
            str(s["pairs_with_hidden_canary_in_context"]),
            str(s.get("pairs_with_hidden_canary_in_answer", "-")),
        )
    console.print(table)
    recall = result.get("postfilter_recall")
    if recall:
        console.print(
            {name: v["recall_at_k"] for name, v in recall["systems"].items()}
            | {"lost": recall["answers_lost_by_postfilter"]}
        )


@eval_app.command("quality")
def eval_quality(
    local_model: Annotated[str | None, typer.Option(help="Ollama model for the local generator")] = None,
    cloud_model: Annotated[str | None, typer.Option(help="Free OpenRouter model id (must end in :free)")] = None,
    judge_model: Annotated[str | None, typer.Option(help="Free OpenRouter judge model id")] = None,
    skip_cloud: Annotated[bool, typer.Option(help="Local generator only, no judge (no API calls)")] = False,
    output: Annotated[Path, typer.Option()] = Path("results/quality.json"),
) -> None:
    """Answer quality on authorized questions: local vs free cloud model, judged by a free cloud model."""
    from clearance.config import (
        DEFAULT_FREE_FALLBACKS,
        DEFAULT_FREE_MODEL,
        DEFAULT_JUDGE_FALLBACKS,
        DEFAULT_JUDGE_MODEL,
    )
    from clearance.eval.judge import Judge
    from clearance.eval.runner import prepare, run_quality, write_json
    from clearance.llm.factory import budgeted, build_chat_model

    settings = _settings()
    generators = {"local": build_chat_model(settings, provider="ollama", model=local_model)}
    judge = None
    if not skip_cloud:
        cloud = _cloud_settings(settings)
        cloud_id = cloud_model or DEFAULT_FREE_MODEL
        fallbacks = [m for m in DEFAULT_FREE_FALLBACKS if m != cloud_id]
        generators["cloud"] = budgeted(
            build_chat_model(cloud, provider="openrouter", model=cloud_id, fallback_models=fallbacks),
            cloud,
            tag="generate",
        )
        judge_id = judge_model or DEFAULT_JUDGE_MODEL
        judge_fallbacks = [m for m in DEFAULT_JUDGE_FALLBACKS if m != judge_id]
        judge = Judge(
            budgeted(
                build_chat_model(cloud, provider="openrouter", model=judge_id, fallback_models=judge_fallbacks),
                cloud,
                tag="judge",
            )
        )
    ctx = prepare(settings, model=_extractive())
    result = run_quality(ctx, generators, judge)
    write_json(output, result)
    for label, data in result["generators"].items():
        console.print(label, data["model"], data["summary"])


@eval_app.command("local-models")
def eval_local_models(
    models: Annotated[str, typer.Option(help="Comma-separated Ollama models to compare")] = "qwen3.5:4b,qwen3.5:latest",
    output: Annotated[Path, typer.Option()] = Path("results/local_models.json"),
) -> None:
    """Compare local models on the authorized questions (speed and key-fact check; no judge, no API calls)."""
    from clearance.eval.runner import prepare, run_quality, write_json
    from clearance.llm.factory import build_chat_model

    settings = _settings()
    names = [m.strip() for m in models.split(",") if m.strip()]
    generators = {name: build_chat_model(settings, provider="ollama", model=name) for name in names}
    ctx = prepare(settings, model=_extractive())
    result = run_quality(ctx, generators, None, log_prefix="local")
    write_json(output, result)
    for label, data in result["generators"].items():
        console.print(label, data["summary"])


@eval_app.command("acl-change")
def eval_acl_change(output: Annotated[Path, typer.Option()] = Path("results/acl_change.json")) -> None:
    """Revoke access, check the next query no longer retrieves the document, measure ACL update latency."""
    from clearance.eval.runner import prepare, run_acl_change, write_json

    ctx = prepare(_settings(), model=_extractive())
    result = run_acl_change(ctx)
    write_json(output, result)
    console.print(result["revocations"] | {"deletions": result["deletions"]})


@eval_app.command("latency")
def eval_latency(
    quality: Annotated[Path, typer.Option(help="Quality results to take generation latency from")] = Path(
        "results/quality.json"
    ),
    output: Annotated[Path, typer.Option()] = Path("results/latency.json"),
) -> None:
    """Embedding and retrieval latency (p50/p95) on this machine, plus generation latency from the quality run."""
    from clearance.eval.runner import prepare, run_latency, write_json

    ctx = prepare(_settings(), model=_extractive())
    quality_data = json.loads(quality.read_text(encoding="utf-8")) if quality.exists() else None
    result = run_latency(ctx, quality_data)
    write_json(output, result)
    console.print(result)


@eval_app.command("models")
def eval_models(
    smoke: Annotated[int, typer.Option(help="Smoke-test this many candidates with one call each")] = 3,
    candidates: Annotated[str, typer.Option(help="Comma-separated model ids to try first")] = "",
    output: Annotated[Path, typer.Option()] = Path("results/smoke.json"),
) -> None:
    """List free OpenRouter models and smoke-test a few (one short call each)."""
    from clearance.eval.models import list_free_models, smoke_test

    settings = _cloud_settings(_settings())
    free = list_free_models(settings)
    console.print(f"{len(free)} free models listed")
    preferred = [c.strip() for c in candidates.split(",") if c.strip()]
    result = smoke_test(settings, free, preferred=preferred, count=smoke)
    from clearance.eval.runner import write_json

    if output.exists():  # keep earlier smoke rows: the file is the record of every model tried
        previous = json.loads(output.read_text(encoding="utf-8"))
        result["smoke"] = [*previous.get("smoke", []), *result["smoke"]]
        result["preferred"] = list(dict.fromkeys([*previous.get("preferred", []), *result["preferred"]]))
    write_json(output, result)
    for row in result["smoke"]:
        console.print(row)


@eval_app.command("ledger")
def eval_ledger(
    ledger: Annotated[Path, typer.Option()] = Path("results/calls.jsonl"),
    output: Annotated[Path, typer.Option()] = Path("results/calls_summary.json"),
) -> None:
    """Summarize the call ledger: requests by status and tag, models requested and served, all ids free?"""
    from clearance.eval.models import summarize_ledger
    from clearance.eval.runner import write_json

    summary = summarize_ledger(ledger)
    write_json(output, summary)
    console.print(summary)


def main() -> None:  # pragma: no cover
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
