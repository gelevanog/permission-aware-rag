"""OIDC/JWT verification and the mapping from token claims to an Identity with principals.

The same verifier serves the built-in dev IdP and a real provider (Okta, Microsoft Entra ID, Google, Keycloak,
Auth0): signature against the issuer's JWKS, issuer, audience, expiry; then the groups claim is mapped to
principals with ``GroupMapping``. The principal set is derived from the verified token on every request and never
taken from anything the client sends.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import jwt

from clearance.acl import AclError, normalize_principals, user_principal
from clearance.auth.mapping import GroupMapping
from clearance.logging_config import get_logger

log = get_logger(__name__)


class AuthError(Exception):
    """Missing, malformed, expired or untrusted token (HTTP 401)."""


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    name: str
    principals: tuple[str, ...]
    groups: tuple[str, ...] = ()
    """The groups claim as the IdP sent it (for display and debugging)."""
    is_admin: bool = False
    title: str | None = None

    @property
    def user_principal(self) -> str:
        return user_principal(self.email)


class KeySource(Protocol):
    def signing_key(self, token: str) -> Any: ...


class StaticKeys:
    """Keys known in-process (the dev IdP's public key, or keys pinned in tests)."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._keys = jwt.PyJWKSet.from_dict(jwks)

    def signing_key(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        for key in self._keys.keys:
            if kid is None or key.key_id == kid:
                return key.key
        raise AuthError("token signed with an unknown key")


class RemoteJwks:
    """The issuer's JWKS over HTTPS, cached by PyJWT and refreshed when an unknown ``kid`` shows up."""

    def __init__(self, jwks_url: str) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

    def signing_key(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            raise AuthError(f"cannot get the signing key: {exc}") from exc


def discover_jwks_url(issuer: str, *, timeout: float = 10.0) -> str:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    jwks_uri = response.json().get("jwks_uri")
    if not isinstance(jwks_uri, str):
        raise AuthError(f"no jwks_uri in {url}")
    return jwks_uri


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        keys: KeySource,
        mapping: GroupMapping,
        algorithms: Sequence[str] = ("RS256",),
        groups_claim: str = "groups",
        email_claim: str = "email",
        admin_principals: Sequence[str] = (),
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.keys = keys
        self.mapping = mapping
        self.algorithms = list(algorithms)
        if any(alg.lower() == "none" or alg.upper().startswith("HS") for alg in self.algorithms):
            raise ValueError("only asymmetric signature algorithms are accepted (RS*, ES*, PS*, EdDSA)")
        self.groups_claim = groups_claim
        self.email_claim = email_claim
        self.admin_principals = set(admin_principals)
        self.leeway = leeway_seconds

    def verify(self, token: str) -> Identity:
        try:
            key = self.keys.signing_key(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except AuthError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {exc}") from exc
        return self.identity_from_claims(claims)

    def identity_from_claims(self, claims: dict[str, Any]) -> Identity:
        email = claims.get(self.email_claim) or claims.get("preferred_username") or claims.get("upn")
        if not isinstance(email, str) or "@" not in email:
            raise AuthError(f"token has no usable {self.email_claim!r} claim")
        raw_groups = claims.get(self.groups_claim) or []
        if isinstance(raw_groups, str):
            raw_groups = [raw_groups]
        if not isinstance(raw_groups, list):
            raise AuthError(f"the {self.groups_claim!r} claim must be a list")
        groups = tuple(str(group) for group in raw_groups)
        mapped, unmapped = self.mapping.principals_for_claims(groups)
        if unmapped:
            log.debug("auth.unmapped_groups", count=len(unmapped))
        try:
            principals = normalize_principals([f"user:{email}", *mapped])
        except AclError as exc:
            raise AuthError(str(exc)) from exc
        return Identity(
            subject=str(claims["sub"]),
            email=email.lower(),
            name=str(claims.get("name") or email),
            principals=principals,
            groups=groups,
            is_admin=bool(self.admin_principals & set(principals)),
            title=str(claims["title"]) if claims.get("title") else None,
        )
