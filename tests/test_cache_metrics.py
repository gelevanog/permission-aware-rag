"""Permission-scoped cache keys, evaluation metrics, canary matching, judge parsing, audit masking."""

from __future__ import annotations

import time

import pytest

from clearance.audit import mask_preview
from clearance.eval.dataset import AuthorizedQuestion, Canary
from clearance.eval.judge import parse_verdict
from clearance.eval.metrics import hit_at_k, percentile, rate, reciprocal_rank, summarize_latency
from clearance.retrieval.cache import PermissionScopedCache, principals_hash

ALICE = ["user:alice@x.test", "group:finance"]
DAN = ["user:dan@x.test", "group:engineering"]


def test_cache_keys_always_include_principals_and_epoch() -> None:
    key = PermissionScopedCache.key
    assert key("answer", ALICE, 1, "q") != key("answer", DAN, 1, "q")
    assert key("answer", ALICE, 1, "q") != key("answer", ALICE, 2, "q")
    assert key("answer", ALICE, 1, "q") == key("answer", list(reversed(ALICE)), 1, "q")  # order-insensitive
    with pytest.raises(ValueError, match="principal"):
        key("answer", [], 1, "q")


def test_cache_isolation_between_users_and_after_permission_changes() -> None:
    cache: PermissionScopedCache[str] = PermissionScopedCache()
    cache.put("answer", ALICE, 7, "salary?", value="Alice's answer")
    assert cache.get("answer", ALICE, 7, "salary?") == "Alice's answer"
    assert cache.get("answer", DAN, 7, "salary?") is None  # never served to another principal set
    assert cache.get("answer", ALICE, 8, "salary?") is None  # stale after an ACL change bumps the epoch


def test_cache_ttl_lru_and_disable() -> None:
    cache: PermissionScopedCache[int] = PermissionScopedCache(max_entries=2, ttl_seconds=0.05)
    for i in range(3):
        cache.put("n", ALICE, 0, i, value=i)
    assert cache.get("n", ALICE, 0, 0) is None and cache.get("n", ALICE, 0, 2) == 2
    time.sleep(0.06)
    assert cache.get("n", ALICE, 0, 2) is None
    off: PermissionScopedCache[int] = PermissionScopedCache(enabled=False)
    off.put("n", ALICE, 0, value=1)
    assert off.get("n", ALICE, 0) is None


def test_principals_hash_is_stable() -> None:
    assert principals_hash(ALICE) == principals_hash(list(reversed(ALICE)))
    assert principals_hash(ALICE) != principals_hash(DAN)


def test_percentiles_and_retrieval_metrics() -> None:
    assert percentile([], 50) is None
    assert percentile([5.0], 95) == 5.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile(list(range(101)), 95) == 95
    assert summarize_latency([10, 20, 30])["p50"] == 20
    assert hit_at_k(["a", "b", "c"], ["c"], 3) and not hit_at_k(["a", "b", "c"], ["c"], 2)
    assert reciprocal_rank(["a", "b", "c"], ["b", "z"]) == 0.5 and reciprocal_rank(["a"], ["z"]) == 0.0
    assert rate(1, 4) == 0.25 and rate(1, 0) is None


def test_canary_matching_respects_number_boundaries() -> None:
    salary = Canary("dan-salary", "salary", ("171,500", "171500"))
    assert salary.found_in("Dan earns $171,500 per year")
    assert salary.found_in("base 171500.")
    assert not salary.found_in("the total was $1,171,500")
    assert not salary.found_in("171,5009 units")
    codename = Canary("kingfisher", "codename", ("Kingfisher",))
    assert codename.found_in("Project KINGFISHER is on track")


def test_expect_check_accepts_alternatives() -> None:
    question = AuthorizedQuestion("q", "u", "?", "a", ("doc",), ("24 December|December 24", "1 January"))
    assert question.expect_met("From December 24 to 1 January 2027.")
    assert not question.expect_met("From December 24 onwards.")


def test_judge_verdict_parsing() -> None:
    assert parse_verdict('{"correct": true, "faithful": false, "reason": "adds a fact"}')["faithful"] is False
    thinking = 'Let me think {"correct": false}... final: {"correct": true, "faithful": true, "reason": "ok"}'
    assert parse_verdict(thinking)["correct"] is True
    assert parse_verdict("no json here")["correct"] is None


def test_audit_preview_masks_numbers_emails_and_tokens() -> None:
    preview = mask_preview("Is dan.kim@fernhill.test paid $171,500? token " + "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
    assert "171" not in preview and "dan.kim" not in preview and "ABCDEF" not in preview
    assert len(mask_preview("x" * 500)) <= 60
