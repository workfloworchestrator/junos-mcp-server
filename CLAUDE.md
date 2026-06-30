# CLAUDE.md

Read-only JUNOS troubleshooting MCP server.

## Invariant (do not break)
Read-only only. NEVER add a configuration/write tool. Every device command goes
through `validate_show_command()`, which allows only `show` commands and blocks
`| save` / `| append` / `| tee` / `| load`.

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
