---
title: MCP Management Tools
parent: Reference
nav_order: 1
---

# MCP Management Tools

MCPBox exposes 28 management tools with the `mcpbox_` prefix. These are discovered automatically by any connected MCP client.

## Server Management

| Tool | Description |
|------|-------------|
| `mcpbox_list_servers` | List all servers with status and tool counts |
| `mcpbox_get_server` | Get details for a specific server |
| `mcpbox_create_server` | Create a new server |
| `mcpbox_delete_server` | Delete a server and all its tools |
| `mcpbox_start_server` | Start a server (register tools with sandbox) |
| `mcpbox_stop_server` | Stop a server (unregister tools) |
| `mcpbox_get_server_modules` | Get the global Python module whitelist |

## Tool Management

| Tool | Description |
|------|-------------|
| `mcpbox_list_tools` | List all tools in a server |
| `mcpbox_get_tool` | Get tool details including source code |
| `mcpbox_create_tool` | Create a new tool (draft status) |
| `mcpbox_update_tool` | Update a tool's code or description |
| `mcpbox_delete_tool` | Delete a tool |

## Versioning

| Tool | Description |
|------|-------------|
| `mcpbox_list_tool_versions` | List a tool's version history |
| `mcpbox_rollback_tool` | Roll back to a previous version |

## Development & Testing

| Tool | Description |
|------|-------------|
| `mcpbox_test_code` | Test a saved tool by running its current code against the sandbox |
| `mcpbox_validate_code` | Check Python syntax and structure |

## Server Secrets

| Tool | Description |
|------|-------------|
| `mcpbox_create_server_secret` | Create a secret placeholder (admin sets the value in the UI) |
| `mcpbox_list_server_secrets` | List secret key names for a server (no values) |

## Approval Workflow

| Tool | Description |
|------|-------------|
| `mcpbox_request_publish` | Submit a draft tool for admin approval |
| `mcpbox_request_module` | Request a Python module to be whitelisted |
| `mcpbox_request_network_access` | Request network access to an external host |
| `mcpbox_get_tool_status` | Get approval status and pending requests |
| `mcpbox_list_pending_requests` | List all pending approval requests |

## External MCP Sources

| Tool | Description |
|------|-------------|
| `mcpbox_add_external_source` | Add an external MCP server as a tool source |
| `mcpbox_list_external_sources` | List all configured external MCP sources for a server |
| `mcpbox_discover_external_tools` | Connect to an external source and discover available tools |
| `mcpbox_import_external_tools` | Import selected tools from an external source |

## Observability

| Tool | Description |
|------|-------------|
| `mcpbox_get_tool_logs` | Get recent execution logs for a tool |

---

## Tool Code Requirements

All tools use Python with an `async def main()` function:

```python
async def main(city: str) -> dict:
    """Get weather for a city."""
    resp = await http.get(f"https://api.example.com/weather?q={city}")
    return resp.json()
```

- Parameters of `main()` become the tool's input schema
- The return value becomes the tool's output
- Type hints and docstrings are used for schema generation

### Available Globals

| Global | Description |
|--------|-------------|
| `http` | SSRF-protected HTTP client (`await http.get()`, `http.post()`, etc.) |
| `json` | The `json` module |
| `datetime` | The `datetime` module |
| `arguments` | Dict of input arguments |
| `secrets` | Read-only dict of server secrets |

### Module Whitelist

Tools run in a sandboxed environment with restricted imports.

**Allowed by default:**

| Category | Modules |
|----------|---------|
| Data formats | `json`, `base64`, `binascii`, `html` |
| Date/Time | `datetime`, `calendar`, `zoneinfo` |
| Math | `math`, `cmath`, `decimal`, `fractions`, `statistics` |
| Text | `regex`, `string`, `textwrap`, `difflib` |
| URL parsing | `urllib.parse` |
| Data structures | `collections`, `itertools`, `functools`, `operator` |
| Types | `typing`, `dataclasses`, `enum`, `uuid`, `copy` |
| Hashing | `hashlib`, `hmac` |

**Always forbidden:** `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `pickle`, `marshal`, `socket`, `inspect`, `gc`, `builtins`

Need a module that's not on the list? The LLM can request it with `mcpbox_request_module`, and you approve it in the admin UI.

### Sandbox Limits

| Limit | Value |
|-------|-------|
| Memory | 256 MB |
| CPU time | 60 seconds |
| Execution timeout | 30 seconds (configurable up to 300s) |
| Code size | 100 KB |
| Stdout capture | 10 KB |
| File descriptors | 64 |
