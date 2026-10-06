"""Section-bounded chunking.

A chunk never spans two sections, so a restricted section can never share a chunk (and therefore an embedding
and an ACL row) with text that more people may read. Long sections are split on paragraph boundaries with a
one-paragraph overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

from clearance.ingest.parsing import ParsedDocument


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    section_path: tuple[str, ...]
    text: str

    @property
    def section(self) -> str:
        return " > ".join(self.section_path)

    def embedding_text(self, title: str) -> str:
        """What the embedder sees: title and heading path give short chunks their context."""
        heading = f"{title} > {self.section}" if self.section_path else title
        return f"{heading}\n{self.text}"


def _words(text: str) -> int:
    return len(text.split())


def chunk_document(document: ParsedDocument, *, max_words: int = 220) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in document.sections:
        paragraphs = [p.strip() for p in section.text.split("\n\n") if p.strip()]
        current: list[str] = []
        for paragraph in paragraphs:
            if current and _words("\n\n".join([*current, paragraph])) > max_words:
                chunks.append(Chunk(len(chunks), section.path, "\n\n".join(current)))
                current = [current[-1]] if _words(current[-1]) < max_words // 2 else []
            current.append(paragraph)
        if current:
            chunks.append(Chunk(len(chunks), section.path, "\n\n".join(current)))
    return chunks
