# MCPbox Management Tools

MCPbox exposes management functions as MCP tools, allowing external LLMs (like Claude Code) to create, configure, and manage MCP servers and tools programmatically.

## Overview

Instead of requiring users to configure an API key for embedded LLM features, MCPbox exposes its management operations as MCP tools. This allows users to leverage their existing Claude access (via Claude Code, Claude Web, etc.) to build and manage their MCP infrastructure.

**Important**: Tools created via these MCP tools start in **draft** status and must go through an admin approval workflow before becoming available.

## Available Tools

All management tools use the `mcpbox_` prefix to distinguish them from user-created tools.

### Server Management

| Tool | Description |
|------|-------------|
| `mcpbox_list_servers` | List all MCP servers with their status and tool counts |
| `mcpbox_get_server` | Get detailed information about a specific server |
| `mcpbox_create_server` | Create a new MCP server |
| `mcpbox_delete_server` | Delete a server and all its tools |
| `mcpbox_start_server` | Start a server (make tools available) |
| `mcpbox_stop_server` | Stop a server (make tools unavailable) |
| `mcpbox_get_server_modules` | Get globally allowed Python modules |

### Tool Management

| Tool | Description |
|------|-------------|
| `mcpbox_list_tools` | List all tools in a server |
| `mcpbox_get_tool` | Get tool details including Python code |
| `mcpbox_create_tool` | Create a new tool in draft status (Python code) |
| `mcpbox_update_tool` | Update an existing tool |
| `mcpbox_delete_tool` | Delete a tool |

### Versioning

| Tool | Description |
|------|-------------|
| `mcpbox_list_tool_versions` | List version history for a tool |
| `mcpbox_rollback_tool` | Rollback a tool to a previous version |

### Development & Testing

| Tool | Description |
|------|-------------|
| `mcpbox_test_code` | Test Python code execution in the sandbox (supports async) |
| `mcpbox_validate_code` | Validate Python code syntax and structure |

### Server Secrets

| Tool | Description |
|------|-------------|
| `mcpbox_create_server_secret` | Create a secret placeholder (admin sets value in UI) |
| `mcpbox_list_server_secrets` | List secrets for a server (keys only, no values) |

### Approval Workflow

| Tool | Description |
|------|-------------|
| `mcpbox_request_publish` | Request admin approval to publish a draft tool |
| `mcpbox_request_module` | Request a Python module to be whitelisted |
| `mcpbox_request_network_access` | Request network access to an external host |
| `mcpbox_get_tool_status` | Get approval status and pending requests for a tool |
| `mcpbox_list_pending_requests` | List all pending approval requests |

### Observability

| Tool | Description |
|------|-------------|
| `mcpbox_get_tool_logs` | Get recent execution logs for a tool |

## Tool Approval Workflow

Tools are created in **draft** status and must be approved by an admin before they become available for use:

```
1. LLM creates tool with mcpbox_create_tool
   -> Tool is in "draft" status (not visible to other users)

2. LLM tests and validates the tool
   -> mcpbox_test_code, mcpbox_validate_code

3. LLM requests additional modules/network access if needed
   -> mcpbox_request_module, mcpbox_request_network_access

4. LLM requests publish
   -> mcpbox_request_publish (moves to "pending_review")

5. Admin reviews in UI at /approvals
   -> Approves or rejects the tool

6. If approved: Tool becomes available in tools/list
   If rejected: LLM can revise and re-submit
```

## Usage Examples

### Creating a Weather Tool

```
1. Create a server for weather-related tools:
   mcpbox_create_server(name="weather_api", description="Weather data tools")

2. Create a secret placeholder for the API key:
   mcpbox_create_server_secret(
     server_id="<uuid>",
     key_name="OPENWEATHERMAP_API_KEY",
     description="OpenWeatherMap API key for weather data"
   )
   -> Admin sets the actual value in the web UI at /servers/<uuid>

3. Create a tool that fetches weather data using the secret:
   mcpbox_create_tool(
     server_id="<uuid>",
     name="get_current_weather",
     description="Get current weather for a city",
     python_code='''
   async def main(city: str) -> dict:
       """Get current weather for a city using OpenWeatherMap."""
       api_key = secrets["OPENWEATHERMAP_API_KEY"]
       url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
       response = await http.get(url)
       return response.json()
   '''
   )
   -> Tool created in "draft" status

4. Request publish approval:
   mcpbox_request_publish(
     tool_id="<uuid>",
     notes="Weather API tool using OpenWeatherMap, safe for production"
   )

5. After admin approval, start the server:
   mcpbox_start_server(server_id="<uuid>")
```

### Creating a Hash Calculator Tool

```
1. Create the tool:
   mcpbox_create_tool(
     server_id="<uuid>",
     name="calculate_hash",
     description="Calculate SHA256 hash of input text",
     python_code='''
   async def main(text: str) -> dict:
       """Calculate SHA256 hash of the input text."""
       import hashlib
       hash_value = hashlib.sha256(text.encode()).hexdigest()
       return {"hash": hash_value, "algorithm": "sha256"}
   '''
   )

2. Request publish:
   mcpbox_request_publish(tool_id="<uuid>", notes="Simple hash utility")
```

### Testing with Server's Module Configuration

```
# Test Python code using the server's specific module whitelist
mcpbox_test_code(
  code='''
async def main(data: str) -> dict:
    import yaml  # This will fail if yaml is not whitelisted
    parsed = yaml.safe_load(data)
    return {"result": parsed}
''',
  arguments={"data": "key: value"},
  server_id="<uuid>"  # Optional: test with this server's allowed modules
)
```

### Requesting Additional Modules

```
# If your tool needs a module that's not whitelisted:
mcpbox_request_module(
  tool_id="<uuid>",
  module_name="yaml",
  justification="Need to parse YAML configuration files for the config_parser tool"
)

# Request network access to external hosts:
mcpbox_request_network_access(
  tool_id="<uuid>",
  host="api.github.com",
  port=443,
  justification="Need to access GitHub API to fetch repository information"
)
```

### Checking Tool Status

```
# See approval status and any pending requests:
mcpbox_get_tool_status(tool_id="<uuid>")

# Returns:
{
  "tool_id": "...",
  "name": "my_tool",
  "approval_status": "pending_review",
  "publish_notes": "Ready for production use",
  "module_requests": [
    {"module_name": "yaml", "status": "pending", ...}
  ],
  "network_access_requests": [
    {"host": "api.github.com", "status": "approved", ...}
  ]
}
```

## Tool Execution

All tools use Python code with an `async def main()` function. Requirements:
- Must have an `async def main()` function
- Parameters become tool inputs (automatically extracted for input schema)
- Return value becomes tool output
- Available globals:
  - `http` — SSRF-protected `httpx.AsyncClient` (use `await http.get(url)`, etc.)
  - `json` — JSON module
  - `datetime` — datetime module
  - `arguments` — dict of input arguments
  - `secrets` — `MappingProxyType` dict of server secrets (read-only, e.g. `secrets["API_KEY"]`)
- Additional modules can be imported if whitelisted (see `mcpbox_get_server_modules`)
- Each tool invocation is logged (args redacted, results truncated) — viewable via `mcpbox_get_tool_logs`

## Module Whitelist

Python code tools run in a sandboxed environment with restricted module imports:

**Default Allowed Modules:**
- Data formats: `json`, `base64`, `binascii`, `html`
- Date/Time: `datetime`, `calendar`, `zoneinfo`
- Math: `math`, `cmath`, `decimal`, `fractions`, `statistics`
- Text: `regex`, `string`, `textwrap`, `difflib`
- URL parsing: `urllib.parse`
- Data structures: `collections`, `itertools`, `functools`, `operator`
- Types: `typing`, `dataclasses`, `enum`, `uuid`, `copy`
- Hashing: `hashlib`, `hmac`

**Always Forbidden:**
- System access: `os`, `sys`, `subprocess`, `shutil`, `pathlib`
- Code execution: `pickle`, `marshal`, `code`, `ast`
- Network: `socket`, `urllib.request`, `http.client` (use provided `http` client)
- Introspection: `inspect`, `gc`, `builtins`

Use `mcpbox_get_server_modules` to see the current configuration and `mcpbox_request_module` to request additional modules.

## Error Handling

All tools return structured responses:

**Success:**
```json
{
  "success": true,
  "id": "uuid",
  "message": "Operation completed"
}
```

**Error:**
```json
{
  "error": "Description of what went wrong"
}
```

## Security Notes

1. **Authentication**:
   - **Local mode**: No auth required (Claude Desktop via localhost)
   - **Remote mode**: Service token validation (Cloudflare Worker adds X-MCPbox-Service-Token)
2. **Approval Workflow**: All tools must be approved by admin before becoming available
3. **Input Validation**: Tool names must be lowercase alphanumeric with underscores
4. **Python Code**: Executed in an isolated sandbox environment with restricted imports
5. **Network Access**: Python tools access network via SSRF-protected `http` client

## Architecture

```
LOCAL MODE:                                REMOTE MODE:
Claude Desktop                             Claude Web
    |                                          |
    | localhost                                | MCP Protocol (HTTPS)
    v                                          v
                                         Cloudflare Worker
                                         (OAuth 2.1 + OIDC upstream)
                                               |
                                               | + X-MCPbox-Service-Token
                                               | + X-MCPbox-User-Email
                                               v
                                         Workers VPC (private)
    |                                          |
    +------------------------------------------+
                        |
                        v
              MCP Gateway (/mcp)
                        |
         +-- mcpbox_* tools --> MCPManagementService --> Database
         |
         +-- approved user tools --> Sandbox Service --> Tool Execution
```

The management tools are handled directly by the MCP gateway, while user-created tools (once approved) are forwarded to the sandbox service for execution.
