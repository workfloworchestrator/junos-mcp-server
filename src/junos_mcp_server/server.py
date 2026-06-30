import os
import time
import httpx
from dataclasses import dataclass
from jnpr.junos import Device
from jnpr.junos.exception import ConnectError
from mcp.server.fastmcp import FastMCP


_CACHE: dict = {"targets": None, "at": 0.0}
_TTL = 60.0

mcp = FastMCP("junos-mcp-server")


@dataclass(frozen=True)
class Settings:
    orchestrator_url: str
    basic_user: str
    basic_password: str
    ssh_user: str
    ssh_password: str
    ssh_port: int


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def settings() -> Settings:
    return Settings(
        orchestrator_url=_require("ORCHESTRATOR_URL").rstrip("/"),
        basic_user=_require("GNMIC_HTTP_BASIC_USER"),
        basic_password=_require("GNMIC_HTTP_BASIC_PASSWORD"),
        ssh_user=_require("JUNOS_SSH_USER"),
        ssh_password=_require("JUNOS_SSH_PASSWORD"),
        ssh_port=int(os.environ.get("JUNOS_SSH_PORT", "830")),
    )


_WRITE_PIPE_HEADS = {"save", "append", "tee", "load"}


def validate_show_command(command: str) -> str:
    """Return the command if it is a read-only 'show'; raise ValueError otherwise.

    Enforces the read-only invariant: first token must be 'show', and no pipe
    segment may invoke a modifier that writes on the device (save/append/tee/load).
    """
    cmd = command.strip()
    tokens = cmd.split()
    if not tokens or tokens[0] != "show":
        raise ValueError("only show commands are allowed")
    pipe_heads = (seg.split()[:1] for seg in cmd.split("|")[1:] if seg.split())
    if any(h[0].lower() in _WRITE_PIPE_HEADS for h in pipe_heads):
        raise ValueError(
            "only show commands are allowed (no '| save' / '| append' / '| tee' / '| load')"
        )
    return cmd


def _host_only(address: str) -> str:
    return address.split(":", 1)[0]


def fetch_targets() -> dict[str, str]:
    # ponytail: process-wide 60s cache, fine for a single-user troubleshooting tool
    if _CACHE["targets"] is not None and (time.monotonic() - _CACHE["at"]) < _TTL:
        return _CACHE["targets"]
    cfg = settings()
    url = f"{cfg.orchestrator_url}/api/surf/subscriptions/gnmi/targets"
    try:
        resp = httpx.get(
            url, auth=httpx.BasicAuth(cfg.basic_user, cfg.basic_password), timeout=10.0
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            raise RuntimeError(
                "targets endpoint returned 401 — check GNMIC_HTTP_BASIC_* credentials"
            ) from exc
        raise RuntimeError(f"targets endpoint error {exc.response.status_code} at {url}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"cannot reach targets endpoint at {url}: {exc}") from exc
    try:
        targets = {name: _host_only(entry["address"]) for name, entry in resp.json().items()}
    except (ValueError, KeyError, AttributeError) as exc:
        raise RuntimeError(f"unexpected targets response shape from {url}: {exc}") from exc
    _CACHE.update(targets=targets, at=time.monotonic())
    return targets


def run_show(fqdn: str, command: str) -> str:
    cfg = settings()
    dev = Device(host=fqdn, user=cfg.ssh_user, passwd=cfg.ssh_password, port=cfg.ssh_port)
    try:
        dev.open()
        return dev.cli(command, warning=False)
    except ConnectError as exc:
        return f"could not connect to {fqdn}: {exc}"
    except Exception as exc:  # ponytail: PyEZ raises many subclasses; return readable text, never a traceback
        return f"error running '{command}' on {fqdn}: {exc}"
    finally:
        if dev.connected:
            dev.close()


@mcp.tool()
def list_devices() -> list[str]:
    """List JUNOS device names discovered from the orchestrator gNMI targets endpoint."""
    return sorted(fetch_targets())


@mcp.tool()
def run_show_command(device: str, command: str) -> str:
    """Run a read-only JUNOS 'show' command on a device and return its text output."""
    command = validate_show_command(command)
    targets = fetch_targets()
    fqdn = targets.get(device)
    if fqdn is None:
        return f"unknown device '{device}'. Known devices: {', '.join(sorted(targets))}"
    return run_show(fqdn, command)


def main() -> None:
    mcp.run()
