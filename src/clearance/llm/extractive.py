"""Extractive "model": quotes the passage sentences that best match the question, with citations.

Deterministic and dependency-free. It is the fake LLM of the test suite and CI, and the labelled fallback when the
local model server is not running, so the app still answers (by quoting) with zero setup. It reads only the
prompt it is given, exactly like a real model, so it can only quote what the retriever let through.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from clearance.llm.base import Completion, Message

NOT_FOUND = "NOT_FOUND"
_PASSAGE = re.compile(r"^\[(\d+)\][^\n]*\n(.*?)(?=^\[\d+\]|^Question:|\Z)", re.S | re.M)
_WORD = re.compile(r"[a-z0-9€$][a-z0-9,.$€%-]*[a-z0-9%]|[a-z0-9]", re.I)
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "did",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "should",
        "tell",
        "the",
        "their",
        "them",
        "there",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "any",
        "all",
    ]
)


def _terms(text: str) -> set[str]:
    terms = set()
    for word in _WORD.findall(text.lower()):
        word = word.strip(".,")
        if word and word not in _STOP:
            terms.add(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return terms


def extract_answer(prompt: str, *, max_sentences: int = 2) -> str:
    question = prompt.rsplit("Question:", 1)[-1].strip() if "Question:" in prompt else prompt
    wanted = _terms(question)
    if not wanted:
        return NOT_FOUND
    scored: list[tuple[float, int, str]] = []
    for match in _PASSAGE.finditer(prompt):
        number, body = int(match.group(1)), match.group(2)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
            sentence = sentence.strip(" -*#|")
            if len(sentence) < 12:
                continue
            overlap = len(wanted & _terms(sentence))
            if overlap:
                scored.append((overlap / len(wanted) + overlap * 0.01, number, sentence))
    scored.sort(key=lambda item: -item[0])
    if not scored or scored[0][0] < 0.4:
        return NOT_FOUND
    best = [item for item in scored[:max_sentences] if item[0] >= scored[0][0] * 0.75]
    return " ".join(f"{sentence.rstrip('.')} [{number}]." for _, number, sentence in best)


class ExtractiveModel:
    def __init__(self, label: str = "extractive") -> None:
        self._label = label

    @property
    def label(self) -> str:
        return self._label

    @property
    def is_local(self) -> bool:
        return True

    def complete(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Completion:
        prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return Completion(text=extract_answer(prompt), model=self._label)

    def stream(self, messages: Sequence[Message], *, max_tokens: int, temperature: float = 0.0) -> Iterator[str]:
        text = self.complete(messages, max_tokens=max_tokens).text
        for index, word in enumerate(text.split(" ")):
            yield word if index == 0 else " " + word
