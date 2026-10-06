"""HTTP API end to end with the dev IdP (needs TEST_DATABASE_URL)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clearance.api.app import create_app
from clearance.config import DEFAULT_NO_ANSWER
from clearance.services import Services

pytestmark = pytest.mark.db


@pytest.fixture
def client(seeded: Services) -> Iterator[TestClient]:
    with TestClient(create_app(seeded)) as test_client:
        yield test_client


def auth(client: TestClient, email: str) -> dict[str, str]:
    token = client.post("/dev-idp/token", json={"email": email}).json()["id_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_and_dev_idp_endpoints(client: TestClient) -> None:
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["documents"] == 60 and health["local_only"] is True
    discovery = client.get("/dev-idp/.well-known/openid-configuration").json()
    assert discovery["jwks_uri"].endswith("/dev-idp/jwks.json")
    assert client.get("/dev-idp/jwks.json").json()["keys"][0]["alg"] == "RS256"
    assert len(client.get("/dev-idp/users").json()) == 11
    assert client.post("/dev-idp/token", json={"email": "mallory@evil.test"}).status_code == 404


def test_requests_without_a_valid_token_are_rejected(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 401
    bad = client.post("/api/ask", json={"question": "hi"}, headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


def test_me_reports_principals_from_the_token(client: TestClient) -> None:
    me = client.get("/api/me", headers=auth(client, "bob.tanner@fernhill.test")).json()
    assert me["principals"] == ["group:contractors", "group:engineering", "user:bob.tanner@fernhill.test"]
    assert me["is_admin"] is False


def test_same_question_two_users(client: TestClient) -> None:
    question = {"question": "What is the absolute floor price for the Growth tier?"}
    julia = client.post("/api/ask", json=question, headers=auth(client, "julia.romero@fernhill.test")).json()
    frank = client.post("/api/ask", json=question, headers=auth(client, "frank.moreau@fernhill.test")).json()
    assert "Floor prices and approval thresholds" in {c["section"] for c in julia["citations"]}
    assert "$31" in julia["text"]
    assert all(c["section"] != "Floor prices and approval thresholds" for c in frank["citations"])
    assert "$31" not in frank["text"]
    assert frank["trace"]["excluded_documents"] > julia["trace"]["excluded_documents"]


def test_streaming_endpoint_emits_trace_tokens_and_done(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/ask/stream",
        json={"question": "What is the per diem in Portugal?"},
        headers=auth(client, "dan.kim@fernhill.test"),
    ) as response:
        events = [json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "trace" and kinds[-1] == "done" and "token" in kinds
    assert events[0]["trace"]["searchable_documents"] == 31
    assert "€55" in events[-1]["answer"]["text"]


def test_document_view_hides_restricted_sections_and_forbidden_documents(client: TestClient, seeded: Services) -> None:
    admin = auth(client, "ian.brooks@fernhill.test")
    documents = {d["external_id"]: d for d in client.get("/api/admin/documents", headers=admin).json()}
    ladder = documents["engineering/engineering-career-ladder.md"]["id"]
    dan = client.get(f"/api/documents/{ladder}", headers=auth(client, "dan.kim@fernhill.test")).json()
    assert dan["chunks"] and all("Salary bands" not in c["section"] for c in dan["chunks"])
    erin = client.get(f"/api/documents/{ladder}", headers=auth(client, "erin.walsh@fernhill.test")).json()
    assert any(c["section"] == "Salary bands" for c in erin["chunks"])
    memo = documents["leadership/project-kingfisher-acquisition-memo.md"]["id"]
    forbidden = client.get(f"/api/documents/{memo}", headers=auth(client, "dan.kim@fernhill.test"))
    missing = client.get(
        "/api/documents/00000000-0000-0000-0000-000000000000", headers=auth(client, "dan.kim@fernhill.test")
    )
    assert forbidden.status_code == missing.status_code == 404 and forbidden.json() == missing.json()
    titles = {
        d["title"]
        for d in client.get("/api/documents", headers=auth(client, "dan.kim@fernhill.test")).json()["documents"]
    }
    assert not any("Kingfisher" in title for title in titles)


def test_admin_endpoints_require_the_admin_group(client: TestClient) -> None:
    hana = auth(client, "hana.sato@fernhill.test")  # the CEO is not a Clearance administrator
    assert client.get("/api/admin/documents", headers=hana).status_code == 403
    assert client.get("/api/admin/audit", headers=hana).status_code == 403
    directory = client.get("/api/admin/directory", headers=auth(client, "ian.brooks@fernhill.test")).json()
    bob = next(u for u in directory["users"] if u["email"].startswith("bob"))
    assert "group:contractors" in bob["principals"]


def test_admin_acl_edit_changes_the_next_answer(client: TestClient) -> None:
    admin = auth(client, "ian.brooks@fernhill.test")
    documents = {d["external_id"]: d for d in client.get("/api/admin/documents", headers=admin).json()}
    playbook = documents["sales/sales-playbook.md"]
    question = {"question": "What is the absolute floor price for the Growth tier?"}
    frank = auth(client, "frank.moreau@fernhill.test")
    before = client.post("/api/ask", json=question, headers=frank).json()
    acl: dict[str, Any] = dict(playbook["acl"])
    acl["sections"] = [{"heading": "Floor prices and approval thresholds", "allow": ["group:sales"], "deny": []}]
    updated = client.put(f"/api/admin/documents/{playbook['id']}/acl", json=acl, headers=admin)
    assert updated.status_code == 200 and updated.json()["chunks_updated"] >= 1
    after = client.post("/api/ask", json=question, headers=frank).json()
    assert "Floor prices and approval thresholds" not in {c["section"] for c in before["citations"]}
    assert any(r["section"] == "Floor prices and approval thresholds" for r in after["trace"]["retrieved"])
    bad = client.put(f"/api/admin/documents/{playbook['id']}/acl", json={"allow": ["finance"]}, headers=admin)
    assert bad.status_code == 422
    events = [e["event"] for e in client.get("/api/admin/audit", headers=admin).json()]
    assert "acl_update" in events and "ask" in events


def test_upload_with_acl_and_delete(client: TestClient) -> None:
    admin = auth(client, "ian.brooks@fernhill.test")
    body = b"# Pet policy\n\n## Dogs\n\nDogs are welcome in the Lisbon office on Fridays.\n"
    created = client.post(
        "/api/admin/documents",
        files={"file": ("pet-policy.md", body, "text/markdown")},
        data={"acl": "allow: [group:engineering]", "path": "uploads"},
        headers=admin,
    )
    assert created.status_code == 200 and created.json()["action"] == "created"
    question = {"question": "Are dogs welcome in the office?"}
    dan = client.post("/api/ask", json=question, headers=auth(client, "dan.kim@fernhill.test")).json()
    frank = client.post("/api/ask", json=question, headers=auth(client, "frank.moreau@fernhill.test")).json()
    assert "Fridays" in dan["text"] and "Fridays" not in frank["text"]
    document_id = created.json()["document_id"]
    assert client.delete(f"/api/admin/documents/{document_id}", headers=admin).status_code == 200
    gone = client.post("/api/ask", json=question, headers=auth(client, "dan.kim@fernhill.test")).json()
    assert "Fridays" not in gone["text"]
    no_acl = client.post(
        "/api/admin/documents",
        files={"file": ("x.md", b"# X\n\ntext", "text/markdown")},
        data={"acl": "allow: []"},
        headers=admin,
    )
    assert no_acl.status_code == 422


def test_no_answer_message_and_audit_masking(client: TestClient) -> None:
    dan = auth(client, "dan.kim@fernhill.test")
    reply = client.post("/api/ask", json={"question": "Who won the 2025 hackathon?"}, headers=dan).json()
    assert reply["text"] == DEFAULT_NO_ANSWER and reply["outcome"] == "no_answer"
    entries = client.get("/api/admin/audit", headers=auth(client, "ian.brooks@fernhill.test")).json()
    assert entries[0]["question_preview"].startswith("Who won the #### hackathon")


def test_eval_results_endpoint(client: TestClient) -> None:
    data = client.get("/api/eval", headers=auth(client, "dan.kim@fernhill.test")).json()
    assert set(data) >= {"leak", "quality", "acl_change", "latency"}
