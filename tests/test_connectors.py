"""Google Drive and SharePoint (Graph) connectors against recorded API responses (tests/fixtures).

The fixtures follow the documented Drive v3 and Graph v1.0 response shapes; they were written for these tests, not
captured from a live tenant (see README: live sync against real tenants was not run).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from clearance.auth.mapping import GroupMapping
from clearance.connectors.gdrive import GoogleDriveConnector
from clearance.connectors.local import iter_folder
from clearance.connectors.oauth import GoogleServiceAccount, MicrosoftClientCredentials, StaticToken
from clearance.connectors.sharepoint import SharePointConnector
from clearance.connectors.sync import get_cursor, sync_gdrive, sync_sharepoint
from clearance.db.session import Database
from clearance.embeddings import HashEmbedder
from clearance.index import IndexWriter
from clearance.retrieval.search import Retriever
from tests.conftest import CORPUS, FIXTURES, ROOT

MAPPING = GroupMapping.load(ROOT / "configs" / "group-mapping.yaml")


# ---- Google Drive ----------------------------------------------------------------------------------------
class DriveRouter:
    def __init__(self) -> None:
        self.revoked = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer drive-token"
        path, params = request.url.path.removeprefix("/drive/v3"), request.url.params
        g = FIXTURES / "gdrive"
        if path == "/files":
            if "'root_folder' in parents" in params["q"]:
                name = "files_root_page2.json" if params.get("pageToken") == "page-2" else "files_root.json"
            else:
                name = "files_finance.json"
            return httpx.Response(200, json=json.loads((g / name).read_text()))
        if path.endswith("/permissions"):
            file_id = path.split("/")[2]
            suffix = "_revoked" if (self.revoked and file_id == "doc_board") else ""
            return httpx.Response(200, json=json.loads((g / f"permissions_{file_id}{suffix}.json").read_text()))
        if path.endswith("/export"):
            assert params["mimeType"] == "text/markdown"
            return httpx.Response(200, content=(g / f"export_{path.split('/')[2]}.md").read_bytes())
        if path == "/files/md_onboarding" and params.get("alt") == "media":
            return httpx.Response(200, content=(g / "media_md_onboarding.md").read_bytes())
        if path == "/changes/startPageToken":
            return httpx.Response(200, json=json.loads((g / "start_page_token.json").read_text()))
        if path == "/changes":
            return httpx.Response(200, json=json.loads((g / f"changes_{params['pageToken']}.json").read_text()))
        return httpx.Response(404, json={"error": {"code": 404, "message": f"unexpected {path}"}})


def _drive(router: DriveRouter) -> GoogleDriveConnector:
    return GoogleDriveConnector(
        tokens=StaticToken("drive-token"),
        mapping=MAPPING,
        root_folder_id="root_folder",
        http=httpx.Client(transport=httpx.MockTransport(router)),
    )


def test_drive_walks_folders_exports_docs_and_maps_permissions() -> None:
    documents = {d.external_id: d for d in _drive(DriveRouter()).documents()}
    assert set(documents) == {"doc_handbook", "md_onboarding", "doc_board"}  # images skipped, folder recursed
    board = documents["doc_board"]
    assert board.path == "Finance" and board.title == "Q3 Board Pack" and board.filename.endswith(".md")
    # owner + leadership group (inherited) + finance group; unmapped external group, "anyone with the link" and a
    # deleted permission grant nothing (fail closed)
    assert board.acl.allow == ("group:finance", "group:leadership", "user:kofi.mensah@fernhill.test")
    assert documents["doc_handbook"].acl.allow == ("group:all-employees", "user:carol.diaz@fernhill.test")
    assert documents["md_onboarding"].acl.allow == ("user:bob.tanner@fernhill.test", "user:erin.walsh@fernhill.test")
    assert b"25 days" in documents["doc_handbook"].content
    assert board.source_url == "https://docs.google.com/document/d/doc_board/edit"


@pytest.mark.db
def test_drive_full_then_incremental_sync(db: Database) -> None:
    router = DriveRouter()
    writer = IndexWriter(db, HashEmbedder())
    first = sync_gdrive(db, writer, _drive(router))
    assert first.count("created") == 3 and get_cursor(db, "gdrive") == "4100"
    retriever, embedder = Retriever(db), HashEmbedder()
    hana = ["user:hana.sato@fernhill.test", "group:leadership"]
    vector = embedder.embed_query("cash runway board pack")
    assert any("runway" in c.text for c in retriever.search(vector, hana, 5))

    router.revoked = True  # leadership removed from the board pack in Drive; content unchanged
    second = sync_gdrive(db, writer, _drive(router))
    assert second.count("acl_updated") == 1 and second.deleted == 2  # trashed + removed files
    assert get_cursor(db, "gdrive") == "4107"
    assert not any("runway" in c.text for c in retriever.search(vector, hana, 5))  # revocation propagated
    assert writer.external_ids("gdrive") == {"doc_board"}  # unrelated file outside the tree ignored


def test_google_service_account_token_exchange(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / "sa.json").write_text(
        json.dumps(
            {
                "client_email": "clearance@proj.iam.gserviceaccount.com",
                "private_key": pem.decode(),
                "private_key_id": "k1",
            }
        )
    )
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import urllib.parse

        import jwt

        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        claims = jwt.decode(
            form["assertion"], key.public_key(), algorithms=["RS256"], audience=GoogleServiceAccount.TOKEN_URL
        )
        seen.append(claims)
        return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3599, "token_type": "Bearer"})

    tokens = GoogleServiceAccount(
        tmp_path / "sa.json",
        subject="ian.brooks@fernhill.test",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert tokens.token() == "ya29.test" and tokens.token() == "ya29.test"
    assert len(seen) == 1 and seen[0]["sub"] == "ian.brooks@fernhill.test" and "drive.readonly" in seen[0]["scope"]


# ---- SharePoint / Graph -----------------------------------------------------------------------------------
def _docx(text: str) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (
        f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>'
        f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Budget 2027</w:t></w:r></w:p>'
        f'<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Engineering</w:t></w:r></w:p>'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


class GraphRouter:
    def __init__(self) -> None:
        self.revoked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        g = FIXTURES / "graph"
        path, token = request.url.path, request.url.params.get("token")
        if request.url.host == "download.test":  # pre-authenticated URL: httpx drops the bearer token cross-host
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=(g / f"content_{path.strip('/')}.md").read_bytes())
        assert request.headers["Authorization"] == "Bearer graph-token"
        if path == "/v1.0/sites/site-1/drive":
            return httpx.Response(200, json=json.loads((g / "site_drive.json").read_text()))
        if path.endswith("/root/delta"):
            name = {None: "delta_page1", "page2": "delta_page2", "cursor-1": "delta_incremental"}[token]
            return httpx.Response(200, json=json.loads((g / f"{name}.json").read_text()))
        if path.endswith("/permissions"):
            item = path.split("/")[-2]
            suffix = "_revoked" if (self.revoked and item == "01BUDGET") else ""
            return httpx.Response(200, json=json.loads((g / f"permissions_{item}{suffix}.json").read_text()))
        if path.endswith("/content"):
            item = path.split("/")[-2]
            if item == "01BUDGET":
                return httpx.Response(200, content=_docx("The engineering budget is 9.4 million."))
            return httpx.Response(302, headers={"Location": f"https://download.test/{item}"})
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": path}})


def _sharepoint(router: GraphRouter) -> SharePointConnector:
    return SharePointConnector(
        tokens=StaticToken("graph-token"),
        mapping=MAPPING,
        site_id="site-1",
        organization_domain="fernhill.test",
        http=httpx.Client(transport=httpx.MockTransport(router), follow_redirects=True),
    )


def test_sharepoint_delta_reads_files_and_effective_permissions() -> None:
    batch = _sharepoint(GraphRouter()).delta()
    documents = {d.external_id: d for d in batch.upserts}
    assert set(documents) == {"01BUDGET", "01HANDBOOK"} and batch.cursor.endswith("token=cursor-1")
    budget = documents["01BUDGET"]
    assert budget.path == "Finance" and budget.title == "Budget 2027"
    # owner (user), Entra group by object id, SharePoint site group by name; anonymous link and unknown group dropped
    assert budget.acl.allow == ("group:finance", "group:leadership", "user:kofi.mensah@fernhill.test")
    handbook = documents["01HANDBOOK"]
    # organization link -> the mapped domain principal; "specific people" link -> those users (incl. claims login)
    assert handbook.acl.allow == (
        "group:all-employees",
        "user:bob.tanner@fernhill.test",
        "user:erin.walsh@fernhill.test",
    )
    assert b"25 days" in handbook.content  # followed the 302 to the download URL


@pytest.mark.db
def test_sharepoint_incremental_sync_applies_deletions_and_permission_changes(db: Database) -> None:
    router = GraphRouter()
    writer = IndexWriter(db, HashEmbedder())
    first = sync_sharepoint(db, writer, _sharepoint(router))
    assert first.count("created") == 2 and str(get_cursor(db, "sharepoint")).endswith("cursor-1")
    retriever, embedder = Retriever(db), HashEmbedder()
    hana = ["user:hana.sato@fernhill.test", "group:leadership"]
    vector = embedder.embed_query("engineering budget")
    assert any("9.4 million" in c.text for c in retriever.search(vector, hana, 5))
    router.revoked = True
    second = sync_sharepoint(db, writer, _sharepoint(router))
    assert second.count("acl_updated") == 1 and second.deleted == 1
    assert not any("9.4 million" in c.text for c in retriever.search(vector, hana, 5))
    assert writer.external_ids("sharepoint") == {"01BUDGET"}


def test_microsoft_client_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tenant-1/oauth2/v2.0/token"
        assert b"scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" in request.content
        return httpx.Response(200, json=json.loads((FIXTURES / "graph" / "token.json").read_text()))

    tokens = MicrosoftClientCredentials(
        "tenant-1", "app-1", "secret", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert tokens.token().endswith("test-access-token")


# ---- local folder -------------------------------------------------------------------------------------------
def test_local_folder_reads_sidecars_and_skips_acl_files() -> None:
    documents = {d.external_id: d for d in iter_folder(CORPUS)}
    assert len(documents) == 60 and not any(e.endswith(".yaml") for e in documents)
    sow = documents["shared/bob-tanner-statement-of-work.md"]
    assert sow.path == "shared" and "user:bob.tanner@fernhill.test" in sow.acl.allow
