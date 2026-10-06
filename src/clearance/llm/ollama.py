"""Ollama's native chat API (local models on CPU or GPU).

The native API, rather than Ollama's OpenAI-compatible /v1, because it can turn off the "thinking" phase of
hybrid reasoning models (Qwen 3.x) with ``think: false``: on a CPU, a few hundred hidden reasoning tokens would
add tens of seconds to every answer. It also sets the context window explicitly (Ollama's default is small
enough to silently truncate a RAG prompt).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from clearance.llm.base import Completion, LLMError, LLMUnavailableError, Message, RetryableLLMError


class OllamaModel:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        num_ctx: int = 4096,
        num_thread: int | None = None,
        keep_alive: str = "30m",
        think: bool = False,
        timeout_seconds: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.num_ctx = num_ctx
        self.num_thread = num_thread
        self.keep_alive = keep_alive
        self.think = think
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def label(self) -> str:
        return f"ollama/{self.model}"

    @property
    def is_local(self) -> bool:
        return True

    def body(self, messages: Sequence[Message], *, max_tokens: int, temperature: float, stream: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens}
        if self.num_thread:
            options["num_thread"] = self.num_thread
        return {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": options,
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def complete(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Completion:
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, stream=False)
        try:
            with self._client() as client:
                response = client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"Ollama is not reachable at {self.base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"Ollama timeout: {exc}") from exc
        data = _checked(response)
        content = str((data.get("message") or {}).get("content") or "")
        if not content.strip():
            raise RetryableLLMError("Ollama returned an empty answer")
        return Completion(
            text=content,
            model=str(data.get("model") or self.model),
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            extra={
                "prompt_eval_ms": round(int(data.get("prompt_eval_duration") or 0) / 1e6),
                "eval_ms": round(int(data.get("eval_duration") or 0) / 1e6),
                "load_ms": round(int(data.get("load_duration") or 0) / 1e6),
            },
        )

    def stream(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Iterator[str]:
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, stream=True)
        try:
            with (
                self._client() as client,
                client.stream("POST", f"{self.base_url}/api/chat", json=body) as response,
            ):
                if response.status_code >= 400:
                    response.read()
                    _checked(response)
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise LLMError(f"Ollama error: {str(chunk['error'])[:300]}")
                    piece = (chunk.get("message") or {}).get("content")
                    if piece:
                        yield str(piece)
                    if chunk.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"Ollama is not reachable at {self.base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"Ollama timeout: {exc}") from exc

    def available(self) -> bool:
        """True if the server is up and has the model (``ollama pull <model>`` otherwise)."""
        try:
            with self._client() as client:
                response = client.get(f"{self.base_url}/api/tags", timeout=3.0)
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        names = {str(item.get("name")) for item in response.json().get("models") or []}
        return self.model in names or f"{self.model}:latest" in names


def _checked(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {"error": response.text[:300]}
    if response.status_code == 404:
        raise LLMUnavailableError(f"Ollama: {data.get('error', 'model not found')} (run `ollama pull <model>`)")
    if response.status_code >= 500:
        raise RetryableLLMError(f"Ollama {response.status_code}: {str(data.get('error'))[:300]}")
    if response.status_code >= 400:
        raise LLMError(f"Ollama {response.status_code}: {str(data.get('error'))[:300]}")
    if not isinstance(data, dict):
        raise LLMError("Ollama returned an unexpected payload")
    return data
