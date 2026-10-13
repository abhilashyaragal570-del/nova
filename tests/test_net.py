import pytest

from app import net


def test_there_is_a_timeout_by_default():
    assert net.build_http_options().timeout == net.DEFAULT_TIMEOUT_MS


def test_the_timeout_can_be_changed():
    assert net.build_http_options(timeout_ms=5_000).timeout == 5_000


def test_ipv4_can_be_switched_off():
    options = net.build_http_options(force_ipv4=False)
    assert options.timeout == net.DEFAULT_TIMEOUT_MS
    assert not getattr(options, "client_args", None)


def test_ipv4_is_on_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_FORCE_IPV4", raising=False)
    assert net.force_ipv4_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "No", "OFF"])
def test_the_environment_can_switch_ipv4_off(monkeypatch, value):
    monkeypatch.setenv("NOVA_FORCE_IPV4", value)
    assert net.force_ipv4_enabled() is False