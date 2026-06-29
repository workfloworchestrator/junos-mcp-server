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
