"""Evaluation data: questions, canaries, and a ground-truth permission oracle computed from the corpus files.

The oracle re-reads the YAML sidecars and re-chunks the Markdown with the same rules as ingestion, but never looks at
the database: "was this chunk allowed for this user?" is answered from the source of truth, independently of the
SQL filter, the row-level security policies and the ``chunk_acl`` rows under test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clearance.acl import DocumentAcl, document_acl_for
from clearance.connectors.local import iter_folder
from clearance.ingest.chunking import chunk_document
from clearance.ingest.parsing import parse_file


@dataclass(frozen=True)
class Canary:
    id: str
    fact: str
    match: tuple[str, ...]

    def found_in(self, text: str) -> bool:
        return any(_contains(text, variant) for variant in self.match)


def _contains(text: str, variant: str) -> bool:
    """Case-insensitive; a variant that starts or ends with a digit must not be part of a longer number."""
    pattern = re.escape(variant.lower())
    if variant[:1].isdigit():
        pattern = r"(?<![\d.,])" + pattern
    if variant[-1:].isdigit():
        pattern = pattern + r"(?![\d]|[.,]\d)"
    return re.search(pattern, text.lower()) is not None


@dataclass(frozen=True)
class AuthorizedQuestion:
    id: str
    user: str
    question: str
    answer: str | None
    docs: tuple[str, ...]
    expect: tuple[str, ...] = ()

    @property
    def answerable(self) -> bool:
        return bool(self.docs)

    def expect_met(self, text: str) -> bool:
        lowered = text.lower()
        return all(any(option.lower() in lowered for option in fact.split("|")) for fact in self.expect)


@dataclass(frozen=True)
class AdversarialQuestion:
    id: str
    question: str
    style: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionSet:
    authorized: tuple[AuthorizedQuestion, ...]
    adversarial: tuple[AdversarialQuestion, ...]


def email(user: str, domain: str = "fernhill.test") -> str:
    return user if "@" in user else f"{user}@{domain}"


def load_questions(path: Path, domain: str = "fernhill.test") -> QuestionSet:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    authorized = tuple(
        AuthorizedQuestion(
            id=str(item["id"]),
            user=email(str(item["user"]), domain),
            question=str(item["question"]),
            answer=item.get("answer"),
            docs=tuple(item.get("docs") or ()),
            expect=tuple(str(x) for x in item.get("expect") or ()),
        )
        for item in data["authorized"]
    )
    adversarial = tuple(
        AdversarialQuestion(
            id=str(item["id"]),
            question=str(item["question"]),
            style=str(item.get("style", "")),
            targets=tuple(item.get("targets") or ()),
        )
        for item in data["adversarial"]
    )
    return QuestionSet(authorized, adversarial)


def load_canaries(path: Path) -> tuple[Canary, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(
        Canary(id=str(item["id"]), fact=str(item.get("fact", "")), match=tuple(str(m) for m in item["match"]))
        for item in data["canaries"]
    )


@dataclass(frozen=True)
class OracleChunk:
    external_id: str
    section_path: tuple[str, ...]
    text: str


@dataclass
class CorpusOracle:
    """Ground truth from the files: document ACLs, chunks and where every canary lives."""

    acls: dict[str, DocumentAcl]
    chunks: list[OracleChunk]
    canaries: tuple[Canary, ...] = ()
    _canary_chunks: dict[str, list[OracleChunk]] = field(default_factory=dict)

    @classmethod
    def build(cls, corpus_dir: Path, canaries: Sequence[Canary] = ()) -> CorpusOracle:
        root = corpus_dir.resolve()
        acls: dict[str, DocumentAcl] = {}
        chunks: list[OracleChunk] = []
        for doc in iter_folder(root):
            acls[doc.external_id] = document_acl_for(root / doc.external_id, root)
            parsed = parse_file(doc.content, filename=doc.filename, mime_type=doc.mime_type)
            chunks.extend(
                OracleChunk(doc.external_id, chunk.section_path, chunk.text) for chunk in chunk_document(parsed)
            )
        oracle = cls(acls=acls, chunks=chunks, canaries=tuple(canaries))
        for canary in canaries:
            oracle._canary_chunks[canary.id] = [c for c in chunks if canary.found_in(c.text)]
        return oracle

    def can_read(self, principals: Iterable[str], external_id: str, section_path: Sequence[str]) -> bool:
        acl = self.acls.get(external_id)
        return acl is not None and acl.for_section(tuple(section_path)).permits(principals)

    def can_read_document_fully(self, principals: Iterable[str], external_id: str) -> bool:
        reader = list(principals)
        return all(
            self.can_read(reader, c.external_id, c.section_path) for c in self.chunks if c.external_id == external_id
        )

    def can_read_any(self, principals: Iterable[str], external_id: str) -> bool:
        acl = self.acls.get(external_id)
        return acl is not None and acl.readable_by(principals)

    def visible_canaries(self, principals: Iterable[str]) -> set[str]:
        reader = list(principals)
        return {
            canary_id
            for canary_id, located in self._canary_chunks.items()
            if any(self.can_read(reader, c.external_id, c.section_path) for c in located)
        }

    def hidden_canaries(self, principals: Iterable[str]) -> list[Canary]:
        visible = self.visible_canaries(principals)
        return [canary for canary in self.canaries if canary.id not in visible]

    def canary_locations(self) -> dict[str, list[str]]:
        return {cid: sorted({c.external_id for c in located}) for cid, located in self._canary_chunks.items()}
