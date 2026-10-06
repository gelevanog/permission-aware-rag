"""Local-only switch, free-only guard, providers (mocked HTTP) and the budget wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from clearance.llm.base import (
    BudgetExceededError,
    LLMError,
    LLMUnavailableError,
    PolicyViolationError,
    RetryableLLMError,
)
from clearance.llm.budget import BudgetedModel, CallLedger, DiskCache, Throttle
from clearance.llm.extractive import NOT_FOUND, extract_answer
from clearance.llm.factory import budgeted, build_chat_model
from clearance.llm.guards import ensure_free_models, ensure_local_allowed, is_local_url
from clearance.llm.ollama import OllamaModel
from clearance.llm.openai_compat import OpenAICompatibleModel
from tests.conftest import make_settings

MESSAGES: list[Any] = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
SECRET_PROMPT: list[Any] = [{"role": "user", "content": "What is Dan's salary? zebra-canary"}]


# ---- local-only switch ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080",
        "http://[::1]:8000",
        "http://ollama:11434",
        "http://10.0.3.7:8000/v1",
        "http://192.168.1.20/v1",
        "http://gpu-box.internal:8000",
        "http://vllm.local/v1",
    ],
)
def test_local_urls_are_allowed(url: str) -> None:
    assert is_local_url(url)
    ensure_local_allowed("openai_compatible", url, local_only=True)


@pytest.mark.parametrize(
    "url", ["https://api.openai.com/v1", "https://openrouter.ai/api/v1", "http://8.8.8.8/v1", "http://example.com"]
)
def test_remote_urls_are_refused_in_local_only_mode(url: str) -> None:
    assert not is_local_url(url)
    with pytest.raises(PolicyViolationError, match="local-only"):
        ensure_local_allowed("openai_compatible", url, local_only=True)
    ensure_local_allowed("openai_compatible", url, local_only=False)  # explicit opt-out


def test_allowed_hosts_extend_the_local_list() -> None:
    assert is_local_url("https://llm.corp.example.com/v1", ["llm.corp.example.com"])


@pytest.mark.parametrize("provider", ["openrouter", "openai", "anthropic"])
def test_cloud_providers_are_refused_by_default(provider: str) -> None:
    settings = make_settings(llm_provider=provider, openrouter_api_key="k", openai_api_key="k", anthropic_api_key="k")
    assert settings.local_only is True  # the default
    with pytest.raises(PolicyViolationError, match="local-only"):
        build_chat_model(settings)


def test_local_providers_are_built_in_local_only_mode() -> None:
    assert build_chat_model(make_settings(llm_provider="ollama")).label.startswith("ollama/")
    assert build_chat_model(make_settings(llm_provider="extractive")).is_local
    model = build_chat_model(make_settings(llm_provider="openai_compatible", llm_base_url="http://vllm:8000/v1"))
    assert model.is_local


# ---- free-only guard -----------------------------------------------------------------------------------------
def test_free_only_guard_refuses_paid_ids() -> None:
    ensure_free_models(["a/b:free", "c/d:free"])
    with pytest.raises(PolicyViolationError, match="non-free"):
        ensure_free_models(["a/b:free", "openai/gpt-5"])


def test_factory_refuses_paid_openrouter_models_and_fallbacks() -> None:
    settings = make_settings(local_only=False, openrouter_api_key="k")
    with pytest.raises(PolicyViolationError):
        build_chat_model(settings, provider="openrouter", model="anthropic/claude-sonnet-5")
    with pytest.raises(PolicyViolationError):
        build_chat_model(settings, provider="openrouter", model="x/y:free", fallback_models=["openai/gpt-5"])
    assert build_chat_model(settings, provider="openrouter", model="x/y:free").label == "openrouter/x/y:free"
    relaxed = make_settings(local_only=False, openrouter_api_key="k", require_free_models=False)
    assert build_chat_model(relaxed, provider="openrouter", model="anthropic/claude-sonnet-5")


def _openrouter(handler: Any, **kwargs: Any) -> OpenAICompatibleModel:
    return OpenAICompatibleModel(
        kind="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="x/y:free",
        api_key="k",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_openrouter_request_carries_fallbacks_and_rejects_a_paid_served_model() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"model": "openai/gpt-5", "choices": [{"message": {"content": "hi"}}]})

    model = _openrouter(handler, fallback_models=["z/w:free"])
    with pytest.raises(PolicyViolationError, match="served non-free"):
        model.complete(MESSAGES, max_tokens=10)
    assert seen["models"] == ["x/y:free", "z/w:free"]


def test_openrouter_errors_are_classified() -> None:
    def rate_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate-limited upstream"}}, headers={"retry-after": "7"})

    with pytest.raises(RetryableLLMError) as info:
        _openrouter(rate_limited).complete(MESSAGES, max_tokens=10)
    assert info.value.retry_after == 7.0

    def in_body(request: httpx.Request) -> httpx.Response:  # OpenRouter reports upstream failures inside a 200
        return httpx.Response(200, json={"error": {"code": 502, "message": "provider down"}})

    with pytest.raises(RetryableLLMError):
        _openrouter(in_body).complete(MESSAGES, max_tokens=10)

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "denied"}})

    with pytest.raises(LLMError):
        _openrouter(forbidden).complete(MESSAGES, max_tokens=10)


def test_openai_compatible_streaming() -> None:
    chunks = [{"model": "x/y:free", "choices": [{"delta": {"content": part}}]} for part in ("Hel", "lo")]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    assert "".join(_openrouter(handler).stream(MESSAGES, max_tokens=10)) == "Hello"


# ---- Ollama --------------------------------------------------------------------------------------------------
def test_ollama_turns_thinking_off_and_sets_the_context_window() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "message": {"content": "Answer [1]."},
                "prompt_eval_count": 900,
                "eval_count": 12,
            },
        )

    model = OllamaModel(
        base_url="http://localhost:11434/v1", model="qwen3.5:4b", transport=httpx.MockTransport(handler)
    )
    completion = model.complete(MESSAGES, max_tokens=300)
    assert completion.text == "Answer [1]." and completion.input_tokens == 900
    assert seen["think"] is False and seen["options"]["num_ctx"] == 4096 and seen["options"]["num_predict"] == 300


def test_ollama_streaming_and_unreachable_server() -> None:
    lines = [{"message": {"content": "A"}}, {"message": {"content": "B"}}, {"done": True}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    model = OllamaModel(base_url="http://localhost:11434", model="m", transport=httpx.MockTransport(handler))
    assert "".join(model.stream(MESSAGES, max_tokens=5)) == "AB"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    down = OllamaModel(base_url="http://localhost:11434", model="m", transport=httpx.MockTransport(refuse))
    with pytest.raises(LLMUnavailableError):
        down.complete(MESSAGES, max_tokens=5)


# ---- Anthropic (mocked client; the official SDK's surface) -----------------------------------------------------
def test_anthropic_provider_maps_system_prompt_and_text_blocks() -> None:
    from clearance.llm.anthropic_provider import AnthropicModel

    calls: list[dict[str, Any]] = []

    def create(**params: Any) -> Any:
        calls.append(params)
        return SimpleNamespace(
            stop_reason="end_turn",
            model="claude-sonnet-5",
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Answer [1].")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=3),
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    model = AnthropicModel(client=client)  # type: ignore[arg-type]
    completion = model.complete(MESSAGES, max_tokens=500)
    assert completion.text == "Answer [1]."
    assert calls[0]["system"] == "s" and calls[0]["messages"] == [{"role": "user", "content": "q"}]
    assert calls[0]["model"] == "claude-sonnet-5" and calls[0]["max_tokens"] >= 4096
    assert not model.is_local


# ---- budget wrapper ------------------------------------------------------------------------------------------
class FakeRemote:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.calls = 0

    label = "openrouter/x/y:free"
    is_local = False

    def complete(self, messages: Any, *, max_tokens: int, temperature: float = 0.0) -> Any:
        from clearance.llm.base import Completion

        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=reply, model="x/y:free", input_tokens=5, output_tokens=2)

    def stream(self, messages: Any, *, max_tokens: int, temperature: float = 0.0) -> Any:
        yield self.complete(messages, max_tokens=max_tokens).text


def test_budget_wrapper_retries_caches_and_records(tmp_path: Path) -> None:
    inner = FakeRemote([RetryableLLMError("429", retry_after=0.01), "ok"])
    ledger = CallLedger(tmp_path / "calls.jsonl", max_calls=10)
    model = BudgetedModel(
        inner,
        ledger=ledger,
        cache=DiskCache(tmp_path / "cache"),
        throttle=Throttle(0),
        tag="t",
        retry_base_seconds=0.01,
    )
    assert model.complete(SECRET_PROMPT, max_tokens=5).text == "ok"
    again = model.complete(SECRET_PROMPT, max_tokens=5)
    assert again.cached and inner.calls == 2  # second answer from the disk cache, no request
    rows = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["retryable_error", "ok"]
    assert "zebra-canary" not in json.dumps(rows)  # the ledger never stores prompts


def test_budget_is_a_hard_limit(tmp_path: Path) -> None:
    ledger = CallLedger(tmp_path / "calls.jsonl", max_calls=1)
    model = BudgetedModel(FakeRemote(["a", "b"]), ledger=ledger, cache=None, throttle=None, tag="t")
    model.complete(MESSAGES, max_tokens=5)
    with pytest.raises(BudgetExceededError):
        model.complete([{"role": "user", "content": "other"}], max_tokens=5)


def test_budgeted_leaves_local_models_alone() -> None:
    model = build_chat_model(make_settings(llm_provider="ollama"))
    assert budgeted(model, make_settings(), tag="x") is model


# ---- extractive fallback -------------------------------------------------------------------------------------
def test_extractive_model_quotes_with_citations_or_declines() -> None:
    prompt = (
        "Context passages:\n\n[1] Travel Policy > Per diem\nThe per diem is €55 per day in Portugal.\n\n"
        "[2] Office Guide\nThe Lisbon office is on Rua da Prata.\n\nQuestion: What is the per diem in Portugal?"
    )
    answer = extract_answer(prompt)
    assert "€55" in answer and "[1]" in answer
    assert extract_answer(prompt.replace("What is the per diem in Portugal?", "Who won the hackathon?")) == NOT_FOUND
