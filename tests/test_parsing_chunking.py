from __future__ import annotations

import io
import zipfile

import pytest

from clearance.ingest.chunking import chunk_document
from clearance.ingest.parsing import UnsupportedFormatError, parse_file, parse_markdown

MD = """# Benefits Overview

Intro paragraph about benefits.

## Health insurance

Cigna in the US.

### Dental

Dental is included.

## Executive benefits

An executive car allowance.

```
## not a heading inside code
```
"""


def test_markdown_title_and_section_paths() -> None:
    parsed = parse_markdown(MD)
    assert parsed.title == "Benefits Overview"
    paths = [section.path for section in parsed.sections]
    assert paths == [(), ("Health insurance",), ("Health insurance", "Dental"), ("Executive benefits",)]
    assert "## not a heading" in parsed.sections[-1].text  # headings inside code fences are text


def test_chunks_never_cross_sections() -> None:
    chunks = chunk_document(parse_markdown(MD))
    assert {chunk.section_path for chunk in chunks} == {
        (),
        ("Health insurance",),
        ("Health insurance", "Dental"),
        ("Executive benefits",),
    }
    executive = [c for c in chunks if c.section_path == ("Executive benefits",)]
    assert len(executive) == 1 and "car allowance" in executive[0].text
    assert all("car allowance" not in c.text for c in chunks if c.section_path != ("Executive benefits",))


def test_long_sections_split_on_paragraphs_with_overlap() -> None:
    paragraphs = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(8))
    chunks = chunk_document(parse_markdown(f"# T\n\n## Long\n\n{paragraphs}"), max_words=150)
    assert len(chunks) > 2
    assert all(c.section_path == ("Long",) for c in chunks)
    assert all(len(c.text.split()) <= 150 + 70 for c in chunks)
    assert chunks[1].text.split("\n\n")[0] == chunks[0].text.split("\n\n")[-1]  # one-paragraph overlap


def test_embedding_text_carries_title_and_section() -> None:
    chunk = chunk_document(parse_markdown(MD))[1]
    assert chunk.embedding_text("Benefits Overview").startswith("Benefits Overview > Health insurance\n")


def _docx(paragraphs: list[tuple[str, str]]) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'
        if style
        else f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for style, text in paragraphs
    )
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_docx_headings_become_sections() -> None:
    data = _docx([("Title", "Board Pack"), ("", "Summary text."), ("Heading2", "Cash"), ("", "Runway is long.")])
    parsed = parse_file(data, filename="board.docx")
    assert parsed.title == "Board Pack"
    assert [s.path for s in parsed.sections] == [(), ("Cash",)]


def test_unsupported_formats_are_refused() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_file(b"%PDF-1.7", filename="scan.pdf", mime_type="application/pdf")
    with pytest.raises(UnsupportedFormatError):
        parse_file(b"not a zip", filename="broken.docx")


def test_fallback_title_from_filename() -> None:
    assert parse_file(b"no heading here", filename="travel-policy.md").title == "Travel policy"
