# JUNOS MCP Server — Design

**Date:** 2026-06-29
**Status:** Approved, pending implementation plan

## Purpose

A read-only JUNOS troubleshooting tool exposed over MCP. It dynamically
discovers device targets from the SURF orchestrator's Basic-Auth-protected
gNMI-targets endpoint, then runs **`show` commands only** against those devices
over NETCONF (PyEZ). Used by an LLM (Claude) as a troubleshooting assistant.

Read-only is guaranteed by construction: no configuration/write tool exists in
the server, and a command validator rejects anything that is not a `show`
command.

## Source endpoint (already exists in the orchestrator)

- `GET {ORCHESTRATOR_URL}/api/surf/subscriptions/gnmi/targets`
- HTTP Basic Auth, credentials `GNMIC_HTTP_BASIC_USER` / `GNMIC_HTTP_BASIC_PASSWORD`
  (same env var names the orchestrator uses).
- Response shape:
  ```json
  {
    "ledn002a-jnx-01-vtb.dcn.surf.net": {
      "address": "ledn002a-jnx-01-vtb.dcn.surf.net:32767",
      "subscriptions": ["..."]
    }
  }
  ```
- The `:32767` port in `address` is the **gNMI telemetry** port and is
  irrelevant to `show` commands. We use the FQDN only and connect over our own
  NETCONF port.

## Architecture

Single module `src/junos_mcp_server/server.py` (~130 lines). Dependencies:
`mcp`, `junos-eznc` (PyEZ), `httpx`. Everything else is stdlib.

```
MCP client (Claude)
   │  list_devices()            ┌───────────────────────────────┐
   ├───────────────────────────▶│ fetch_targets(): httpx GET     │
   │                            │  + BasicAuth → orchestrator    │
   │                            │  strip :32767 → {name: fqdn}   │
   │                            │  cached 60s                    │
   │  run_show_command(dev,cmd) │ validate_show_command(cmd) ◀── trust boundary
   ├───────────────────────────▶│ PyEZ Device(fqdn, port=830)    │
   │◀──────── text ─────────────│  .open() → dev.cli() → text    │
                                └───────────────────────────────┘
```

## Components

### `settings()` — config from environment
Frozen dataclass read from `os.environ` (no `pydantic-settings` dependency):

| Env var | Purpose | Default |
|---|---|---|
| `ORCHESTRATOR_URL` | base URL of orchestrator | none (required) |
| `GNMIC_HTTP_BASIC_USER` | targets-endpoint Basic Auth user | none (required) |
| `GNMIC_HTTP_BASIC_PASSWORD` | targets-endpoint Basic Auth password | none (required) |
| `JUNOS_SSH_USER` | device login user (read-only service account) | none (required) |
| `JUNOS_SSH_PASSWORD` | device login password | none (required) |
| `JUNOS_SSH_PORT` | NETCONF port | `830` |

Missing required vars → clear startup error naming the missing var.

### `fetch_targets() -> dict[str, str]`
Maps device name → FQDN (gNMI port stripped). `httpx.get` with `httpx.BasicAuth`.
Process-wide cache with a 60-second TTL.
`# ponytail: process-wide cache, fine for a single-user troubleshooting tool`

### `validate_show_command(cmd: str) -> str` — security invariant
- Normalize (strip leading/trailing whitespace, collapse internal runs is not
  required; just strip).
- First whitespace-delimited token must equal `show` (case-sensitive JUNOS
  operational keyword). Reject empty input.
- Reject if any pipe segment starts with `save` or `load` (those write files on
  the device). All other pipe modifiers (`match`, `count`, `display`, etc.) are
  read-only and allowed.
- Returns the normalized command on success; raises `ValueError` with a message
  ("only show commands are allowed") on rejection.
This is the one piece of non-trivial security logic and is fully unit-tested.

### `run_show(fqdn: str, cmd: str) -> str`
`Device(host=fqdn, user=..., passwd=..., port=...)`, `.open()`,
`dev.cli(cmd, warning=False)`, return text, `.close()` in a `finally`.
PyEZ connection/auth/timeout exceptions are caught and returned as a readable
error string (no stack trace leaked to the LLM).

### MCP tools (FastMCP)
- `list_devices() -> list[str]` — device names from `fetch_targets()`.
- `run_show_command(device: str, command: str) -> str` — validate command,
  resolve device→FQDN (unknown device → error listing valid names), run, return
  text.

No refresh tool — the 60s TTL covers it.

## Error handling

| Failure | Behaviour |
|---|---|
| Orchestrator 401 | message: "check GNMIC_HTTP_BASIC_* credentials" |
| Orchestrator unreachable | message naming the URL |
| Unknown device name | error listing valid device names |
| Non-`show` command | `ValueError`: "only show commands are allowed" |
| Device unreachable / auth fail / timeout | readable error string, not a traceback |

## Testing

`tests/test_server.py`, `@pytest.mark.parametrize` (per project style rules):
- `validate_show_command`: accepts `show interfaces`, `show route table x`,
  `show foo | match bar`; rejects `request system reboot`, `configure`,
  `clear interfaces`, `""`, `show foo | save /tmp/x`, `  show version ` (leading
  space ok after strip).
- target parsing: `"host:32767"` → `"host"`, plain `"host"` → `"host"`.

Live device/orchestrator calls are not unit-tested (require real network).

## Packaging / running

`pyproject.toml`:
- `requires-python = ">=3.10,<3.13"` (PyEZ wheel constraint; `uv` provisions a
  compatible interpreter automatically even on a 3.14 host).
- `dependencies = ["mcp", "junos-eznc", "httpx"]`.
- `[project.scripts] junos-mcp-server = "junos_mcp_server.server:main"`.
- `main()` runs FastMCP over stdio.

Run:
```bash
uvx --from . junos-mcp-server          # local checkout
uvx --from git+<repo-url> junos-mcp-server
```

MCP client config (stdio) and the full env-var list go in `README.md`.
`CLAUDE.md` documents: the show-only invariant, module layout, how to run tests,
and the project Python style rules.

## Out of scope (YAGNI — add when a real need appears)

- Structured RPC / XML/JSON output (text only for now).
- Separate `refresh_targets` tool.
- Per-device or multi-account credentials.
- `.env` file loading (env comes from the MCP client's `env` block or shell).
- SSH key / jump-host auth (chosen: username+password; revisit if devices move
  behind a bastion).
