import pytest
from junos_mcp_server import server


def test_settings_reads_env(monkeypatch):
    for k, v in {
        "ORCHESTRATOR_URL": "https://api.example.net/",
        "GNMIC_HTTP_BASIC_USER": "gnmic",
        "GNMIC_HTTP_BASIC_PASSWORD": "secret",
        "JUNOS_SSH_USER": "ro",
        "JUNOS_SSH_PASSWORD": "pw",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JUNOS_SSH_PORT", raising=False)
    cfg = server.settings()
    assert cfg.orchestrator_url == "https://api.example.net"  # trailing slash stripped
    assert cfg.ssh_port == 830  # default


def test_settings_missing_required(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_URL", raising=False)
    with pytest.raises(RuntimeError, match="ORCHESTRATOR_URL"):
        server.settings()


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
