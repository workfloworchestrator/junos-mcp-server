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
| `ORCHESTRATOR_URL` | yes¹ | — | orchestrator base URL, e.g. `https://api.automation.surf.net` |
| `GNMIC_HTTP_BASIC_USER` | yes¹ | — | Basic Auth user for the targets endpoint |
| `GNMIC_HTTP_BASIC_PASSWORD` | yes¹ | — | Basic Auth password for the targets endpoint |
| `JUNOS_SSH_USER` | yes | — | read-only device login user |
| `JUNOS_SSH_PASSWORD` | yes | — | device login password |
| `JUNOS_SSH_PORT` | no | `830` | NETCONF port |
| `JUNOS_DEV_MODE` | no | `0` | development mode — serve `JUNOS_DEV_TARGETS` instead of querying the orchestrator |
| `JUNOS_DEV_TARGETS` | dev² | `[]` | JSON list of node hostnames, e.g. `["r1.lab.net","r2.lab.net"]` |

¹ Not required when `JUNOS_DEV_MODE` is set. &nbsp; ² Required (non-empty) when `JUNOS_DEV_MODE` is set.

## Development mode

Set `JUNOS_DEV_MODE=1` and `JUNOS_DEV_TARGETS` to a JSON list of your own nodes
to bypass the orchestrator entirely — `list_devices()` then returns exactly that
list and `run_show_command` connects to those hostnames. SSH credentials are
still required; orchestrator/Basic-Auth vars are not.

```bash
JUNOS_DEV_MODE=1 JUNOS_DEV_TARGETS='["r1.lab.net","r2.lab.net"]' \
  JUNOS_SSH_USER=ro JUNOS_SSH_PASSWORD=... uvx --from . junos-mcp-server
```

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
