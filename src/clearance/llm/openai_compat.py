"""OpenAI-compatible chat completions over HTTP: vLLM, LM Studio, llama.cpp server, Ollama's /v1, OpenAI, OpenRouter."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any, Literal

import httpx

from clearance.llm.base import Completion, LLMError, LLMUnavailableError, Message, RetryableLLMError
from clearance.llm.guards import ensure_free_models, ensure_served_free

Kind = Literal["openai_compatible", "openrouter", "openai"]

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/gelevanog/permission-aware-rag",
    "X-Title": "Clearance",
}


class OpenAICompatibleModel:
    def __init__(
        self,
        *,
        kind: Kind,
        base_url: str,
        model: str,
        api_key: str | None = None,
        fallback_models: Sequence[str] = (),
        require_free: bool = True,
        timeout_seconds: float = 180.0,
        local: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if kind in {"openrouter", "openai"} and not api_key:
            raise LLMError(f"{'OPENROUTER' if kind == 'openrouter' else 'OPENAI'}_API_KEY is not set")
        self.kind = kind
        self.model = model
        self.fallback_models = list(fallback_models)
        self.require_free = require_free and kind == "openrouter"
        if self.require_free:
            ensure_free_models([model, *self.fallback_models])
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if kind == "openrouter":
            self._headers.update(OPENROUTER_HEADERS)
        self._timeout = timeout_seconds
        self._transport = transport
        self._local = local

    @property
    def label(self) -> str:
        return f"{self.kind}/{self.model}"

    @property
    def is_local(self) -> bool:
        return self._local

    def body(self, messages: Sequence[Message], *, max_tokens: int, temperature: float, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if self.kind == "openrouter":
            if self.fallback_models:
                body["models"] = [self.model, *self.fallback_models]
            if self.require_free:
                ensure_free_models([body["model"], *body.get("models", [])])
        return body

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def complete(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Completion:
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, stream=False)
        try:
            with self._client() as client:
                response = client.post(self._url, json=body, headers=self._headers)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"cannot reach {self._url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise RetryableLLMError(f"connection error: {exc}") from exc
        data = _json_or_error(response)
        served = data.get("model")
        if self.require_free:
            ensure_served_free(served if isinstance(served, str) else None)
        choices = data.get("choices") or []
        if not choices:
            raise RetryableLLMError("no choices in the response")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            if choices[0].get("finish_reason") == "length":
                raise LLMError("empty answer: max_tokens reached before any output")
            raise RetryableLLMError(f"empty answer (finish_reason={choices[0].get('finish_reason')})")
        usage = data.get("usage") or {}
        return Completion(
            text=str(content),
            model=str(served or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    def stream(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Iterator[str]:
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, stream=True)
        try:
            with (
                self._client() as client,
                client.stream("POST", self._url, json=body, headers=self._headers) as response,
            ):
                if response.status_code >= 400:
                    response.read()
                    _json_or_error(response)
                checked = False
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    if "error" in chunk:
                        raise LLMError(f"stream error: {_error_message(chunk)}")
                    if not checked and self.require_free and chunk.get("model"):
                        ensure_served_free(str(chunk["model"]))
                        checked = True
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield str(piece)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"cannot reach {self._url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"timeout: {exc}") from exc


def _error_message(data: dict[str, Any]) -> str:
    error: Any = data.get("error", data)
    if isinstance(error, dict):
        metadata = error.get("metadata")
        raw = metadata.get("raw") if isinstance(metadata, dict) else None
        return str(raw or error.get("message") or error)[:300]
    return str(error)[:300]


def _json_or_error(response: httpx.Response) -> dict[str, Any]:
    status = response.status_code
    try:
        data = response.json()
    except ValueError:
        data = {"error": {"message": response.text[:300]}}
    if not isinstance(data, dict):
        data = {"error": {"message": str(data)[:300]}}
    error = data.get("error")
    if isinstance(error, dict) and status < 400:  # OpenRouter reports some upstream failures inside a 200
        code = error.get("code")
        status = code if isinstance(code, int) and code >= 400 else 502
    if status < 400:
        return data
    message = _error_message(data)
    if status == 429:
        retry_after = response.headers.get("retry-after")
        try:
            delay = float(retry_after) if retry_after else None
        except ValueError:
            delay = None
        raise RetryableLLMError(f"rate limited: {message}", retry_after=delay)
    if status >= 500 or status in {408, 409}:
        raise RetryableLLMError(f"upstream {status}: {message}")
    raise LLMError(f"upstream {status}: {message}")
