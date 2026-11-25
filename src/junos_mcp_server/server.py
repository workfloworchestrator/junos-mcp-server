import difflib
import itertools
import time

import httpx
from jnpr.junos import Device
from jnpr.junos.exception import ConnectError
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


_CACHE: dict = {"targets": None, "at": 0.0}
_TTL = 60.0

mcp = FastMCP("junos-mcp-server")


class Settings(BaseSettings):
    """Config from environment.

    Device login (ssh_*) is always required. In development mode
    (JUNOS_DEV_MODE=1) the orchestrator is bypassed and JUNOS_DEV_TARGETS — a
    JSON list of node hostnames — is served as the device list; otherwise the
    orchestrator URL and Basic-Auth credentials are required."""

    ssh_user: str = Field(min_length=1, validation_alias="JUNOS_SSH_USER")
    ssh_password: str = Field(min_length=1, validation_alias="JUNOS_SSH_PASSWORD")
    ssh_port: int = Field(default=830, validation_alias="JUNOS_SSH_PORT")

    dev_mode: bool = Field(default=False, validation_alias="JUNOS_DEV_MODE")
    dev_targets: list[str] = Field(default_factory=list, validation_alias="JUNOS_DEV_TARGETS")

    orchestrator_url: str = Field(default="", validation_alias="ORCHESTRATOR_URL")
    basic_user: str = Field(default="", validation_alias="GNMIC_HTTP_BASIC_USER")
    basic_password: str = Field(default="", validation_alias="GNMIC_HTTP_BASIC_PASSWORD")

    @field_validator("orchestrator_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_mode(self) -> "Settings":
        if self.dev_mode and not self.dev_targets:
            raise ValueError("JUNOS_DEV_MODE is set but JUNOS_DEV_TARGETS is empty")
        if not self.dev_mode and not (self.orchestrator_url and self.basic_user and self.basic_password):
            raise ValueError(
                "ORCHESTRATOR_URL, GNMIC_HTTP_BASIC_USER and GNMIC_HTTP_BASIC_PASSWORD "
                "are required unless JUNOS_DEV_MODE is set"
            )
        return self


def settings() -> Settings:
    return Settings()


_WRITE_PIPE_HEADS = {"save", "append", "tee", "load"}


class ShowCommand(BaseModel):
    """A validated read-only JUNOS 'show' command. Enforces the read-only
    invariant: first token must be 'show', and no pipe segment may invoke a
    modifier that writes on the device (save/append/tee/load)."""

    command: str

    @field_validator("command")
    @classmethod
    def _must_be_read_only_show(cls, value: str) -> str:
        cmd = value.strip()
        tokens = cmd.split()
        if not tokens or tokens[0] != "show":
            raise ValueError("only show commands are allowed")
        pipe_heads = (seg.split()[:1] for seg in cmd.split("|")[1:] if seg.split())
        if any(h[0].lower() in _WRITE_PIPE_HEADS for h in pipe_heads):
            raise ValueError(
                "only show commands are allowed (no '| save' / '| append' / '| tee' / '| load')"
            )
        return cmd


def validate_show_command(command: str) -> str:
    """Return the normalized command if read-only; raise pydantic ValidationError
    (a ValueError subclass) whose message contains 'only show commands' otherwise."""
    return ShowCommand(command=command).command


def _host_only(address: str) -> str:
    return address.split(":", 1)[0]


def fetch_targets() -> dict[str, str]:
    cfg = settings()
    if cfg.dev_mode:
        return {node: node for node in cfg.dev_targets}
    # ponytail: process-wide 60s cache, fine for a single-user troubleshooting tool
    if _CACHE["targets"] is not None and (time.monotonic() - _CACHE["at"]) < _TTL:
        return _CACHE["targets"]
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


_MAX_SUGGESTIONS = 5


def _short_name(fqdn: str) -> str:
    return fqdn.split(".", 1)[0]


def resolve_device(device: str, targets: dict[str, str]) -> str | None:
    """Return the key in `targets` that `device` unambiguously names, else None.

    Case-insensitive and whitespace-tolerant. An exact (FQDN) match wins;
    otherwise a short hostname matches only if it equals the part before the
    first dot of exactly one known FQDN. Never guesses: no fuzzy matching and
    no picking between several candidates."""
    name = device.strip().lower()
    exact = [key for key in targets if key.lower() == name]
    candidates = exact or [key for key in targets if _short_name(key.lower()) == name]
    return candidates[0] if len(candidates) == 1 else None


def unknown_device_message(device: str, targets: dict[str, str]) -> str:
    """Short miss message: a few close matches (as FQDNs), never the full device list."""

    def short(key: str) -> str:
        return _short_name(key.lower())

    by_short = {
        name: list(keys)
        for name, keys in itertools.groupby(sorted(targets, key=short), key=short)
    }
    close = difflib.get_close_matches(
        _short_name(device.strip().lower()), list(by_short), n=_MAX_SUGGESTIONS
    )
    suggestions = list(
        itertools.islice(
            itertools.chain.from_iterable(by_short[n] for n in close), _MAX_SUGGESTIONS
        )
    )
    hint = f" did you mean: {', '.join(suggestions)}." if suggestions else ""
    return (
        f"unknown device '{device}': not managed by this server.{hint}"
        " Call list_devices to see the managed devices."
    )


@mcp.tool()
def list_devices() -> list[str]:
    """List the devices this server can reach, as lowercase FQDNs (e.g. 'aac001a-jnx-01.dcn.surf.net').

    The list comes from the orchestrator's gNMI targets and contains only Juniper
    routers. Other equipment (DCN/management switches, optical shelves) is not
    managed by this server and cannot be reached."""
    return sorted(fetch_targets())


@mcp.tool()
def run_show_command(device: str, command: str) -> str:
    """Run a read-only JUNOS 'show' command on a Juniper router and return its text output.

    `device` is the FQDN (e.g. 'aac001a-jnx-01.dcn.surf.net') or the short
    hostname (e.g. 'aac001a-jnx-01'), in any case; a short hostname must match
    exactly one device. Only Juniper routers from the orchestrator's gNMI targets
    are reachable (not DCN/management switches or optical shelves); call
    list_devices to see them. An unknown name returns a short error with at most
    a few 'did you mean' suggestions, never the full list."""
    command = validate_show_command(command)
    targets = fetch_targets()
    match resolve_device(device, targets):
        case None:
            return unknown_device_message(device, targets)
        case key:
            return run_show(targets[key], command)


def main() -> None:
    mcp.run()
