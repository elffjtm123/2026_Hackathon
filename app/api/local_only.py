"""The one definition of a "local request" for local-development-only endpoints.

Each endpoint keeps its own error code and message; this module only decides.
"""

import ipaddress
from collections.abc import Collection
from typing import Literal

from starlette.requests import HTTPConnection

# ignore: any Origin; if_present: browsers must be an allowed origin, scripts may omit it;
# required: only an allowed browser origin (state-changing browser endpoints).
OriginRule = Literal["ignore", "if_present", "required"]
LocalVerdict = Literal["allowed", "disabled", "not_local"]


def is_loopback_peer(connection: HTTPConnection) -> bool:
    if connection.client is None:
        return False
    try:
        address = ipaddress.ip_address(connection.client.host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback


def local_request_verdict(
    connection: HTTPConnection,
    *,
    environments: Collection[str] = ("development",),
    enabled: bool = True,
    origin: OriginRule = "ignore",
    any_peer_in_test: bool = False,
) -> LocalVerdict:
    """"disabled" (feature off here) is decided before "not_local" (wrong peer or Origin)."""
    settings = connection.app.state.settings
    if settings.app_env not in environments or not enabled:
        return "disabled"
    peer_ok = (any_peer_in_test and settings.app_env == "test") or is_loopback_peer(connection)
    supplied = connection.headers.get("origin")
    origin_ok = (
        origin == "ignore"
        or (origin == "if_present" and supplied is None)
        or supplied in settings.cors_origins
    )
    return "allowed" if peer_ok and origin_ok else "not_local"
