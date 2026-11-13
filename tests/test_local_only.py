"""The single definition of a local development request, shared by every local-only endpoint."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api.local_only import local_request_verdict
from app.core.config import Settings


def connection(host="127.0.0.1", origin=None, app_env="development"):
    settings = Settings(
        _env_file=None,
        app_env=app_env,
        jwt_secret="k" * 48,
        cors_origins=["http://allowed.test"],
    )
    headers = [] if origin is None else [(b"origin", origin.encode())]
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    client = None if host is None else (host, 50000)
    return Request({"type": "http", "client": client, "headers": headers, "app": app})


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"])
def test_loopback_v4_and_v6_peers_are_local(host):
    assert local_request_verdict(connection(host)) == "allowed"


@pytest.mark.parametrize(
    "host", ["192.0.2.1", "::ffff:192.0.2.1", "2001:db8::1", "testclient", None]
)
def test_non_loopback_or_unknown_peers_are_not_local(host):
    assert local_request_verdict(connection(host)) == "not_local"


def test_production_and_disabled_features_are_disabled_before_peer_checks():
    assert local_request_verdict(connection("192.0.2.1", app_env="production")) == "disabled"
    production = connection(app_env="production")
    assert local_request_verdict(production, environments={"development", "test"}) == "disabled"
    assert local_request_verdict(connection(), enabled=False) == "disabled"


def test_environment_allow_list_is_per_endpoint():
    assert local_request_verdict(connection(app_env="test")) == "disabled"
    both = {"development", "test"}
    assert local_request_verdict(connection(app_env="test"), environments=both) == "allowed"


def test_test_environment_exemption_skips_only_the_peer_check():
    remote = connection("192.0.2.1", app_env="test")
    both = {"development", "test"}
    assert local_request_verdict(remote, environments=both) == "not_local"
    assert local_request_verdict(remote, environments=both, any_peer_in_test=True) == "allowed"
    dev_remote = connection("192.0.2.1")
    assert local_request_verdict(dev_remote, environments=both, any_peer_in_test=True) == (
        "not_local"
    )
    evil = connection("192.0.2.1", origin="https://evil.test", app_env="test")
    assert (
        local_request_verdict(evil, environments=both, any_peer_in_test=True, origin="if_present")
        == "not_local"
    )


@pytest.mark.parametrize(
    ("rule", "origin", "expected"),
    [
        ("ignore", None, "allowed"),
        ("ignore", "https://evil.test", "allowed"),
        ("if_present", None, "allowed"),
        ("if_present", "http://allowed.test", "allowed"),
        ("if_present", "https://evil.test", "not_local"),
        ("required", None, "not_local"),
        ("required", "http://allowed.test", "allowed"),
        ("required", "https://evil.test", "not_local"),
    ],
)
def test_origin_rules(rule, origin, expected):
    assert local_request_verdict(connection(origin=origin), origin=rule) == expected
