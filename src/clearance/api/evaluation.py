"""Serves the committed evaluation results (results/*.json) to the dashboard's evaluation page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RESULT_FILES = ("leak", "quality", "acl_change", "latency", "smoke", "calls_summary")


def load_results(results_dir: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in RESULT_FILES:
        path = results_dir / f"{name}.json"
        results[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return results
