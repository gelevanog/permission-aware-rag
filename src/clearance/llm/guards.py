"""Two guards that run before any request leaves the process.

* **Local-only switch** (on by default): refuses cloud providers and any OpenAI-compatible URL whose host is not
  this machine or a private network, so company documents cannot be sent to a third party by a configuration
  mistake. Host names are not resolved (DNS can change); a name counts as local only if it is ``localhost``, a
  single-label name such as the Compose service ``ollama``, ends in ``.local``/``.internal``/``.lan``, or is listed
  in ``CLEARANCE_LOCAL_ALLOWED_HOSTS``.
* **Free-only guard** (on by default): refuses any OpenRouter model id that does not end in ``:free``, and rejects
  an answer that OpenRouter served from a non-free model.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlparse

from clearance.llm.base import PolicyViolationError

CLOUD_KINDS = frozenset({"openrouter", "openai", "anthropic"})
_LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".localhost", ".home.arpa")


def is_local_url(url: str, allowed_hosts: Iterable[str] = ()) -> bool:
    host = (urlparse(url).hostname or "").lower().strip("[]")
    if not host:
        return False
    if host in {h.lower() for h in allowed_hosts} or host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host  # single-label names: Docker Compose services, hosts on the LAN
    return address.is_loopback or address.is_private or address.is_link_local


def ensure_local_allowed(
    kind: str, base_url: str | None, *, local_only: bool, allowed_hosts: Iterable[str] = ()
) -> None:
    if not local_only:
        return
    if kind in CLOUD_KINDS:
        raise PolicyViolationError(
            f"local-only mode: refusing the cloud provider {kind!r} (set CLEARANCE_LOCAL_ONLY=false to allow it)"
        )
    if base_url and not is_local_url(base_url, allowed_hosts):
        raise PolicyViolationError(
            f"local-only mode: {urlparse(base_url).hostname!r} is not a local or private host "
            "(add it to CLEARANCE_LOCAL_ALLOWED_HOSTS if it is yours, or set CLEARANCE_LOCAL_ONLY=false)"
        )


def ensure_free_models(model_ids: Iterable[str]) -> None:
    paid = [model for model in model_ids if not str(model).endswith(":free")]
    if paid:
        raise PolicyViolationError(
            f"free-only guard: refusing non-free OpenRouter model id(s): {', '.join(paid)} "
            "(set CLEARANCE_REQUIRE_FREE_MODELS=false to allow paid models)"
        )


def ensure_served_free(served_model: str | None) -> None:
    if served_model and not served_model.endswith(":free"):
        raise PolicyViolationError(
            f"free-only guard: OpenRouter served non-free model {served_model!r}; answer rejected"
        )
