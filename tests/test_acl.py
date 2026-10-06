from __future__ import annotations

from pathlib import Path

import pytest

from clearance.acl import (
    AccessRule,
    AclError,
    DocumentAcl,
    SectionRule,
    can_read,
    document_acl_for,
    normalize_principal,
    normalize_principals,
    parse_acl_spec,
)
from tests.conftest import CORPUS

ALICE = ["user:alice@x.test", "group:finance", "group:all-employees"]
BOB = ["user:bob@x.test", "group:contractors", "group:engineering"]


def test_principals_are_validated_and_normalized() -> None:
    assert normalize_principal(" USER:Alice@X.test ") == "user:alice@x.test"
    assert normalize_principal("group:finance") == "group:finance"
    assert normalize_principals(["group:b", "group:a", "group:b"]) == ("group:a", "group:b")
    for bad in ("alice", "user:alice", "group:", "role:admin", "group:has space", "user:a@b,c"):
        with pytest.raises(AclError):
            normalize_principal(bad)


def test_deny_wins_over_allow() -> None:
    assert can_read(BOB, ["group:engineering"], [])
    assert not can_read(BOB, ["group:engineering"], ["group:contractors"])
    assert not can_read(BOB, ["user:bob@x.test"], ["user:bob@x.test"])


def test_empty_allow_list_means_nobody() -> None:
    assert not can_read(ALICE, [], [])
    assert not AccessRule().permits(ALICE)


def test_section_override_replaces_allow_and_accumulates_deny() -> None:
    acl = DocumentAcl.of(
        ["group:engineering"],
        ["group:contractors"],
        [SectionRule("Salary bands", ("group:hr", "group:managers"), ("user:carl@x.test",))],
    )
    body = acl.for_section(("Levels",))
    bands = acl.for_section(("Salary bands",))
    assert body.permits(["user:dan@x.test", "group:engineering"])
    assert not bands.permits(["user:dan@x.test", "group:engineering"])  # engineers lose the restricted section
    assert bands.permits(["user:erin@x.test", "group:managers"])
    assert not bands.permits(["user:carl@x.test", "group:hr"])  # section deny
    assert not bands.permits(["user:x@x.test", "group:managers", "group:contractors"])  # document deny still applies


def test_section_override_applies_to_subsections_and_is_case_insensitive() -> None:
    acl = DocumentAcl.of(["group:all"], [], [SectionRule("Executive  BENEFITS", ("group:leadership",))])
    assert acl.for_section(("Executive benefits", "Car allowance")).allow == ("group:leadership",)
    assert acl.for_section(("Health insurance",)).allow == ("group:all",)
    assert acl.for_section(()).allow == ("group:all",)


def test_deepest_section_override_wins() -> None:
    acl = DocumentAcl.of(["group:all"], [], [SectionRule("Outer", ("group:a",)), SectionRule("Inner", ("group:b",))])
    assert acl.for_section(("Outer",)).allow == ("group:a",)
    assert acl.for_section(("Outer", "Inner")).allow == ("group:b",)


def test_readable_by_counts_partial_access() -> None:
    acl = DocumentAcl.of(["group:finance"], [], [SectionRule("Board", ("group:leadership",))])
    assert acl.readable_by(["group:leadership"])  # only the section, but that is still part of the document
    assert acl.readable_by(["group:finance"])
    assert not acl.readable_by(["group:sales"])


def test_json_round_trip() -> None:
    acl = DocumentAcl.of(["group:a"], ["user:b@x.test"], [SectionRule("S", ("group:c",), ("group:d",))])
    assert DocumentAcl.from_json(acl.to_json()) == acl


def test_sidecar_validation_fails_loudly() -> None:
    with pytest.raises(AclError, match="unknown keys"):
        parse_acl_spec({"allow": ["group:a"], "readers": ["group:b"]})
    with pytest.raises(AclError, match="heading"):
        parse_acl_spec({"sections": [{"allow": ["group:a"]}]})
    with pytest.raises(AclError, match="non-empty allow"):
        parse_acl_spec({"sections": [{"heading": "X", "allow": []}]})
    with pytest.raises(AclError, match="invalid principal"):
        parse_acl_spec({"allow": ["finance"]})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_folder_inheritance_down_the_tree(tmp_path: Path) -> None:
    _write(tmp_path / "_folder.acl.yaml", "allow: [group:all-employees]\ndeny: [group:contractors]\n")
    _write(tmp_path / "hr" / "_folder.acl.yaml", "allow: [group:hr]\n")
    _write(tmp_path / "hr" / "cases" / "_folder.acl.yaml", "inherit: false\nallow: [group:hr-cases]\n")
    for name in ("a.md", "hr/b.md", "hr/cases/c.md", "hr/d.md"):
        _write(tmp_path / name, "# T\n\ntext\n")
    _write(tmp_path / "hr" / "d.md.acl.yaml", "inherit: false\nallow: [user:carol@x.test]\n")

    assert document_acl_for(tmp_path / "a.md", tmp_path).allow == ("group:all-employees",)
    hr = document_acl_for(tmp_path / "hr" / "b.md", tmp_path)
    assert hr.allow == ("group:all-employees", "group:hr") and hr.deny == ("group:contractors",)
    cases = document_acl_for(tmp_path / "hr" / "cases" / "c.md", tmp_path)
    assert cases.allow == ("group:hr-cases",) and cases.deny == ()  # folder broke inheritance
    own = document_acl_for(tmp_path / "hr" / "d.md", tmp_path)
    assert own.allow == ("user:carol@x.test",) and own.deny == ()


def test_demo_corpus_acls_resolve() -> None:
    ladder = document_acl_for(CORPUS / "engineering" / "engineering-career-ladder.md", CORPUS)
    assert ladder.allow == ("group:engineering",)
    assert ladder.deny == ("group:contractors",)
    assert ladder.for_section(("Salary bands",)).allow == ("group:hr", "group:managers")
    reorg = document_acl_for(CORPUS / "leadership" / "reorg-plan-operation-driftwood.md", CORPUS)
    assert not reorg.for_section(()).permits(["user:erin.walsh@fernhill.test", "group:leadership"])
    assert reorg.for_section(()).permits(["user:carol.diaz@fernhill.test", "group:hr"])
