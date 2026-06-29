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
