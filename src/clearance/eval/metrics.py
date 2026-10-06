"""Small, dependency-free metrics used by the evaluation and covered by unit tests."""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 100]); None for an empty sequence."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * q / 100.0
    low, high = math.floor(rank), math.ceil(rank)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def summarize_latency(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "p50": _round(percentile(values, 50)),
        "p95": _round(percentile(values, 95)),
        "mean": _round(sum(values) / len(values)) if values else None,
        "max": _round(max(values)) if values else None,
    }


def hit_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> bool:
    return bool(set(retrieved[:k]) & set(gold))


def reciprocal_rank(retrieved: Sequence[str], gold: Sequence[str]) -> float:
    for index, item in enumerate(retrieved, start=1):
        if item in gold:
            return 1.0 / index
    return 0.0


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
