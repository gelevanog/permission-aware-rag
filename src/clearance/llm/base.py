"""Chat-model interface shared by the local, OpenAI-compatible, OpenRouter and Anthropic providers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    """The model that actually answered (OpenRouter may route to a fallback)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    extra: dict[str, object] = field(default_factory=dict)


class LLMError(RuntimeError):
    """The model request failed and should not be retried."""


class RetryableLLMError(LLMError):
    """Rate limit, overload, timeout or an empty answer: worth retrying with backoff."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMUnavailableError(LLMError):
    """The model server cannot be reached (e.g. local Ollama not running)."""


class PolicyViolationError(LLMError):
    """A guard refused the request: cloud call while local-only, or a non-free OpenRouter model."""


class BudgetExceededError(LLMError):
    pass


class ChatModel(Protocol):
    @property
    def label(self) -> str:
        """Provider and model, e.g. "ollama/qwen3.5:4b"."""
        ...

    @property
    def is_local(self) -> bool:
        """True when no text leaves this machine or private network."""
        ...

    def complete(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Completion: ...

    def stream(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Iterator[str]: ...
