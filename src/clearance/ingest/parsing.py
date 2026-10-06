"""Turn source files into a title and heading-delimited sections.

Supported: Markdown, plain text, Google Docs exported as Markdown, and .docx (headings from Word's Heading styles).
Sections matter for permissions: a section override in an ACL applies to one heading and its subsections, so the
parser keeps the full heading path of every block of text and the chunker never lets a chunk cross a heading.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]
    """Headings from the top level (``##``) down; empty for text before the first heading."""
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    sections: tuple[Section, ...]

    @property
    def headings(self) -> set[str]:
        return {heading for section in self.sections for heading in section.path}


class UnsupportedFormatError(ValueError):
    pass


def parse_markdown(text: str, fallback_title: str = "Untitled") -> ParsedDocument:
    """Split Markdown on headings. The first ``#`` heading is the title; ``##`` and deeper form section paths."""
    title: str | None = None
    path: list[tuple[int, str]] = []
    sections: list[Section] = []
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(Section(tuple(heading for _, heading in path), body))
        buffer.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match is None:
            buffer.append(line)
            continue
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1 and title is None and not sections and not "".join(buffer).strip():
            title = heading
            continue
        flush()
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, heading))
    flush()
    return ParsedDocument(title=title or fallback_title, sections=tuple(sections))


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_markdown(data: bytes) -> str:
    """Minimal .docx reader: paragraphs in order, Word heading styles become Markdown headings."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnsupportedFormatError("not a valid .docx file") from exc
    root = ElementTree.fromstring(xml)
    lines: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_W}t")).strip()
        if not text:
            continue
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        style_name = (style.get(f"{_W}val") or "") if style is not None else ""
        level_match = re.match(r"(?i)^(title|heading\s*([1-6]))$", style_name)
        if level_match:
            level = 1 if level_match.group(1).lower() == "title" else int(level_match.group(2))
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_markdown(data: bytes, *, filename: str, mime_type: str | None = None) -> str:
    """Text content of a supported file as Markdown."""
    lower = filename.lower()
    if (
        lower.endswith(".docx")
        or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return docx_to_markdown(data)
    if lower.endswith((".md", ".markdown", ".txt")) or (mime_type or "").startswith(("text/", "application/json")):
        return data.decode("utf-8", errors="replace")
    raise UnsupportedFormatError(f"unsupported file type: {filename} ({mime_type or 'unknown type'})")


def parse_file(data: bytes, *, filename: str, mime_type: str | None = None) -> ParsedDocument:
    stem = re.sub(r"[-_]+", " ", filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]).strip().capitalize()
    return parse_markdown(to_markdown(data, filename=filename, mime_type=mime_type), fallback_title=stem or "Untitled")
