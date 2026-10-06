"""Google Drive connector: documents and their sharing permissions, full and incremental (changes feed) sync.

API shapes used (Drive API v3):

* ``files.list`` (``GET /drive/v3/files?q='<folder>' in parents and trashed=false``) walking a folder tree;
* ``files.export`` (``GET /files/{id}/export?mimeType=text/markdown``) for Google Docs, ``files.get?alt=media``
  for uploaded .md/.txt/.docx files;
* ``permissions.list`` (``GET /files/{id}/permissions``) for the grantees of each file. Drive returns inherited
  permissions on the file itself (``permissionDetails[].inherited``), so the result is the effective ACL;
* ``changes.getStartPageToken`` and ``changes.list`` for incremental sync. A sharing change shows up as a change
  of the file, so a revoked share is picked up by the next sync without re-downloading unchanged content
  (the content hash is unchanged, so only the ACL rows are rewritten).

Grantee mapping (``GroupMapping``): ``user`` -> ``user:<email>``; ``group`` -> the principal mapped to the group
email; ``domain`` -> the principal mapped to the domain; ``anyone`` -> the ``anyone`` principal (unset by default:
"anyone with the link" grants nobody). A grantee that cannot be mapped is dropped, never widened (fail closed).
Drive has no deny entries and no section-level permissions.
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

API = "https://www.googleapis.com/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
GOOGLE_DOC = "application/vnd.google-apps.document"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED = {GOOGLE_DOC, "text/markdown", "text/plain", "text/x-markdown", DOCX}
READ_ROLES = {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}
FILE_FIELDS = "id,name,mimeType,modifiedTime,parents,webViewLink,trashed,owners(emailAddress)"
PERMISSION_FIELDS = "permissions(id,type,role,emailAddress,domain,deleted,permissionDetails),nextPageToken"


@dataclass
class ChangeBatch:
    upserts: list[SourceDocument] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cursor: str = ""


class GoogleDriveConnector:
    source = "gdrive"

    def __init__(
        self,
        *,
        tokens: TokenProvider,
        mapping: GroupMapping,
        root_folder_id: str,
        http: httpx.Client | None = None,
    ) -> None:
        self.tokens = tokens
        self.mapping = mapping
        self.root_folder_id = root_folder_id
        self.http = http or httpx.Client(timeout=60, follow_redirects=True)

    # ---- HTTP ------------------------------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = self.http.get(
            f"{API}{path}", params=params, headers={"Authorization": f"Bearer {self.tokens.token()}"}
        )
        response.raise_for_status()
        return response

    def _paged(self, path: str, params: dict[str, Any], key: str) -> Iterator[dict[str, Any]]:
        token: str | None = None
        while True:
            page = self._get(path, {**params, **({"pageToken": token} if token else {})}).json()
            yield from page.get(key) or []
            token = page.get("nextPageToken")
            if not token:
                return

    # ---- listing ----------------------------------------------------------------------------------------
    def walk(self) -> Iterator[tuple[dict[str, Any], str]]:
        """(file, folder path) for every supported file below the root folder."""
        stack: list[tuple[str, str]] = [(self.root_folder_id, "")]
        while stack:
            folder_id, path = stack.pop()
            params = {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": f"nextPageToken,files({FILE_FIELDS})",
                "pageSize": 100,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            for item in self._paged("/files", params, "files"):
                if item.get("mimeType") == FOLDER:
                    stack.append((item["id"], f"{path}/{item['name']}".strip("/")))
                elif item.get("mimeType") in SUPPORTED or str(item.get("name", "")).endswith((".md", ".txt")):
                    yield item, path

    def documents(self) -> Iterator[SourceDocument]:
        for item, path in self.walk():
            document = self.fetch(item, path)
            if document is not None:
                yield document

    # ---- one file ---------------------------------------------------------------------------------------
    def fetch(self, item: dict[str, Any], path: str = "") -> SourceDocument | None:
        acl = self.acl_for(item["id"])
        mime = str(item.get("mimeType") or "")
        if mime == GOOGLE_DOC:
            content = self._get(f"/files/{item['id']}/export", {"mimeType": "text/markdown"}).content
            filename, content_type = f"{item['name']}.md", "text/markdown"
        else:
            content = self._get(f"/files/{item['id']}", {"alt": "media", "supportsAllDrives": "true"}).content
            filename, content_type = str(item["name"]), mime or None
        owners = item.get("owners") or []
        return SourceDocument(
            source=self.source,
            external_id=str(item["id"]),
            filename=filename,
            content=content,
            acl=acl,
            path=path,
            mime_type=content_type,
            title=str(item["name"]).removesuffix(".md").removesuffix(".txt"),
            owner=f"user:{owners[0]['emailAddress']}" if owners and owners[0].get("emailAddress") else None,
            source_url=item.get("webViewLink"),
        )

    def acl_for(self, file_id: str) -> DocumentAcl:
        params = {"fields": PERMISSION_FIELDS, "supportsAllDrives": "true", "pageSize": 100}
        allow: list[str] = []
        for permission in self._paged(f"/files/{file_id}/permissions", params, "permissions"):
            principal = self.principal_for(permission)
            if principal:
                allow.append(principal)
        return DocumentAcl.of(allow)

    def principal_for(self, permission: dict[str, Any]) -> str | None:
        if permission.get("deleted") or permission.get("role") not in READ_ROLES:
            return None
        kind = permission.get("type")
        principal: str | None = None
        if kind == "user" and permission.get("emailAddress"):
            principal = self.mapping.for_user_email(str(permission["emailAddress"]))
        elif kind == "group" and permission.get("emailAddress"):
            principal = self.mapping.for_group_email(str(permission["emailAddress"]))
        elif kind == "domain" and permission.get("domain"):
            principal = self.mapping.for_domain(str(permission["domain"]))
        elif kind == "anyone":
            principal = self.mapping.anyone
        if principal is None:
            log.warning("gdrive.unmapped_grantee", type=kind, permission_id=permission.get("id"))
        return principal

    # ---- incremental -------------------------------------------------------------------------------------
    def start_cursor(self) -> str:
        data = self._get("/changes/startPageToken", {"supportsAllDrives": "true"}).json()
        return str(data["startPageToken"])

    def changes(self, cursor: str, *, known_ids: set[str]) -> ChangeBatch:
        """Changes since ``cursor``. Files outside the synced tree are ignored unless already indexed."""
        batch = ChangeBatch(cursor=cursor)
        token: str | None = cursor
        while token:
            page = self._get(
                "/changes",
                {
                    "pageToken": token,
                    "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS}))",
                    "includeRemoved": "true",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
            ).json()
            for change in page.get("changes") or []:
                file_id = str(change.get("fileId"))
                item = change.get("file") or {}
                if change.get("removed") or item.get("trashed"):
                    if file_id in known_ids:
                        batch.removed.append(file_id)
                    continue
                if item.get("mimeType") == FOLDER:
                    continue
                if file_id in known_ids or self.root_folder_id in (item.get("parents") or []):
                    document = self.fetch(item)
                    if document is not None:
                        batch.upserts.append(document)
            token = page.get("nextPageToken")
            if page.get("newStartPageToken"):
                batch.cursor = str(page["newStartPageToken"])
        return batch
