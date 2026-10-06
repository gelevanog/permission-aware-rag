"""Local folder connector: files plus YAML ACL sidecars.

    company/
      _folder.acl.yaml              allow/deny for everything below (inherited by subfolders)
      hr/
        _folder.acl.yaml
        compensation-review.md
        compensation-review.md.acl.yaml   per-document allow/deny, `inherit: false`, section overrides

A document without any ACL (no folder or sidecar grants) is indexed with an empty allow list: nobody can read
it until an administrator grants access. Fail closed.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import Path

from clearance.acl import FOLDER_ACL, SIDECAR_SUFFIX, document_acl_for
from clearance.index import SourceDocument

SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt", ".docx")


def iter_folder(root: Path, *, source: str = "local") -> Iterator[SourceDocument]:
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == FOLDER_ACL or path.name.endswith(SIDECAR_SUFFIX):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES or path.name.startswith("."):
            continue
        relative = path.relative_to(root)
        yield SourceDocument(
            source=source,
            external_id=relative.as_posix(),
            filename=path.name,
            content=path.read_bytes(),
            acl=document_acl_for(path, root),
            path=relative.parent.as_posix() if relative.parent != Path() else "",
            mime_type=mimetypes.guess_type(path.name)[0] or "text/markdown",
        )
