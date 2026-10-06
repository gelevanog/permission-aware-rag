"""Free OpenRouter models: listing, one-call smoke tests, and the call-ledger summary."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from clearance.config import Settings
from clearance.llm.base import LLMError
from clearance.llm.factory import budgeted, build_chat_model


def list_free_models(settings: Settings) -> list[dict[str, Any]]:
    """Model ids ending in ":free" from OpenRouter's public model list (no key needed, no call counted)."""
    response = httpx.get(settings.openrouter_base_url.rstrip("/") + "/models", timeout=30)
    response.raise_for_status()
    models = response.json().get("data") or []
    return [
        {"id": m["id"], "context_length": m.get("context_length"), "name": m.get("name")}
        for m in models
        if str(m.get("id", "")).endswith(":free")
    ]


def smoke_test(
    settings: Settings, free: Sequence[dict[str, Any]], *, preferred: Sequence[str] = (), count: int = 3
) -> dict[str, Any]:
    free_ids = [m["id"] for m in free]
    candidates = [m for m in preferred if m in free_ids] + [m for m in free_ids if m not in preferred]
    rows: list[dict[str, Any]] = []
    for model_id in candidates[:count]:
        model = budgeted(
            build_chat_model(settings, provider="openrouter", model=model_id, fallback_models=[]),
            settings.model_copy(update={"llm_max_retries": 0}),
            tag="smoke",
        )
        started = time.perf_counter()
        try:
            completion = model.complete(
                [{"role": "user", "content": "Reply with the single word OK."}], max_tokens=400, temperature=0.0
            )
            rows.append(
                {
                    "model": model_id,
                    "ok": True,
                    "served": completion.model,
                    "reply": completion.text.strip()[:40],
                    "seconds": round(time.perf_counter() - started, 1),
                    "cached": completion.cached,
                }
            )
        except LLMError as exc:
            rows.append({"model": model_id, "ok": False, "error": str(exc)[:200]})
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "free_models_listed": len(free_ids),
        "preferred": list(preferred),
        "smoke": rows,
    }


def summarize_ledger(path: Path) -> dict[str, Any]:
    rows = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.exists()
        else []
    )
    requested = sorted({str(r.get("requested_model")) for r in rows if r.get("requested_model")})
    served = Counter(str(r["served_model"]) for r in rows if r.get("served_model"))
    return {
        "total_requests": len(rows),
        "by_status": dict(Counter(str(r.get("status")) for r in rows)),
        "by_tag": dict(Counter(str(r.get("tag")) for r in rows)),
        "requested_models": requested,
        "served_models": dict(served),
        "all_model_ids_free": all(m.endswith(":free") for m in [*requested, *served]),
        "input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "first": rows[0]["ts"] if rows else None,
        "last": rows[-1]["ts"] if rows else None,
    }
