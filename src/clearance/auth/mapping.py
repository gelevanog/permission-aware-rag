"""Maps identity-provider groups and source-system grantees to Clearance principals.

One mapping file serves both directions of the problem: the groups an employee's token asserts (Okta group names,
Entra ID object ids, Google group emails) and the grantees a connector finds on a document (a Drive permission for
``finance@company.com``, a SharePoint grant to an Entra group id, an organization-wide sharing link). Both must
land on the same principal, or permissions silently stop matching.

    idp_groups:      {"FH-Finance": group:finance}           # token `groups` claim values (Okta, Keycloak, dev IdP)
    aad_group_ids:   {"5b8e...": group:finance}              # Entra ID object ids (token claim and SharePoint grants)
    group_emails:    {"finance@fernhill.test": group:finance} # Google Workspace groups (Drive permissions)
    domains:         {"fernhill.test": group:all-employees}  # Drive "domain" grants, SharePoint organization links
    anyone: null                                              # "anyone with the link": unmapped = nobody (fail closed)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clearance.acl import AclError, normalize_principal
from clearance.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class GroupMapping:
    idp_groups: dict[str, str] = field(default_factory=dict)
    aad_group_ids: dict[str, str] = field(default_factory=dict)
    group_emails: dict[str, str] = field(default_factory=dict)
    domains: dict[str, str] = field(default_factory=dict)
    anyone: str | None = None
    passthrough: bool = False
    """Unmapped token groups become ``group:<value>`` instead of being ignored."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, passthrough: bool = False) -> GroupMapping:
        data = data or {}

        def section(name: str, *, lower_keys: bool = False) -> dict[str, str]:
            raw = data.get(name) or {}
            if not isinstance(raw, Mapping):
                raise AclError(f"group mapping: {name} must be a mapping")
            return {(str(k).lower() if lower_keys else str(k)): normalize_principal(str(v)) for k, v in raw.items()}

        anyone = data.get("anyone")
        return cls(
            idp_groups=section("idp_groups"),
            aad_group_ids=section("aad_group_ids", lower_keys=True),
            group_emails=section("group_emails", lower_keys=True),
            domains=section("domains", lower_keys=True),
            anyone=normalize_principal(str(anyone)) if anyone else None,
            passthrough=passthrough,
        )

    @classmethod
    def load(cls, path: Path | None, *, passthrough: bool = False) -> GroupMapping:
        if path is None or not path.exists():
            return cls(passthrough=passthrough)
        return cls.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")), passthrough=passthrough)

    # ---- tokens ----------------------------------------------------------------------------------------
    def principals_for_claims(self, groups: Iterable[str]) -> tuple[list[str], list[str]]:
        """(principals, unmapped claim values) for the values of a token's groups claim."""
        principals: list[str] = []
        unmapped: list[str] = []
        for value in groups:
            mapped = (
                self.idp_groups.get(value)
                or self.aad_group_ids.get(value.lower())
                or self.group_emails.get(value.lower())
            )
            if mapped:
                principals.append(mapped)
            elif self.passthrough:
                try:
                    principals.append(normalize_principal(f"group:{value.lower().replace(' ', '-')}"))
                except AclError:
                    unmapped.append(value)
            else:
                unmapped.append(value)
        return principals, unmapped

    # ---- connectors ------------------------------------------------------------------------------------
    def for_user_email(self, email: str) -> str:
        return normalize_principal(f"user:{email}")

    def for_group_email(self, email: str) -> str | None:
        return self.group_emails.get(email.lower())

    def for_aad_group(self, group_id: str) -> str | None:
        return self.aad_group_ids.get(group_id.lower())

    def for_domain(self, domain: str) -> str | None:
        return self.domains.get(domain.lower())
