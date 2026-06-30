import os
import time
import httpx
from dataclasses import dataclass


_CACHE: dict = {"targets": None, "at": 0.0}
_TTL = 60.0


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


def validate_show_command(command: str) -> str:
    cmd = command.strip()
    tokens = cmd.split()
    if not tokens or tokens[0] != "show":
        raise ValueError("only show commands are allowed")
    # block pipe modifiers that write on the device; match/count/display etc. are fine
    pipe_heads = (seg.split()[:1] for seg in cmd.split("|")[1:] if seg.split())
    if next((h for h in pipe_heads if h[0] in ("save", "load")), None) is not None:
        raise ValueError("only show commands are allowed (no '| save' / '| load')")
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
    targets = {name: _host_only(entry["address"]) for name, entry in resp.json().items()}
    _CACHE.update(targets=targets, at=time.monotonic())
    return targets
