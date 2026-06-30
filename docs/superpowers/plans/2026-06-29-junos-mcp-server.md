# JUNOS MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only JUNOS troubleshooting MCP server that discovers devices from the SURF orchestrator's Basic-Auth gNMI-targets endpoint and runs `show` commands only, over NETCONF/PyEZ.

**Architecture:** One module `src/junos_mcp_server/server.py`: env-based `settings()`, a cached `fetch_targets()` (httpx + Basic Auth), a `validate_show_command()` security gate, a `run_show()` PyEZ wrapper, and two FastMCP tools (`list_devices`, `run_show_command`) run over stdio. No write/config tool exists — read-only by construction.

**Tech Stack:** Python 3.10–3.12, `mcp` (FastMCP), `junos-eznc` (PyEZ), `httpx`, `pytest`. Packaged for `uvx`.

## Global Constraints

- `requires-python = ">=3.10,<3.13"` (PyEZ wheel constraint; `uv` provisions a compatible interpreter even on a 3.14 host).
- Dependencies limited to `mcp`, `junos-eznc`, `httpx` (runtime) + `pytest` (dev). No `pydantic-settings`, no `.env` loader.
- Read-only only: never add a configuration/write tool. The sole command path goes through `validate_show_command`.
- Reuse orchestrator env-var names for the targets call: `GNMIC_HTTP_BASIC_USER`, `GNMIC_HTTP_BASIC_PASSWORD`.
- Targets endpoint: `GET {ORCHESTRATOR_URL}/api/surf/subscriptions/gnmi/targets`, response `{name: {"address": "fqdn:32767", ...}}` — strip the port, use FQDN.
- Python style: prefer comprehensions/`itertools`/`next(...,None)` over imperative loops/`break`/`continue`; `@pytest.mark.parametrize` for data-varying tests.

---

### Task 1: Project scaffold + `settings()`

**Files:**
- Create: `pyproject.toml`
- Create: `src/junos_mcp_server/__init__.py` (empty)
- Create: `src/junos_mcp_server/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `Settings` (frozen dataclass with fields `orchestrator_url: str`, `basic_user: str`, `basic_password: str`, `ssh_user: str`, `ssh_password: str`, `ssh_port: int`); `settings() -> Settings`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "junos-mcp-server"
version = "0.1.0"
description = "Read-only JUNOS troubleshooting MCP server with dynamic targets from the SURF orchestrator"
requires-python = ">=3.10,<3.13"
dependencies = ["mcp", "junos-eznc", "httpx"]

[project.scripts]
junos-mcp-server = "junos_mcp_server.server:main"

[project.optional-dependencies]
dev = ["pytest"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/junos_mcp_server"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_server.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server.py -v`
Expected: FAIL (`AttributeError`/`ImportError`: `settings` not defined)

- [ ] **Step 4: Write minimal implementation**

```python
# src/junos_mcp_server/server.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git init -q && git add -A && git commit -m "feat: project scaffold + env settings"
```
(If the dir is already a git repo, drop `git init -q &&`.)

---

### Task 2: `validate_show_command()` — security gate

**Files:**
- Modify: `src/junos_mcp_server/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `validate_show_command(command: str) -> str` — returns the stripped command if it is a `show` command with no write pipe modifier; raises `ValueError("only show commands are allowed")` otherwise.

- [ ] **Step 1: Write the failing parametrized test**

```python
# add to tests/test_server.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server.py -k validate -v`
Expected: FAIL (`validate_show_command` not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/junos_mcp_server/server.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_server.py -k validate -v`
Expected: PASS (all parametrized cases pass)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: show-only command validator"
```

---

### Task 3: `fetch_targets()` — dynamic device discovery

**Files:**
- Modify: `src/junos_mcp_server/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `settings()`.
- Produces: `_host_only(address: str) -> str` (strips `:port`); `fetch_targets() -> dict[str, str]` (name → FQDN), cached 60s in module-level `_CACHE`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_server.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server.py -k "fetch or host_only" -v`
Expected: FAIL (`_host_only`/`fetch_targets` not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# add near the top imports of src/junos_mcp_server/server.py
import time
import httpx

_CACHE: dict = {"targets": None, "at": 0.0}
_TTL = 60.0


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_server.py -k "fetch or host_only" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: fetch_targets from orchestrator gnmi targets endpoint"
```

---

### Task 4: `run_show()` + FastMCP tools + `main()`

**Files:**
- Modify: `src/junos_mcp_server/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `settings()`, `fetch_targets()`, `validate_show_command()`.
- Produces: `run_show(fqdn: str, command: str) -> str`; FastMCP tools `list_devices() -> list[str]` and `run_show_command(device: str, command: str) -> str`; `main() -> None`.

- [ ] **Step 1: Write the failing test** (tool dispatch logic, PyEZ mocked)

```python
# add to tests/test_server.py
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
```

Note: the released `mcp` package's `@mcp.tool()` returns the original function unchanged, so the decorated tools are callable directly in tests (verified: no `.fn` wrapper).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_server.py -k "run_show_command or list_devices" -v`
Expected: FAIL (tools not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# add to imports
from jnpr.junos import Device
from jnpr.junos.exception import ConnectError
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("junos-mcp-server")


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_server.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Smoke-test imports + decoration succeed**

Run: `uv run python -c "from junos_mcp_server.server import mcp, list_devices, run_show_command, main; print('ok')"`
Expected: prints `ok` (imports resolve, FastMCP instance + tools build without error).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: PyEZ run_show + MCP tools + stdio entrypoint"
```

---

### Task 5: README + CLAUDE.md

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`

**Interfaces:** none (docs).

- [ ] **Step 1: Write `README.md`**

````markdown
# junos-mcp-server

Read-only JUNOS troubleshooting MCP server. Discovers devices dynamically from
the SURF orchestrator's gNMI-targets endpoint and runs **`show` commands only**
over NETCONF (PyEZ). It has no configuration/write capability by design.

## Tools

- `list_devices()` — device names from the orchestrator.
- `run_show_command(device, command)` — runs a `show` command; rejects anything else.

## Environment

| Var | Required | Default | Purpose |
|---|---|---|---|
| `ORCHESTRATOR_URL` | yes | — | orchestrator base URL, e.g. `https://api.automation.surf.net` |
| `GNMIC_HTTP_BASIC_USER` | yes | — | Basic Auth user for the targets endpoint |
| `GNMIC_HTTP_BASIC_PASSWORD` | yes | — | Basic Auth password for the targets endpoint |
| `JUNOS_SSH_USER` | yes | — | read-only device login user |
| `JUNOS_SSH_PASSWORD` | yes | — | device login password |
| `JUNOS_SSH_PORT` | no | `830` | NETCONF port |

## Run

```bash
uvx --from . junos-mcp-server                 # from a local checkout
uvx --from git+<repo-url> junos-mcp-server    # from git
```

## MCP client config (stdio)

```json
{
  "mcpServers": {
    "junos": {
      "command": "uvx",
      "args": ["--from", "git+<repo-url>", "junos-mcp-server"],
      "env": {
        "ORCHESTRATOR_URL": "https://api.automation.surf.net",
        "GNMIC_HTTP_BASIC_USER": "gnmic",
        "GNMIC_HTTP_BASIC_PASSWORD": "...",
        "JUNOS_SSH_USER": "...",
        "JUNOS_SSH_PASSWORD": "..."
      }
    }
  }
}
```

Requires NETCONF enabled on devices (`set system services netconf ssh`).
````

- [ ] **Step 2: Write `CLAUDE.md`**

```markdown
# CLAUDE.md

Read-only JUNOS troubleshooting MCP server.

## Invariant (do not break)
Read-only only. NEVER add a configuration/write tool. Every device command goes
through `validate_show_command()`, which allows only `show` commands and blocks
`| save` / `| load`.

## Layout
- `src/junos_mcp_server/server.py` — the whole server: `settings()`,
  `fetch_targets()` (cached), `validate_show_command()`, `run_show()` (PyEZ),
  and FastMCP tools `list_devices` / `run_show_command`.
- `tests/test_server.py` — parametrized unit tests for the pure logic.

## Targets source
`GET {ORCHESTRATOR_URL}/api/surf/subscriptions/gnmi/targets` (Basic Auth). The
`address` field is `fqdn:32767` (gNMI port) — we use the FQDN only and connect
NETCONF on `JUNOS_SSH_PORT` (830).

## Test
`uv run --extra dev pytest -v`

## Style
Prefer comprehensions / `itertools` / `next(..., None)` over imperative loops,
`break`, `continue`. Use `@pytest.mark.parametrize` for data-varying tests.
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "docs: README + CLAUDE.md"
```

---

## Self-Review

- **Spec coverage:** settings (T1), validator (T2), fetch_targets+port strip+cache (T3), run_show+tools+main+stdio+packaging (T1 pyproject/T4), errors (T3/T4), tests parametrized (T2/T3), README+CLAUDE.md (T5), uvx entry point (T1). All spec sections mapped.
- **Placeholders:** none — every code/doc step is concrete. `<repo-url>` in docs is a genuine user-supplied value, not a plan gap.
- **Type consistency:** `settings()→Settings`, `fetch_targets()→dict[str,str]`, `validate_show_command()→str`, `run_show(fqdn,command)→str`, tools accessed via `.fn` in tests — consistent across tasks.
