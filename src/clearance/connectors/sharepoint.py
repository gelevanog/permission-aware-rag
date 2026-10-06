"""Microsoft SharePoint / OneDrive connector over Microsoft Graph: documents and permissions via delta queries.

API shapes used (Graph v1.0):

* ``GET /sites/{site-id}/drive`` to find the document library's drive;
* ``GET /drives/{drive-id}/root/delta`` (then ``@odata.nextLink`` pages and finally an ``@odata.deltaLink``, the
  cursor for the next incremental sync). Deleted items come back with a ``deleted`` facet;
* ``GET /drives/{drive-id}/items/{item-id}/content`` (a 302 to a pre-authenticated download URL);
* ``GET /drives/{drive-id}/items/{item-id}/permissions``: ``grantedToV2`` / ``grantedToIdentitiesV2`` with
  ``user``, ``group`` or ``siteGroup`` identities, and sharing ``link`` permissions with a ``scope`` of
  ``anonymous``, ``organization`` or ``users``. Inherited permissions are listed too (``inheritedFrom``), so the
  result is the item's effective ACL.

Grantee mapping (``GroupMapping``): users by email; Entra groups by object id (``aad_group_ids``) or email;
SharePoint site groups by display name (``idp_groups``); ``organization`` links -> the principal mapped to
``organization_domain``; ``anonymous`` links -> the ``anyone`` principal (unset = nobody). Unmappable grantees are
dropped (fail closed). Graph exposes no deny entries for drive items.

A delta change does not always mean new content: Graph reports permission changes as item changes, and the
indexer compares content hashes, so a sharing change rewrites ACL rows without re-embedding.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from clearance.acl import DocumentAcl
from clearance.auth.mapping import GroupMapping
from clearance.connectors.oauth import TokenProvider
from clearance.index import SourceDocument
from clearance.logging_config import get_logger

log = get_logger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SUPPORTED_SUFFIXES = (".md", ".txt", ".docx")
READ_ROLES = {"read", "write", "owner", "sp.full control", "sp.edit", "sp.view"}


@dataclass
class DeltaBatch:
    upserts: list[SourceDocument] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cursor: str = ""


class SharePointConnector:
    source = "sharepoint"

    def __init__(
        self,
        *,
        tokens: TokenProvider,
        mapping: GroupMapping,
        site_id: str | None = None,
        drive_id: str | None = None,
        organization_domain: str | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        if not (site_id or drive_id):
            raise ValueError("SharePoint connector needs a site id or a drive id")
        self.tokens = tokens
        self.mapping = mapping
        self.site_id = site_id
        self._drive_id = drive_id
        self.organization_domain = organization_domain
        self.http = http or httpx.Client(timeout=60, follow_redirects=True)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        full = url if url.startswith("https://") else f"{GRAPH}{url}"
        response = self.http.get(full, params=params, headers={"Authorization": f"Bearer {self.tokens.token()}"})
        response.raise_for_status()
        return response

    @property
    def drive_id(self) -> str:
        if self._drive_id is None:
            self._drive_id = str(self._get(f"/sites/{self.site_id}/drive").json()["id"])
        return self._drive_id

    # ---- delta ------------------------------------------------------------------------------------------
    def delta(self, cursor: str | None = None) -> DeltaBatch:
        """All changes since ``cursor`` (a deltaLink); without a cursor, every item in the library."""
        batch = DeltaBatch()
        url: str | None = cursor or f"/drives/{self.drive_id}/root/delta"
        while url:
            page = self._get(url).json()
            for item in page.get("value") or []:
                if item.get("deleted") is not None:
                    batch.removed.append(str(item["id"]))
                    continue
                if "file" not in item or not str(item.get("name", "")).lower().endswith(SUPPORTED_SUFFIXES):
                    continue
                batch.upserts.append(self.fetch(item))
            url = page.get("@odata.nextLink")
            if page.get("@odata.deltaLink"):
                batch.cursor = str(page["@odata.deltaLink"])
        return batch

    def documents(self) -> Iterator[SourceDocument]:
        yield from self.delta().upserts

    # ---- one item ---------------------------------------------------------------------------------------
    def fetch(self, item: dict[str, Any]) -> SourceDocument:
        item_id = str(item["id"])
        content = self._get(f"/drives/{self.drive_id}/items/{item_id}/content").content
        parent = str((item.get("parentReference") or {}).get("path") or "")
        path = parent.split("root:", 1)[-1].strip("/") if "root:" in parent else ""
        name = str(item["name"])
        return SourceDocument(
            source=self.source,
            external_id=item_id,
            filename=name,
            content=content,
            acl=self.acl_for(item_id),
            path=path,
            mime_type=str((item.get("file") or {}).get("mimeType") or "") or None,
            title=name.rsplit(".", 1)[0],
            source_url=item.get("webUrl"),
        )

    def acl_for(self, item_id: str) -> DocumentAcl:
        allow: list[str] = []
        url: str | None = f"/drives/{self.drive_id}/items/{item_id}/permissions"
        while url:
            page = self._get(url).json()
            for permission in page.get("value") or []:
                allow.extend(self.principals_for(permission))
            url = page.get("@odata.nextLink")
        return DocumentAcl.of(allow)

    def principals_for(self, permission: dict[str, Any]) -> list[str]:
        roles = {str(role).lower() for role in permission.get("roles") or []}
        if roles and not roles & READ_ROLES:
            return []
        principals: list[str] = []
        link = permission.get("link")
        if isinstance(link, dict) and link.get("scope") in {"anonymous", "organization"}:
            mapped = (
                self.mapping.anyone
                if link["scope"] == "anonymous"
                else (self.mapping.for_domain(self.organization_domain) if self.organization_domain else None)
            )
            if mapped:
                principals.append(mapped)
            else:
                log.warning("sharepoint.unmapped_link", scope=link["scope"], permission_id=permission.get("id"))
            return principals
        identities = [permission.get("grantedToV2") or {}, *(permission.get("grantedToIdentitiesV2") or [])]
        for identity in identities:
            mapped_identity = self._identity(identity)
            if mapped_identity:
                principals.append(mapped_identity)
        if not principals:
            log.warning("sharepoint.unmapped_grantee", permission_id=permission.get("id"))
        return principals

    def _identity(self, identity: dict[str, Any]) -> str | None:
        user = identity.get("user") or identity.get("siteUser")
        if isinstance(user, dict):
            email = user.get("email") or user.get("loginName")
            if isinstance(email, str) and "@" in email:
                return self.mapping.for_user_email(email.split("|")[-1])
        group = identity.get("group")
        if isinstance(group, dict):
            by_id = self.mapping.for_aad_group(str(group.get("id", "")))
            by_email = self.mapping.for_group_email(str(group.get("email", ""))) if group.get("email") else None
            return by_id or by_email
        site_group = identity.get("siteGroup")
        if isinstance(site_group, dict):
            return self.mapping.idp_groups.get(str(site_group.get("displayName", "")))
        return None
