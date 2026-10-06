"""Access tokens for the Google Drive and Microsoft Graph connectors (no vendor SDKs needed)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Protocol

import httpx
import jwt


class TokenProvider(Protocol):
    def token(self) -> str: ...


class StaticToken:
    """A token obtained elsewhere (e.g. `gcloud auth print-access-token`), mainly for trying a connector by hand."""

    def __init__(self, value: str) -> None:
        self._value = value

    def token(self) -> str:
        return self._value


class _Cached:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires = 0.0
        self._lock = threading.Lock()

    def token(self) -> str:
        with self._lock:
            if self._token is None or time.time() > self._expires - 60:
                self._token, lifetime = self._fetch()
                self._expires = time.time() + lifetime
            return self._token

    def _fetch(self) -> tuple[str, float]:
        raise NotImplementedError


class GoogleServiceAccount(_Cached):
    """OAuth 2.0 JWT-bearer grant for a Google service account.

    With ``subject`` set (domain-wide delegation), the service account acts as that Workspace user and sees what
    the user sees. Scope ``drive.readonly`` covers files, exports, permissions and the changes feed.
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPE = "https://www.googleapis.com/auth/drive.readonly"

    def __init__(self, key_file: Path, *, subject: str | None = None, http: httpx.Client | None = None) -> None:
        super().__init__()
        info = json.loads(key_file.read_text(encoding="utf-8"))
        self._email = str(info["client_email"])
        self._key = str(info["private_key"])
        self._key_id = info.get("private_key_id")
        self._subject = subject
        self._http = http or httpx.Client(timeout=30)

    def _fetch(self) -> tuple[str, float]:
        now = int(time.time())
        claims = {"iss": self._email, "scope": self.SCOPE, "aud": self.TOKEN_URL, "iat": now, "exp": now + 3600}
        if self._subject:
            claims["sub"] = self._subject
        headers = {"kid": self._key_id} if self._key_id else None
        assertion = jwt.encode(claims, self._key, algorithm="RS256", headers=headers)
        response = self._http.post(
            self.TOKEN_URL,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        response.raise_for_status()
        data = response.json()
        return str(data["access_token"]), float(data.get("expires_in", 3600))


class MicrosoftClientCredentials(_Cached):
    """OAuth 2.0 client-credentials grant for an Entra ID app registration with Graph application permissions
    (``Sites.Read.All`` or ``Sites.Selected``; ``Files.Read.All``)."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, *, http: httpx.Client | None = None) -> None:
        super().__init__()
        self._url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self._client_id = client_id
        self._secret = client_secret
        self._http = http or httpx.Client(timeout=30)

    def _fetch(self) -> tuple[str, float]:
        response = self._http.post(
            self._url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        response.raise_for_status()
        data = response.json()
        return str(data["access_token"]), float(data.get("expires_in", 3600))
