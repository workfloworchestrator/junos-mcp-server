import os
from dataclasses import dataclass


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
