"""OIDC/JWT verification, the dev IdP, and group-claim mapping to principals."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from clearance.auth.devidp import DevIdentityProvider, Directory
from clearance.auth.mapping import GroupMapping
from clearance.auth.tokens import AuthError, RemoteJwks, StaticKeys, TokenVerifier
from tests.conftest import ROOT

DIRECTORY = Directory.load(ROOT / "data" / "directory.yaml")
MAPPING = GroupMapping.load(ROOT / "configs" / "group-mapping.yaml")


@pytest.fixture
def idp(tmp_path: Path) -> DevIdentityProvider:
    return DevIdentityProvider(
        issuer="http://localhost:8000/dev-idp", audience="clearance", key_file=tmp_path / "k.pem", directory=DIRECTORY
    )


def verifier(idp: DevIdentityProvider, **kwargs: Any) -> TokenVerifier:
    return TokenVerifier(
        issuer=idp.issuer,
        audience="clearance",
        keys=StaticKeys(idp.jwks()),
        mapping=MAPPING,
        admin_principals=["group:it-admins"],
        **kwargs,
    )


def test_dev_idp_token_maps_groups_to_principals(idp: DevIdentityProvider) -> None:
    identity = verifier(idp).verify(idp.issue("alice.chen@fernhill.test"))
    assert identity.email == "alice.chen@fernhill.test"
    assert identity.principals == ("group:all-employees", "group:finance", "user:alice.chen@fernhill.test")
    assert "FH-Lisbon-Office" in identity.groups  # asserted by the IdP, deliberately unmapped -> no principal
    assert not identity.is_admin


def test_contractor_is_not_an_employee_and_admin_flag_comes_from_groups(idp: DevIdentityProvider) -> None:
    bob = verifier(idp).verify(idp.issue("bob.tanner@fernhill.test"))
    assert "group:all-employees" not in bob.principals and "group:contractors" in bob.principals
    ian = verifier(idp).verify(idp.issue("ian.brooks@fernhill.test"))
    assert ian.is_admin and "group:it-admins" in ian.principals


def test_dev_idp_publishes_discovery_and_jwks(idp: DevIdentityProvider) -> None:
    discovery = idp.discovery()
    assert discovery["jwks_uri"] == "http://localhost:8000/dev-idp/jwks.json"
    key = idp.jwks()["keys"][0]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["kid"]


def test_signing_key_survives_restarts(tmp_path: Path) -> None:
    first = DevIdentityProvider(issuer="i", audience="a", key_file=tmp_path / "k.pem", directory=DIRECTORY)
    second = DevIdentityProvider(issuer="i", audience="a", key_file=tmp_path / "k.pem", directory=DIRECTORY)
    assert first.jwks() == second.jwks()


def test_expired_wrong_audience_and_wrong_issuer_are_rejected(idp: DevIdentityProvider) -> None:
    v = verifier(idp)
    with pytest.raises(AuthError, match=r"(?i)expired"):
        v.verify(idp.issue("dan.kim@fernhill.test", now=time.time() - 10 * 3600))
    with pytest.raises(AuthError, match=r"(?i)audience"):
        v.verify(idp.issue("dan.kim@fernhill.test", extra_claims={"aud": "someone-else"}))
    with pytest.raises(AuthError, match=r"(?i)issuer"):
        v.verify(idp.issue("dan.kim@fernhill.test", extra_claims={"iss": "https://evil.test"}))


def test_forged_tokens_are_rejected(idp: DevIdentityProvider) -> None:
    v = verifier(idp)
    claims = jwt.decode(idp.issue("dan.kim@fernhill.test"), options={"verify_signature": False})
    claims["groups"] = ["FH-Leadership"]  # privilege escalation attempt
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = idp.jwks()["keys"][0]["kid"]
    with pytest.raises(AuthError):
        v.verify(jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": kid}))
    with pytest.raises(AuthError):
        v.verify(
            jwt.encode(claims, "shared-secret-that-is-long-enough-for-hs256", algorithm="HS256", headers={"kid": kid})
        )
    unsigned = jwt.encode(claims, key=None, algorithm="none")  # type: ignore[arg-type]
    with pytest.raises(AuthError):
        v.verify(unsigned)


def test_symmetric_algorithms_cannot_be_configured(idp: DevIdentityProvider) -> None:
    with pytest.raises(ValueError):
        verifier(idp, algorithms=["HS256"])


def test_missing_email_claim_is_rejected(idp: DevIdentityProvider) -> None:
    v = verifier(idp)
    token = idp.issue("dan.kim@fernhill.test", extra_claims={"email": None})
    with pytest.raises(AuthError, match="email"):
        v.verify(token)


def test_entra_object_ids_and_google_group_emails_map_to_the_same_principals() -> None:
    principals, unmapped = MAPPING.principals_for_claims(
        ["9d41b7c2-5e3a-4f88-b2c6-7a1e0d3f4b02", "LEADERSHIP@fernhill.test", "unknown-group"]
    )
    assert principals == ["group:finance", "group:leadership"]
    assert unmapped == ["unknown-group"]


def test_passthrough_mode_turns_unmapped_groups_into_principals() -> None:
    mapping = GroupMapping.from_dict({}, passthrough=True)
    principals, unmapped = mapping.principals_for_claims(["Data Science", "bad,group"])
    assert principals == ["group:data-science"] and unmapped == ["bad,group"]


def test_remote_jwks_verification_like_okta_or_entra(monkeypatch: pytest.MonkeyPatch, idp: DevIdentityProvider) -> None:
    """A real provider: keys come from the issuer's JWKS URL (fetched by PyJWT's client; no network here)."""
    keys = RemoteJwks("https://login.example.test/oauth2/v1/keys")
    monkeypatch.setattr(keys._client, "fetch_data", lambda: idp.jwks())
    v = TokenVerifier(issuer=idp.issuer, audience="clearance", keys=keys, mapping=MAPPING)
    assert v.verify(idp.issue("grace.liu@fernhill.test")).principals[-1] == "user:grace.liu@fernhill.test"
