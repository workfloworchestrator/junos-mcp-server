import pytest
from junos_mcp_server import server


@pytest.mark.parametrize(
    "command",
    [
        "show interfaces",
        "  show version ",
        "show route table inet.0",
        "show interfaces | match ge-0/0/0",
        "show configuration | display set",  # display is read-only
    ],
)
def test_validate_accepts_show(command):
    assert server.validate_show_command(command) == command.strip()


@pytest.mark.parametrize(
    "command",
    [
        "",
        "   ",
        "configure",
        "request system reboot",
        "clear interfaces statistics",
        "set cli timestamp",
        "show interfaces | save /var/tmp/x",
        "show configuration | load merge x",
        "show interfaces | append /var/tmp/x",
        "show interfaces | tee /var/tmp/x",
        "show foo | SAVE x",
    ],
)
def test_validate_rejects_non_show(command):
    with pytest.raises(ValueError, match="only show commands"):
        server.validate_show_command(command)


@pytest.mark.parametrize(
    "address,expected",
    [("host.surf.net:32767", "host.surf.net"), ("host.surf.net", "host.surf.net")],
)
def test_host_only(address, expected):
    assert server._host_only(address) == expected


def test_fetch_targets_strips_port(monkeypatch):
    server._CACHE.update(targets=None, at=0.0)  # reset cache

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"r1.surf.net": {"address": "r1.surf.net:32767", "subscriptions": []}}

    monkeypatch.setattr(server.httpx, "get", lambda *a, **k: FakeResp())
    monkeypatch.setenv("ORCHESTRATOR_URL", "https://api.example.net")
    monkeypatch.setenv("GNMIC_HTTP_BASIC_USER", "gnmic")
    monkeypatch.setenv("GNMIC_HTTP_BASIC_PASSWORD", "secret")
    monkeypatch.setenv("JUNOS_SSH_USER", "ro")
    monkeypatch.setenv("JUNOS_SSH_PASSWORD", "pw")
    assert server.fetch_targets() == {"r1.surf.net": "r1.surf.net"}


def test_fetch_targets_dev_mode_bypasses_orchestrator(monkeypatch):
    server._CACHE.update(targets=None, at=0.0)  # reset cache

    def boom(*a, **k):  # orchestrator must not be called in dev mode
        raise AssertionError("httpx.get called in dev mode")

    monkeypatch.setattr(server.httpx, "get", boom)
    monkeypatch.setenv("JUNOS_DEV_MODE", "1")
    monkeypatch.setenv("JUNOS_DEV_TARGETS", '["r1.lab.net", "r2.lab.net"]')
    monkeypatch.setenv("JUNOS_SSH_USER", "ro")
    monkeypatch.setenv("JUNOS_SSH_PASSWORD", "pw")
    monkeypatch.delenv("ORCHESTRATOR_URL", raising=False)  # not required in dev mode
    assert server.fetch_targets() == {"r1.lab.net": "r1.lab.net", "r2.lab.net": "r2.lab.net"}
    assert server.list_devices() == ["r1.lab.net", "r2.lab.net"]


def test_run_show_command_unknown_device(monkeypatch):
    monkeypatch.setattr(server, "fetch_targets", lambda: {"r1": "r1.surf.net"})
    out = server.run_show_command("nope", "show version")
    assert "unknown device" in out and "r1" in out


def test_run_show_command_dispatches(monkeypatch):
    monkeypatch.setattr(server, "fetch_targets", lambda: {"r1": "r1.surf.net"})
    monkeypatch.setattr(server, "run_show", lambda fqdn, cmd: f"OUT {fqdn} {cmd}")
    out = server.run_show_command("r1", "  show version ")
    assert out == "OUT r1.surf.net show version"


def test_run_show_command_rejects_non_show(monkeypatch):
    monkeypatch.setattr(server, "fetch_targets", lambda: {"r1": "r1.surf.net"})
    with pytest.raises(ValueError, match="only show commands"):
        server.run_show_command("r1", "request system reboot")


def test_list_devices(monkeypatch):
    monkeypatch.setattr(server, "fetch_targets", lambda: {"b": "b.net", "a": "a.net"})
    assert server.list_devices() == ["a", "b"]
