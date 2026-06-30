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
