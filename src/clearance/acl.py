"""Access-control model: principals, document ACLs with deny entries, section overrides and inheritance.

A *principal* is a string: ``user:<email>`` or ``group:<name>``. A reader's principal set is their own user
principal plus the groups their identity provider asserts (mapped by ``clearance.auth.mapping``).

Rules, in order:

1. **Deny wins.** If any of the reader's principals is in the deny list, the reader cannot see the text.
2. **Allow.** Otherwise the reader sees the text if any of their principals is in the allow list.
3. **Nothing by default.** An empty allow list means nobody (fail closed).

A document's ACL is its own allow/deny plus, when ``inherit`` is true, those of its folder (like Google Drive's
and SharePoint's inherited permissions). A *section override* (a ``##`` heading inside the document) replaces
the allow list for that section and its subsections, so a team-wide document can carry a section only HR may
read; deny entries always accumulate. Chunks never span two sections, so every chunk has exactly one
effective ACL, which is what the database stores and filters on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PRINCIPAL_RE = re.compile(r"^(user:[^\s,]+@[^\s,]+|group:[a-z0-9][a-z0-9._:@-]*)$")


class AclError(ValueError):
    """An ACL file or principal string is malformed."""


def normalize_principal(value: str) -> str:
    principal = value.strip()
    kind, _, name = principal.partition(":")
    principal = f"{kind.lower()}:{name.lower() if kind.lower() == 'user' else name}"
    if not PRINCIPAL_RE.match(principal):
        raise AclError(f"invalid principal {value!r} (expected user:<email> or group:<name>)")
    return principal


def normalize_principals(values: Iterable[str]) -> tuple[str, ...]:
    """Sorted, de-duplicated, validated principals (the canonical form stored in the database)."""
    return tuple(sorted({normalize_principal(value) for value in values}))


def user_principal(email: str) -> str:
    return normalize_principal(f"user:{email}")


def can_read(principals: Iterable[str], allow: Iterable[str], deny: Iterable[str]) -> bool:
    """The single access rule, shared by ingestion, the leak-test oracle and the property tests."""
    reader = set(principals)
    if reader & set(deny):
        return False
    return bool(reader & set(allow))


@dataclass(frozen=True)
class AccessRule:
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    @classmethod
    def of(cls, allow: Iterable[str] = (), deny: Iterable[str] = ()) -> AccessRule:
        return cls(normalize_principals(allow), normalize_principals(deny))

    def permits(self, principals: Iterable[str]) -> bool:
        return can_read(principals, self.allow, self.deny)

    def merged(self, other: AccessRule) -> AccessRule:
        return AccessRule.of([*self.allow, *other.allow], [*self.deny, *other.deny])


@dataclass(frozen=True)
class SectionRule:
    """Replaces the allow list for one ``##`` section (matched case-insensitively) and its subsections."""

    heading: str
    allow: tuple[str, ...]
    deny: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return section_key(self.heading)


def section_key(heading: str) -> str:
    return " ".join(heading.strip().lower().split())


@dataclass(frozen=True)
class DocumentAcl:
    """The effective ACL of one document (inheritance already resolved)."""

    allow: tuple[str, ...]
    deny: tuple[str, ...] = ()
    sections: tuple[SectionRule, ...] = ()

    @classmethod
    def of(
        cls, allow: Iterable[str] = (), deny: Iterable[str] = (), sections: Iterable[SectionRule] = ()
    ) -> DocumentAcl:
        return cls(normalize_principals(allow), normalize_principals(deny), tuple(sections))

    def for_section(self, section_path: Sequence[str]) -> AccessRule:
        """Effective rule for a chunk under ``section_path`` (headings from the top level down).

        The deepest matching override wins for the allow list; deny entries of the document and of every
        matching override accumulate.
        """
        allow = self.allow
        deny = set(self.deny)
        keys = [section_key(heading) for heading in section_path]
        for rule in self.sections:
            if rule.key in keys:
                deny.update(rule.deny)
        for heading in keys:  # top-down, so the deepest override is applied last
            for rule in self.sections:
                if rule.key == heading:
                    allow = rule.allow
        return AccessRule(tuple(sorted(set(allow))), tuple(sorted(deny)))

    def readable_by(self, principals: Iterable[str]) -> bool:
        """True if the reader can see at least part of the document."""
        reader = set(principals)
        if AccessRule(self.allow, self.deny).permits(reader):
            return True
        return any(AccessRule(rule.allow, tuple({*self.deny, *rule.deny})).permits(reader) for rule in self.sections)

    def to_json(self) -> dict[str, Any]:
        return {
            "allow": list(self.allow),
            "deny": list(self.deny),
            "sections": [{"heading": r.heading, "allow": list(r.allow), "deny": list(r.deny)} for r in self.sections],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DocumentAcl:
        sections = [
            SectionRule(
                heading=str(item["heading"]),
                allow=normalize_principals(item.get("allow") or []),
                deny=normalize_principals(item.get("deny") or []),
            )
            for item in data.get("sections") or []
        ]
        return cls.of(data.get("allow") or [], data.get("deny") or [], sections)


# ---------------------------------------------------------------------------------------------------------
# YAML sidecars: `_folder.acl.yaml` in a folder, `<file>.acl.yaml` next to a document
# ---------------------------------------------------------------------------------------------------------

FOLDER_ACL = "_folder.acl.yaml"
SIDECAR_SUFFIX = ".acl.yaml"
_ALLOWED_KEYS = {"inherit", "allow", "deny", "sections", "owner"}


@dataclass(frozen=True)
class AclSpec:
    """An ACL as written in a sidecar, before inheritance."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    inherit: bool = True
    sections: tuple[SectionRule, ...] = ()
    owner: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def parse_acl_spec(data: Mapping[str, Any] | None, *, source: str = "<acl>") -> AclSpec:
    if data is None:
        return AclSpec()
    if not isinstance(data, Mapping):
        raise AclError(f"{source}: expected a mapping")
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise AclError(f"{source}: unknown keys {sorted(unknown)}")
    sections: list[SectionRule] = []
    for item in data.get("sections") or []:
        if not isinstance(item, Mapping) or not item.get("heading"):
            raise AclError(f"{source}: every section override needs a heading")
        if not item.get("allow"):
            raise AclError(f"{source}: section {item['heading']!r} needs a non-empty allow list")
        sections.append(
            SectionRule(
                heading=str(item["heading"]),
                allow=normalize_principals(item.get("allow") or []),
                deny=normalize_principals(item.get("deny") or []),
            )
        )
    try:
        return AclSpec(
            allow=normalize_principals(data.get("allow") or []),
            deny=normalize_principals(data.get("deny") or []),
            inherit=bool(data.get("inherit", True)),
            sections=tuple(sections),
            owner=normalize_principal(data["owner"]) if data.get("owner") else None,
        )
    except AclError as exc:
        raise AclError(f"{source}: {exc}") from exc


def load_acl_file(path: Path) -> AclSpec:
    if not path.exists():
        return AclSpec(inherit=True)
    return parse_acl_spec(yaml.safe_load(path.read_text(encoding="utf-8")), source=str(path))


def resolve(folder_rule: AccessRule, spec: AclSpec) -> DocumentAcl:
    """Apply inheritance: the folder's allow/deny are added unless the document says ``inherit: false``."""
    allow = [*spec.allow, *(folder_rule.allow if spec.inherit else ())]
    deny = [*spec.deny, *(folder_rule.deny if spec.inherit else ())]
    return DocumentAcl.of(allow, deny, spec.sections)


def folder_rule_for(document: Path, root: Path) -> AccessRule:
    """Folder ACLs inherit down the tree: each `_folder.acl.yaml` from the root to the document's folder."""
    rule = AccessRule()
    relative = document.parent.relative_to(root)
    folders = [root, *(root.joinpath(*relative.parts[: index + 1]) for index in range(len(relative.parts)))]
    for folder in folders:
        spec = load_acl_file(folder / FOLDER_ACL)
        own = AccessRule.of(spec.allow, spec.deny)
        rule = rule.merged(own) if spec.inherit else own
    return rule


def document_acl_for(document: Path, root: Path) -> DocumentAcl:
    """Effective ACL of a file in a local folder tree: folder sidecars, then the file's own sidecar."""
    spec = load_acl_file(document.with_name(document.name + SIDECAR_SUFFIX))
    return resolve(folder_rule_for(document, root), spec)
