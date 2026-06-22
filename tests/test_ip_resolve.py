from shuxin.integrations.location.ip_resolve import (
    clear_egress_ip_cache,
    is_private_or_loopback,
    resolve_effective_ip,
)


def test_is_private_or_loopback():
    assert is_private_or_loopback("127.0.0.1")
    assert is_private_or_loopback("10.0.0.1")
    assert is_private_or_loopback("192.168.1.5")
    assert not is_private_or_loopback("8.8.8.8")


def test_resolve_effective_ip_public_passthrough():
    assert resolve_effective_ip("8.8.4.4") == "8.8.4.4"


def test_resolve_effective_ip_private_uses_egress(monkeypatch):
    clear_egress_ip_cache()
    monkeypatch.setattr(
        "shuxin.integrations.location.ip_resolve.fetch_egress_public_ip",
        lambda: "203.0.113.10",
    )
    assert resolve_effective_ip("127.0.0.1") == "203.0.113.10"
    clear_egress_ip_cache()
