# CLAUDE.md

Read-only JUNOS troubleshooting MCP server.

## Invariant (do not break)
Read-only only. NEVER add a configuration/write tool. Every device command goes
through `validate_show_command()`, which allows only `show` commands and blocks
`| save` / `| append` / `| tee` / `| load`.

## Layout
- `src/junos_mcp_server/server.py` — the whole server: `Settings`
  (pydantic-settings `BaseSettings`, env vars via `validation_alias`) +
  `settings()`, `fetch_targets()` (cached), the `ShowCommand` pydantic model +
  `validate_show_command()`, `run_show()` (PyEZ), and FastMCP tools
  `list_devices` / `run_show_command`.
- `tests/test_server.py` — parametrized unit tests for the command validator,
  target parsing, and tool dispatch. (Settings is plain pydantic — not retested.)

## Targets source
`GET {ORCHESTRATOR_URL}/api/surf/subscriptions/gnmi/targets` (Basic Auth). The
`address` field is `fqdn:32767` (gNMI port) — we use the FQDN only and connect
NETCONF on `JUNOS_SSH_PORT` (830).

Dev mode: `JUNOS_DEV_MODE=1` + `JUNOS_DEV_TARGETS` (JSON list of node hostnames)
makes `fetch_targets()` return `{node: node}` and skip the orchestrator. A
`model_validator` enforces the mode rules: dev needs non-empty `JUNOS_DEV_TARGETS`;
prod needs `ORCHESTRATOR_URL` + `GNMIC_HTTP_BASIC_*`. SSH creds required in both.

## Test
`uv run --extra dev pytest -v`

## Style
Prefer comprehensions / `itertools` / `next(..., None)` over imperative loops,
`break`, `continue`. Use `@pytest.mark.parametrize` for data-varying tests.
