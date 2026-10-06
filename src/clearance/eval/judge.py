"""LLM judge for answer correctness (against the gold answer) and faithfulness (against the context)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from clearance.eval.dataset import AuthorizedQuestion
from clearance.llm.base import ChatModel, LLMError, Message
from clearance.retrieval.search import RetrievedChunk

JUDGE_SYSTEM = (
    "You grade answers from a company knowledge assistant. You reply with a single JSON object and nothing else."
)

JUDGE_PROMPT = """Question: {question}

Gold answer (written by the evaluator): {gold}

Context passages the assistant was given:
{context}

Assistant's answer:
{answer}

Grade two things.
- correct: true if the answer states the key facts of the gold answer (wording may differ; extra correct detail is
  fine), false if a key fact is missing or wrong, or if the answer says it cannot answer.
- faithful: true if every factual claim in the answer is supported by the context passages, false if it states
  facts that are not in the passages.

Reply with JSON only: {{"correct": true or false, "faithful": true or false, "reason": "<one short sentence>"}}"""

_JSON = re.compile(r"\{[^{}]*\"correct\"[^{}]*\}", re.S)


def parse_verdict(text: str) -> dict[str, Any]:
    """The last JSON object with a "correct" key (reasoning models sometimes think out loud first)."""
    matches = _JSON.findall(text)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("correct"), bool):
            return {
                "correct": data["correct"],
                "faithful": data.get("faithful") if isinstance(data.get("faithful"), bool) else None,
                "reason": str(data.get("reason", ""))[:300],
            }
    return {"correct": None, "faithful": None, "reason": "unparseable judge reply", "raw": text[:300]}


class Judge:
    def __init__(self, model: ChatModel, *, max_tokens: int = 4000) -> None:
        self.model = model
        self.max_tokens = max_tokens
        """Reasoning models think before the JSON verdict; a small budget ends in an empty answer."""

    @property
    def label(self) -> str:
        return self.model.label

    def messages(self, question: AuthorizedQuestion, answer: str, context: Sequence[RetrievedChunk]) -> list[Message]:
        passages = "\n\n".join(
            f"[{n}] {c.title}{' > ' + c.section if c.section else ''}\n{c.text.strip()}"
            for n, c in enumerate(context, 1)
        )
        prompt = JUDGE_PROMPT.format(
            question=question.question, gold=question.answer, context=passages or "(none)", answer=answer
        )
        return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}]

    def grade(self, question: AuthorizedQuestion, answer: str, context: Sequence[RetrievedChunk]) -> dict[str, Any]:
        try:
            completion = self.model.complete(
                self.messages(question, answer, context), max_tokens=self.max_tokens, temperature=0.0
            )
        except LLMError as exc:
            return {"correct": None, "faithful": None, "reason": f"judge error: {str(exc)[:200]}"}
        verdict = parse_verdict(completion.text)
        verdict["judge_model"] = completion.model
        return verdict
