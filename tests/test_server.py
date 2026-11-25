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


FLEET = {
    "aac001a-jnx-01.dcn.surf.net": "aac001a-jnx-01.dcn.surf.net",
    "aac001a-jnx-02.dcn.surf.net": "aac001a-jnx-02.dcn.surf.net",
    "lw003a-jnx-03.dcn.surf.net": "lw003a-jnx-03.dcn.surf.net",
    # two FQDNs sharing the short name "dup-jnx-01"
    "dup-jnx-01.dcn.surf.net": "dup-jnx-01.dcn.surf.net",
    "dup-jnx-01.other.surf.net": "dup-jnx-01.other.surf.net",
}
# many near-identical names, to prove suggestions are capped
CROWDED = {f"cr{n:03d}a-jnx-01.dcn.surf.net": f"cr{n:03d}a-jnx-01.dcn.surf.net" for n in range(40)}


@pytest.mark.parametrize(
    "device,expected",
    [
        pytest.param("aac001a-jnx-01.dcn.surf.net", "aac001a-jnx-01.dcn.surf.net", id="exact-fqdn"),
        pytest.param("AAC001A-JNX-01", "aac001a-jnx-01.dcn.surf.net", id="uppercase-short"),
        pytest.param("aac001a-jnx-01", "aac001a-jnx-01.dcn.surf.net", id="lowercase-short"),
        pytest.param("  Aac001A-Jnx-01.DCN.surf.NET\n", "aac001a-jnx-01.dcn.surf.net", id="mixed-case-fqdn-whitespace"),
        pytest.param("dup-jnx-01", None, id="ambiguous-short-never-picked"),
        pytest.param("dup-jnx-01.other.surf.net", "dup-jnx-01.other.surf.net", id="ambiguous-short-full-fqdn-ok"),
        pytest.param("aac001a-jnx", None, id="prefix-is-not-a-match"),
        pytest.param("lw003a-mer01-dist-03", None, id="unmanaged-switch-not-fuzzy-resolved"),
    ],
)
def test_resolve_device(device, expected):
    assert server.resolve_device(device, FLEET) == expected


@pytest.mark.parametrize(
    "targets,device,must_contain,must_not_contain,max_suggestions",
    [
        pytest.param(
            FLEET, "nope", ["unknown device 'nope': not managed by this server", "list_devices"],
            ["lw003a-jnx-03", "aac001a-jnx-01"], 0, id="unknown-short-error-no-full-list",
        ),
        pytest.param(
            FLEET, "aac001a-jnx-1", ["did you mean:", "aac001a-jnx-01.dcn.surf.net"],
            ["dup-jnx-01"], 5, id="near-miss-suggested",
        ),
        pytest.param(
            FLEET, "dup-jnx-01", ["dup-jnx-01.dcn.surf.net", "dup-jnx-01.other.surf.net"],
            [], 5, id="ambiguous-lists-candidates",
        ),
        pytest.param(
            CROWDED, "cr0xxa-jnx-01", ["did you mean:"],
            [], 5, id="suggestions-capped-at-5",
        ),
    ],
)
def test_run_show_command_unknown_device(monkeypatch, targets, device, must_contain, must_not_contain, max_suggestions):
    monkeypatch.setattr(server, "fetch_targets", lambda: targets)
    monkeypatch.setattr(server, "run_show", lambda *a: pytest.fail("must not run on an unresolved device"))
    out = server.run_show_command(device, "show version")
    assert all(text in out for text in must_contain)
    assert not any(text in out for text in must_not_contain)
    assert out.count(".dcn.surf.net") + out.count(".other.surf.net") <= max_suggestions
    assert len(out) < 600


@pytest.mark.parametrize(
    "device",
    [
        pytest.param("r1.surf.net", id="exact-fqdn"),
        pytest.param("R1", id="uppercase-short"),
        pytest.param(" R1.Surf.NET ", id="mixed-case-fqdn"),
    ],
)
def test_run_show_command_resolves_device(monkeypatch, device):
    monkeypatch.setattr(server, "fetch_targets", lambda: {"r1.surf.net": "r1.surf.net"})
    monkeypatch.setattr(server, "run_show", lambda fqdn, cmd: f"OUT {fqdn} {cmd}")
    assert server.run_show_command(device, "show version") == "OUT r1.surf.net show version"


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
