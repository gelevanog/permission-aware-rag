"""Evaluation runs: leak test vs baselines, answer quality (local vs cloud, LLM judge), permission-change propagation,
latency. Each writes a JSON file under results/ (see README > Results)."""

from __future__ import annotations

import json
import platform
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from clearance.acl import DocumentAcl
from clearance.assistant import Assistant, build_messages, is_no_answer
from clearance.auth.tokens import Identity
from clearance.config import Settings
from clearance.connectors.local import iter_folder
from clearance.db.models import Document
from clearance.embeddings import Embedder
from clearance.eval.dataset import (
    Canary,
    CorpusOracle,
    QuestionSet,
    load_canaries,
    load_questions,
)
from clearance.eval.judge import Judge
from clearance.eval.metrics import hit_at_k, rate, reciprocal_rank, summarize_latency
from clearance.llm.base import ChatModel, LLMError
from clearance.retrieval.cache import PermissionScopedCache
from clearance.retrieval.search import RetrievedChunk
from clearance.services import Services, build_services

console = Console(stderr=True)

QUESTIONS = Path("data/eval/questions.yaml")
CANARIES = Path("data/eval/canaries.yaml")
COPY_MARK = "#copy"
SearchFn = Callable[[Sequence[float], Sequence[str], int], list[RetrievedChunk]]


# ---------------------------------------------------------------------------------------------------------
# Setup: a dedicated evaluation database with a fresh copy of the corpus
# ---------------------------------------------------------------------------------------------------------
def eval_database_url(settings: Settings) -> str:
    url = make_url(settings.database_url)
    return url.set(database=f"{url.database}_eval").render_as_string(hide_password=False)


def ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()


@dataclass
class EvalContext:
    settings: Settings
    services: Services
    oracle: CorpusOracle
    questions: QuestionSet
    canaries: tuple[Canary, ...]
    identities: dict[str, Identity]
    external_ids: dict[str, str] = field(default_factory=dict)

    @property
    def retriever(self) -> Any:
        return self.services.assistant.retriever

    def refresh_external_ids(self) -> None:
        with self.services.db.owner_session() as session:
            self.external_ids = {str(i): e for i, e in session.execute(select(Document.id, Document.external_id))}

    def context_of(self, hits: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
        return [hit for hit in hits if hit.score >= self.settings.min_score]

    def external_id(self, chunk: RetrievedChunk) -> str:
        """The corpus file a chunk came from (synthetic copies map back to their original)."""
        return self.external_ids[chunk.document_id].split(COPY_MARK, 1)[0]

    def is_restricted(self, principals: Sequence[str], chunk: RetrievedChunk) -> bool:
        return not self.oracle.can_read(principals, self.external_id(chunk), chunk.section_path)


def prepare(
    settings: Settings, *, embedder: Embedder | None = None, model: ChatModel | None = None, reset: bool = True
) -> EvalContext:
    url = eval_database_url(settings)
    ensure_database(url)
    eval_settings = settings.model_copy(update={"database_url": url, "cache_enabled": False, "seed_demo": False})
    services = build_services(eval_settings, embedder=embedder, model=model, migrate=True)
    if reset:
        with services.db.owner_session() as session:
            session.execute(text("DELETE FROM documents"))
            session.execute(text("DELETE FROM audit_log"))
    report = services.writer.sync_full("local", list(iter_folder(eval_settings.corpus_dir)))
    if report.errors:
        raise RuntimeError(f"corpus ingestion errors: {report.errors}")
    canaries = load_canaries(CANARIES)
    oracle = CorpusOracle.build(eval_settings.corpus_dir, canaries)
    if services.dev_idp is None:
        raise RuntimeError("the evaluation signs in as the demo users through the dev IdP (CLEARANCE_DEV_IDP_ENABLED)")
    identities = {
        user.email: services.verifier.verify(services.dev_idp.issue(user.email))
        for user in services.dev_idp.directory.users
    }
    ctx = EvalContext(eval_settings, services, oracle, load_questions(QUESTIONS), canaries, identities)
    ctx.refresh_external_ids()
    return ctx


def _meta(ctx: EvalContext, **extra: Any) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "embedding_model": ctx.services.embedder.name,
        "top_k": ctx.settings.top_k,
        "min_score": ctx.settings.min_score,
        "documents": len(ctx.oracle.acls),
        "chunks": len(ctx.oracle.chunks),
        "users": len(ctx.identities),
        "machine": f"{platform.machine()}, {platform.system()}, CPU only",
        **extra,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def generate(model: ChatModel, company: str, question: str, context: Sequence[RetrievedChunk], max_tokens: int) -> str:
    if not context:
        return "NOT_FOUND"
    completion = model.complete(build_messages(company, question, context), max_tokens=max_tokens, temperature=0.0)
    return completion.text


# ---------------------------------------------------------------------------------------------------------
# 1. Leak test
# ---------------------------------------------------------------------------------------------------------
def systems(ctx: EvalContext) -> dict[str, SearchFn]:
    r = ctx.retriever
    return {
        "clearance": r.search,
        "rls_only": r.search_rls_only,
        "postfilter": r.search_postfilter,
        "unfiltered": lambda vector, principals, k: r.search_unfiltered(vector, k),
    }


def run_leak(ctx: EvalContext, model: ChatModel | None, *, generate_for: Sequence[str] = ()) -> dict[str, Any]:
    """Every user x every adversarial question, for Clearance, the RLS-only ablation and the two baselines."""
    k = ctx.settings.top_k
    company = ctx.services.directory.company if ctx.services.directory else "the company"
    search_fns = systems(ctx)
    totals: dict[str, Counter[str]] = {name: Counter() for name in search_fns}
    by_user: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: {name: Counter() for name in search_fns})
    by_style: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: {name: Counter() for name in search_fns})
    examples: list[dict[str, Any]] = []
    memo: dict[tuple[str, tuple[str, ...]], str] = {}
    started = time.perf_counter()
    for question in ctx.questions.adversarial:
        vector = ctx.services.embedder.embed_query(question.question)
        for email, identity in ctx.identities.items():
            principals = list(identity.principals)
            hidden = ctx.oracle.hidden_canaries(principals)
            target_hidden = any(c.id in question.targets for c in hidden)
            for name, search in search_fns.items():
                counts = totals[name]
                context = ctx.context_of(search(vector, principals, k))
                restricted = [chunk for chunk in context if ctx.is_restricted(principals, chunk)]
                in_context = sorted({c.id for c in hidden for chunk in context if c.found_in(chunk.text)})
                counts["pairs"] += 1
                counts["pairs_target_hidden"] += int(target_hidden)
                counts["context_chunks"] += len(context)
                counts["restricted_chunks"] += len(restricted)
                counts["pairs_restricted_context"] += int(bool(restricted))
                counts["pairs_canary_in_context"] += int(bool(in_context))
                counts["empty_context"] += int(not context)
                leaked: list[str] = []
                if model is not None and name in generate_for:
                    key = (question.question, tuple(chunk.chunk_id for chunk in context))
                    if key not in memo:
                        memo[key] = generate(model, company, question.question, context, ctx.settings.llm_max_tokens)
                        counts["generations"] += 1
                    answer = memo[key]
                    no_answer = not context or is_no_answer(answer)
                    leaked = sorted(c.id for c in hidden if not no_answer and c.found_in(answer))
                    counts["pairs_generated"] += 1
                    counts["pairs_canary_in_answer"] += int(bool(leaked))
                    counts["no_answer"] += int(no_answer)
                    if leaked and len(examples) < 40:
                        examples.append(
                            {"system": name, "user": email, "question": question.id, "leaked_canaries": leaked}
                        )
                for bucket in (by_user[email][name], by_style[question.style][name]):
                    bucket["pairs"] += 1
                    bucket["pairs_restricted_context"] += int(bool(restricted))
                    bucket["pairs_canary_in_answer"] += int(bool(leaked))
        console.log(f"leak: {question.id} done ({time.perf_counter() - started:.0f}s, {len(memo)} generations)")

    def summary(counts: Counter[str], generated: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "pairs": counts["pairs"],
            "pairs_where_target_is_hidden": counts["pairs_target_hidden"],
            "pairs_with_restricted_chunk_in_context": counts["pairs_restricted_context"],
            "restricted_chunks_in_context": counts["restricted_chunks"],
            "context_chunks": counts["context_chunks"],
            "pairs_with_hidden_canary_in_context": counts["pairs_canary_in_context"],
            "context_leak_rate": rate(counts["pairs_restricted_context"], counts["pairs"]),
            "pairs_with_empty_context": counts["empty_context"],
        }
        if generated:
            result |= {
                "pairs_with_hidden_canary_in_answer": counts["pairs_canary_in_answer"],
                "answer_leak_rate": rate(counts["pairs_canary_in_answer"], counts["pairs_generated"]),
                "no_answer_responses": counts["no_answer"],
                "distinct_generations": counts["generations"],
            }
        return result

    return {
        **_meta(ctx, generator=model.label if model else None, questions=len(ctx.questions.adversarial)),
        "seconds": round(time.perf_counter() - started),
        "systems": {name: summary(totals[name], name in generate_for and model is not None) for name in search_fns},
        "by_user": {
            user: {name: dict(counter) for name, counter in per.items()} for user, per in sorted(by_user.items())
        },
        "by_style": {
            style: {name: dict(counter) for name, counter in per.items()} for style, per in sorted(by_style.items())
        },
        "canaries_visible_per_user": {
            email: len(ctx.oracle.visible_canaries(identity.principals)) for email, identity in ctx.identities.items()
        },
        "leak_examples": examples,
    }


# ---------------------------------------------------------------------------------------------------------
# 1b. Recall loss of post-filtering on authorized questions
# ---------------------------------------------------------------------------------------------------------
def run_recall(ctx: EvalContext, k: int | None = None) -> dict[str, Any]:
    """For every answerable question and every user who may read the whole gold document: is a gold document in the
    context? Post-filtering keeps the global top-k and drops forbidden chunks, so for users who can read little, the
    top-k is often full of chunks they cannot see and the answer is lost."""
    k = k or ctx.settings.top_k
    names = ("clearance", "postfilter", "unfiltered")
    search_fns = {name: fn for name, fn in systems(ctx).items() if name in names}
    hits: dict[str, Counter[str]] = {name: Counter() for name in names}
    per_user: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: {name: Counter() for name in names})
    lost: list[dict[str, Any]] = []
    for question in ctx.questions.authorized:
        if not question.answerable:
            continue
        vector = ctx.services.embedder.embed_query(question.question)
        for email, identity in ctx.identities.items():
            principals = list(identity.principals)
            if not any(ctx.oracle.can_read_document_fully(principals, doc) for doc in question.docs):
                continue
            found: dict[str, bool] = {}
            for name, search in search_fns.items():
                context = ctx.context_of(search(vector, principals, k))
                if name == "unfiltered":  # what a user could see of the unfiltered list (the rest is a leak)
                    context = [c for c in context if not ctx.is_restricted(principals, c)]
                docs = [ctx.external_id(c) for c in context]
                found[name] = hit_at_k(docs, question.docs, k)
                for bucket in (hits[name], per_user[email][name]):
                    bucket["pairs"] += 1
                    bucket["hits"] += int(found[name])
                    bucket["empty"] += int(not context)
                    bucket["context_chunks"] += len(context)
            if found["clearance"] and not found["postfilter"]:
                lost.append({"question": question.id, "user": email})
    return {
        "k": k,
        "pairs": hits["clearance"]["pairs"],
        "systems": {
            name: {
                "recall_at_k": rate(c["hits"], c["pairs"]),
                "pairs_with_empty_context": c["empty"],
                "mean_context_chunks": round(c["context_chunks"] / c["pairs"], 2) if c["pairs"] else None,
            }
            for name, c in hits.items()
        },
        "answers_lost_by_postfilter": len(lost),
        "lost_examples": lost[:30],
        "by_user": {
            user: {name: rate(c["hits"], c["pairs"]) for name, c in per.items()} | {"pairs": per["clearance"]["pairs"]}
            for user, per in sorted(per_user.items())
        },
    }


def add_restricted_copies(ctx: EvalContext, copies: int) -> int:
    """Stress test: add `copies` duplicates of every document that is not company-wide (same text, embeddings and ACL),
    like the historical versions of board packs, salary reviews and minutes a real document store keeps. Copies are
    made in SQL, without re-embedding, and removed by `remove_restricted_copies`."""
    company_wide = ["group:all-employees"]
    restricted = [ext for ext, acl in ctx.oracle.acls.items() if not acl.readable_by(company_wide)]
    by_external = {external: doc_id for doc_id, external in ctx.external_ids.items()}
    added = 0
    with ctx.services.db.owner_session() as session:
        for external in restricted:
            for index in range(1, copies + 1):
                new_id = _uuid_new()
                params = {"old": _uuid(by_external[external]), "new": new_id, "suffix": f"{COPY_MARK}{index}"}
                session.execute(
                    text(
                        "INSERT INTO documents (id, source, external_id, title, path, mime_type, owner, content_hash, "
                        "acl, acl_version) SELECT :new, 'synthetic', external_id || :suffix, title, path, mime_type, "
                        "owner, content_hash, acl, acl_version FROM documents WHERE id = :old"
                    ),
                    params,
                )
                session.execute(
                    text(
                        "INSERT INTO chunks (id, document_id, ordinal, section_path, text, embedding) "
                        "SELECT gen_random_uuid(), :new, ordinal, section_path, text, embedding "
                        "FROM chunks WHERE document_id = :old"
                    ),
                    params,
                )
                session.execute(
                    text(
                        "INSERT INTO chunk_acl (chunk_id, document_id, allow_principals, deny_principals, acl_version) "
                        "SELECT n.id, :new, a.allow_principals, a.deny_principals, a.acl_version FROM chunks n "
                        "JOIN chunks o ON o.document_id = :old AND o.ordinal = n.ordinal "
                        "JOIN chunk_acl a ON a.chunk_id = o.id WHERE n.document_id = :new"
                    ),
                    params,
                )
                added += 1
    ctx.refresh_external_ids()
    return added


def remove_restricted_copies(ctx: EvalContext) -> None:
    with ctx.services.db.owner_session() as session:
        session.execute(text("DELETE FROM documents WHERE source = 'synthetic'"))
    ctx.refresh_external_ids()


def run_recall_study(
    ctx: EvalContext, ks: Sequence[int] = (3, 5, 10), copies: Sequence[int] = (0, 3, 10)
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for count in copies:
        remove_restricted_copies(ctx)
        added = add_restricted_copies(ctx, count) if count else 0
        for k in ks:
            result = run_recall(ctx, k)
            rows.append(
                {
                    "restricted_copies": count,
                    "documents_added": added,
                    "k": k,
                    "pairs": result["pairs"],
                    **{f"recall_{name}": v["recall_at_k"] for name, v in result["systems"].items()},
                    **{f"empty_{name}": v["pairs_with_empty_context"] for name, v in result["systems"].items()},
                    **{f"context_{name}": v["mean_context_chunks"] for name, v in result["systems"].items()},
                    "answers_lost_by_postfilter": result["answers_lost_by_postfilter"],
                }
            )
            console.log(f"recall study: copies={count} k={k}: {rows[-1]}")
    remove_restricted_copies(ctx)
    return rows


# ---------------------------------------------------------------------------------------------------------
# 2. Answer quality
# ---------------------------------------------------------------------------------------------------------
def run_quality(
    ctx: EvalContext, generators: dict[str, ChatModel], judge: Judge | None, *, log_prefix: str = "quality"
) -> dict[str, Any]:
    company = ctx.services.directory.company if ctx.services.directory else "the company"
    results: dict[str, Any] = {}
    retrieval: dict[str, Any] = {}
    for label, model in generators.items():
        assistant = Assistant(
            settings=ctx.settings,
            db=ctx.services.db,
            embedder=ctx.services.embedder,
            model=model,
            audit=None,
            cache=PermissionScopedCache(enabled=False),
            company=company,
        )
        rows: list[dict[str, Any]] = []
        for question in ctx.questions.authorized:
            identity = ctx.identities[question.user]
            started = time.perf_counter()
            try:
                answer = assistant.ask(identity, question.question)
            except LLMError as exc:
                rows.append({"id": question.id, "error": str(exc)[:200]})
                console.log(f"{log_prefix} {label} {question.id}: error {exc}")
                continue
            elapsed = (time.perf_counter() - started) * 1000
            retrieved_docs = [ctx.external_ids[r["document_id"]] for r in answer.trace.retrieved if r["in_context"]]
            all_docs = [ctx.external_ids[r["document_id"]] for r in answer.trace.retrieved]
            row: dict[str, Any] = {
                "id": question.id,
                "user": question.user,
                "answerable": question.answerable,
                "gold_docs": list(question.docs),
                "outcome": answer.outcome,
                "answer": answer.text,
                "cited_docs": sorted({ctx.external_ids[c.document_id] for c in answer.citations}),
                "retrieved_docs": retrieved_docs,
                "expect_met": question.expect_met(answer.text) if question.answerable else None,
                "hit_at_k": hit_at_k(retrieved_docs, question.docs, ctx.settings.top_k)
                if question.answerable
                else None,
                "reciprocal_rank": reciprocal_rank(all_docs, question.docs) if question.answerable else None,
                "timings_ms": {key: round(value) for key, value in answer.trace.timings_ms.items()},
                "wall_ms": round(elapsed),
                "fallback": answer.trace.fallback,
                "served_model": getattr(model, "last_served", None) or model.label,
            }
            if question.answerable and answer.outcome == "answered" and judge is not None:
                context = ctx.context_of(
                    ctx.retriever.search(
                        ctx.services.embedder.embed_query(question.question),
                        identity.principals,
                        ctx.settings.top_k,
                    )
                )
                verdict = judge.grade(question, answer.text, context)
                row["judge"] = verdict
            rows.append(row)
            console.log(
                f"{log_prefix} {label} {question.id}: {answer.outcome} "
                f"expect={row['expect_met']} judge={row.get('judge', {}).get('correct')} {elapsed / 1000:.1f}s"
            )
        results[label] = {"model": model.label, "summary": summarize_quality(rows), "rows": rows}
        if not retrieval:
            answerable = [r for r in rows if r.get("answerable") and "error" not in r]
            retrieval = {
                "questions": len(answerable),
                "recall_at_k": rate(sum(bool(r["hit_at_k"]) for r in answerable), len(answerable)),
                "mrr": round(sum(r["reciprocal_rank"] for r in answerable) / len(answerable), 3)
                if answerable
                else None,
            }
    return {
        **_meta(ctx, judge=judge.label if judge else None),
        "questions": len(ctx.questions.authorized),
        "retrieval": retrieval,
        "generators": results,
    }


def summarize_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if "error" not in r]
    answerable = [r for r in ok if r["answerable"]]
    unanswerable = [r for r in ok if not r["answerable"]]
    judged = [r for r in answerable if "judge" in r and r["judge"].get("correct") is not None]
    answered = [r for r in answerable if r["outcome"] == "answered"]
    correct = sum(1 for r in judged if r["judge"]["correct"])
    faithful_judged = [r for r in judged if r["judge"].get("faithful") is not None]
    generate_ms = [r["timings_ms"]["generate"] for r in ok if "generate" in r["timings_ms"]]
    return {
        "answerable": len(answerable),
        "errors": len(rows) - len(ok),
        # Refusals count as incorrect: correctness is over all answerable questions, not only answered ones.
        "correct": correct if judged else None,
        "correctness": rate(correct, len(answerable)) if judged else None,
        "judged": len(judged),
        "faithfulness": rate(sum(1 for r in faithful_judged if r["judge"]["faithful"]), len(faithful_judged)),
        "expect_met": rate(sum(1 for r in answerable if r["expect_met"]), len(answerable)),
        "false_refusals": len(answerable) - len(answered),
        "answered_with_citation": rate(sum(1 for r in answered if r["cited_docs"]), len(answered)),
        "cited_a_gold_doc": rate(sum(1 for r in answered if set(r["cited_docs"]) & set(r["gold_docs"])), len(answered)),
        "unanswerable": len(unanswerable),
        "unanswerable_declined": sum(1 for r in unanswerable if r["outcome"] == "no_answer"),
        "generate_ms": summarize_latency(generate_ms),
        "fallbacks": sum(1 for r in ok if r.get("fallback")),
    }


# ---------------------------------------------------------------------------------------------------------
# 3. Permission changes propagate immediately
# ---------------------------------------------------------------------------------------------------------
class CountingEmbedder:
    def __init__(self, inner: Embedder) -> None:
        self.inner = inner
        self.document_calls = 0

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def dim(self) -> int:
        return self.inner.dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += len(texts)
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)


def run_acl_change(ctx: EvalContext) -> dict[str, Any]:
    """Revoke (deny), confirm the next query no longer sees the document, restore; then delete and re-ingest."""
    k = ctx.settings.top_k
    writer = ctx.services.writer
    counting = CountingEmbedder(ctx.services.embedder)
    writer.embedder = counting
    trials: list[dict[str, Any]] = []
    update_ms: list[float] = []
    visible_again_ms: list[float] = []
    reembed_ms: list[float] = []
    by_external = {external: doc_id for doc_id, external in ctx.external_ids.items()}
    for question in [q for q in ctx.questions.authorized if q.answerable]:
        identity = ctx.identities[question.user]
        principals = list(identity.principals)
        vector = ctx.services.embedder.embed_query(question.question)
        before = {ctx.external_ids[c.document_id] for c in ctx.context_of(ctx.retriever.search(vector, principals, k))}
        target = next((doc for doc in question.docs if doc in before), None)
        if target is None:
            continue
        doc_id = by_external[target]
        original = _load_acl(ctx, doc_id)
        revoked = DocumentAcl(
            original.allow, tuple(sorted({*original.deny, identity.user_principal})), original.sections
        )
        calls_before = counting.document_calls
        result = writer.set_acl(_uuid(doc_id), revoked)
        after_started = time.perf_counter()
        after = {ctx.external_ids[c.document_id] for c in ctx.retriever.search(vector, principals, k)}
        first_query_ms = (time.perf_counter() - after_started) * 1000
        rls_after = {ctx.external_ids[c.document_id] for c in ctx.retriever.search_rls_only(vector, principals, k)}
        listed = {d.id for d in ctx.retriever.searchable_documents(principals)}
        writer.set_acl(_uuid(doc_id), original)
        restored = {ctx.external_ids[c.document_id] for c in ctx.retriever.search(vector, principals, k)}
        update_ms.append(result.elapsed_ms)
        visible_again_ms.append(first_query_ms)
        trials.append(
            {
                "question": question.id,
                "user": question.user,
                "document": target,
                "chunks_updated": result.chunks_updated,
                "acl_update_ms": round(result.elapsed_ms, 1),
                "excluded_on_next_query": target not in after,
                "excluded_under_rls_only": target not in rls_after,
                "hidden_from_document_list": doc_id not in listed,
                "back_after_restore": target in restored,
                "embeddings_computed": counting.document_calls - calls_before,
            }
        )
    # Deletion: the document disappears from search in the same transaction; re-ingest restores it.
    deletions: list[dict[str, Any]] = []
    for question in [q for q in ctx.questions.authorized if q.answerable][:10]:
        identity = ctx.identities[question.user]
        vector = ctx.services.embedder.embed_query(question.question)
        before = {ctx.external_ids[c.document_id] for c in ctx.retriever.search(vector, identity.principals, k)}
        target = next((doc for doc in question.docs if doc in before), None)
        if target is None:
            continue
        started = time.perf_counter()
        writer.delete(_uuid(by_external[target]))
        delete_ms = (time.perf_counter() - started) * 1000
        after = {ctx.external_ids.get(c.document_id, "?") for c in ctx.retriever.search(vector, identity.principals, k)}
        started = time.perf_counter()
        source = next(d for d in iter_folder(ctx.settings.corpus_dir) if d.external_id == target)
        writer.upsert(source)
        reembed_ms.append((time.perf_counter() - started) * 1000)
        ctx.refresh_external_ids()
        by_external = {external: doc_id for doc_id, external in ctx.external_ids.items()}
        deletions.append(
            {"document": target, "delete_ms": round(delete_ms, 1), "gone_on_next_query": target not in after}
        )
    writer.embedder = counting.inner
    return {
        **_meta(ctx),
        "revocations": {
            "trials": len(trials),
            "excluded_on_next_query": sum(t["excluded_on_next_query"] for t in trials),
            "excluded_under_rls_only": sum(t["excluded_under_rls_only"] for t in trials),
            "hidden_from_document_list": sum(t["hidden_from_document_list"] for t in trials),
            "back_after_restore": sum(t["back_after_restore"] for t in trials),
            "embeddings_computed": sum(t["embeddings_computed"] for t in trials),
            "acl_update_ms": summarize_latency(update_ms),
            "next_query_ms": summarize_latency(visible_again_ms),
        },
        "deletions": {
            "trials": len(deletions),
            "gone_on_next_query": sum(d["gone_on_next_query"] for d in deletions),
            "delete_ms": summarize_latency([d["delete_ms"] for d in deletions]),
            "reingest_with_embedding_ms": summarize_latency(reembed_ms),
        },
        "trial_rows": trials,
        "deletion_rows": deletions,
    }


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def _uuid_new() -> uuid.UUID:
    return uuid.uuid4()


def _load_acl(ctx: EvalContext, doc_id: str) -> DocumentAcl:
    with ctx.services.db.owner_session() as session:
        document = session.get(Document, _uuid(doc_id))
        assert document is not None
        return DocumentAcl.from_json(document.acl)


# ---------------------------------------------------------------------------------------------------------
# 4. Latency on CPU
# ---------------------------------------------------------------------------------------------------------
def run_latency(ctx: EvalContext, quality: dict[str, Any] | None = None) -> dict[str, Any]:
    questions = [q.question for q in ctx.questions.authorized] + [q.question for q in ctx.questions.adversarial]
    embed_ms: list[float] = []
    vectors = []
    for question in questions:
        started = time.perf_counter()
        vectors.append(ctx.services.embedder.embed_query(question))
        embed_ms.append((time.perf_counter() - started) * 1000)
    retrieve_ms: list[float] = []
    index_ms: list[float] = []
    for vector in vectors:
        for identity in ctx.identities.values():
            started = time.perf_counter()
            ctx.retriever.search(vector, identity.principals, ctx.settings.top_k)
            retrieve_ms.append((time.perf_counter() - started) * 1000)
    # The same searches with sequential scans disabled, so the planner must walk the HNSW index (iterative scan):
    # what a large corpus would do. Results must still be k permitted rows for every user.
    full_k = 0
    ctx.services.db.force_index_scan = True
    try:
        for vector in vectors:
            for identity in ctx.identities.values():
                started = time.perf_counter()
                rows = ctx.retriever.search(vector, identity.principals, ctx.settings.top_k)
                index_ms.append((time.perf_counter() - started) * 1000)
                full_k += int(len(rows) == ctx.settings.top_k)
    finally:
        ctx.services.db.force_index_scan = False
    result: dict[str, Any] = {
        **_meta(ctx),
        "embed_query_ms": summarize_latency(embed_ms),
        "retrieve_ms": summarize_latency(retrieve_ms),
        "retrieve_hnsw_forced_ms": summarize_latency(index_ms),
        "hnsw_searches_returning_full_k": f"{full_k}/{len(index_ms)}",
    }
    if quality:
        for label, data in quality.get("generators", {}).items():
            rows = [r for r in data["rows"] if "error" not in r]
            result[f"generate_ms_{label}"] = summarize_latency(
                [r["timings_ms"]["generate"] for r in rows if "generate" in r["timings_ms"]]
            )
            result[f"end_to_end_ms_{label}"] = summarize_latency([r["timings_ms"]["total"] for r in rows])
    return result
