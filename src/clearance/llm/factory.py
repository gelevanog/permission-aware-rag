"""Builds the configured chat model, applying the local-only switch and the free-only guard first."""

from __future__ import annotations

from clearance.config import CLOUD_PROVIDERS, DEFAULT_MODELS, LLMProviderKind, Settings
from clearance.llm.anthropic_provider import AnthropicModel
from clearance.llm.base import ChatModel
from clearance.llm.budget import BudgetedModel, CallLedger, DiskCache, Throttle
from clearance.llm.extractive import ExtractiveModel
from clearance.llm.guards import ensure_free_models, ensure_local_allowed, is_local_url
from clearance.llm.ollama import OllamaModel
from clearance.llm.openai_compat import OpenAICompatibleModel


def build_chat_model(
    settings: Settings,
    *,
    provider: LLMProviderKind | None = None,
    model: str | None = None,
    fallback_models: list[str] | None = None,
) -> ChatModel:
    kind: LLMProviderKind = provider or settings.llm_provider
    name = model or (settings.llm_model if provider is None else "") or DEFAULT_MODELS[kind]
    base_url = {
        "ollama": settings.llm_base_url,
        "openai_compatible": settings.llm_base_url,
        "openrouter": settings.openrouter_base_url,
        "openai": settings.openai_base_url,
    }.get(kind)
    # Guards first: nothing is constructed (no client, no key read) for a refused provider.
    ensure_local_allowed(kind, base_url, local_only=settings.local_only, allowed_hosts=settings.local_allowed_hosts)
    fallbacks = settings.llm_fallback_models if fallback_models is None else fallback_models
    if kind == "openrouter" and settings.require_free_models:
        ensure_free_models([name, *fallbacks])

    if kind == "extractive":
        return ExtractiveModel()
    if kind == "ollama":
        return OllamaModel(base_url=base_url or "", model=name, timeout_seconds=settings.llm_timeout_seconds)
    if kind == "anthropic":
        return AnthropicModel(
            model=name, api_key=settings.anthropic_api_key, timeout_seconds=settings.llm_timeout_seconds
        )
    api_key = {
        "openrouter": settings.openrouter_api_key,
        "openai": settings.openai_api_key,
        "openai_compatible": settings.llm_api_key,
    }[kind]
    return OpenAICompatibleModel(
        kind=kind,
        base_url=base_url or "",
        model=name,
        api_key=api_key,
        fallback_models=fallbacks if kind == "openrouter" else (),
        require_free=settings.require_free_models,
        timeout_seconds=settings.llm_timeout_seconds,
        local=kind == "openai_compatible" and is_local_url(base_url or "", settings.local_allowed_hosts),
    )


def budgeted(model: ChatModel, settings: Settings, *, tag: str) -> ChatModel:
    """Wrap a cloud model for evaluation runs: disk cache, throttle, retries, call budget and ledger."""
    if model.is_local and model.label.split("/", 1)[0] not in CLOUD_PROVIDERS:
        return model
    return BudgetedModel(
        model,
        ledger=CallLedger(settings.llm_ledger, settings.llm_max_calls),
        cache=DiskCache(settings.llm_cache_dir),
        throttle=Throttle(settings.llm_min_seconds_between_requests),
        max_retries=settings.llm_max_retries,
        tag=tag,
    )
