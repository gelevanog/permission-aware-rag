"""A tiny OpenID Connect issuer for the demo company (development only).

It publishes a discovery document and a JWKS and signs RS256 ID tokens for the users in ``data/directory.yaml``,
with a ``groups`` claim in the shape a real IdP sends (Okta-style group names). Because the API verifies these
tokens with exactly the same code it uses for Okta or Entra ID, the demo exercises the production auth path; only
the "log in" step (pick a user) is fake. Disabled with ``CLEARANCE_DEV_IDP_ENABLED=false``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jwt
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@dataclass(frozen=True)
class DirectoryUser:
    email: str
    name: str
    title: str
    department: str
    idp_groups: tuple[str, ...]
    persona: str = ""


@dataclass(frozen=True)
class DirectoryGroup:
    name: str
    idp_group: str
    description: str = ""


@dataclass(frozen=True)
class Directory:
    company: str
    domain: str
    users: tuple[DirectoryUser, ...]
    groups: tuple[DirectoryGroup, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, path: Path) -> Directory:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            company=str(data["company"]),
            domain=str(data["domain"]),
            groups=tuple(
                DirectoryGroup(
                    name=str(g["name"]), idp_group=str(g["idp_group"]), description=str(g.get("description", ""))
                )
                for g in data.get("groups", [])
            ),
            users=tuple(
                DirectoryUser(
                    email=str(u["email"]).lower(),
                    name=str(u["name"]),
                    title=str(u["title"]),
                    department=str(u["department"]),
                    idp_groups=tuple(str(g) for g in u.get("idp_groups", [])),
                    persona=str(u.get("persona", "")),
                )
                for u in data["users"]
            ),
        )

    def user(self, email: str) -> DirectoryUser:
        for user in self.users:
            if user.email == email.lower():
                return user
        raise KeyError(email)


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class DevIdentityProvider:
    def __init__(self, *, issuer: str, audience: str, key_file: Path, directory: Directory, ttl_seconds: int = 28800):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self._private_key = self._load_or_create(key_file)
        public = self._private_key.public_key().public_numbers()
        self._jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "n": _b64(public.n), "e": _b64(public.e)}
        thumbprint = json.dumps({"e": self._jwk["e"], "kty": "RSA", "n": self._jwk["n"]}, separators=(",", ":"))
        self._jwk["kid"] = base64.urlsafe_b64encode(hashlib.sha256(thumbprint.encode()).digest()).rstrip(b"=").decode()

    @staticmethod
    def _load_or_create(key_file: Path) -> rsa.RSAPrivateKey:
        if key_file.exists():
            key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
            if isinstance(key, rsa.RSAPrivateKey):
                return key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        try:
            key_file.parent.mkdir(parents=True, exist_ok=True)
            pem = key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            key_file.write_bytes(pem)
            key_file.chmod(0o600)
        except OSError:
            pass  # read-only filesystem: an in-memory key is fine (tokens die with the process)
        return key

    def jwks(self) -> dict[str, Any]:
        return {"keys": [dict(self._jwk)]}

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "jwks_uri": f"{self.issuer}/jwks.json",
            "token_endpoint": f"{self.issuer}/token",
            "id_token_signing_alg_values_supported": ["RS256"],
            "response_types_supported": ["id_token"],
            "subject_types_supported": ["public"],
            "claims_supported": ["sub", "email", "name", "groups", "title"],
        }

    def issue(self, email: str, *, now: float | None = None, extra_claims: dict[str, Any] | None = None) -> str:
        user = self.directory.user(email)
        issued = int(now if now is not None else time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.issuer}/{user.email}")),
            "email": user.email,
            "name": user.name,
            "title": user.title,
            "groups": list(user.idp_groups),
            "iat": issued,
            "exp": issued + self.ttl_seconds,
            **(extra_claims or {}),
        }
        return jwt.encode(claims, self._private_key, algorithm="RS256", headers={"kid": self._jwk["kid"]})
