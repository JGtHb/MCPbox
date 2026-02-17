# API Contracts

## Internal Module Interfaces

### Backend → Sandbox (HTTP)

- **Interface**: HTTP REST over Docker network (`mcpbox-sandbox`). Backend uses `SandboxClient` (`backend/app/services/sandbox_client.py`) to communicate with sandbox at `http://sandbox:8001`.
- **Auth**: `Authorization: Bearer <SANDBOX_API_KEY>` header on all requests
- **Circuit breaker**: 5 failures → open state, 60s recovery timeout

#### POST /servers/register
- **Purpose**: Register a server and its approved tools with the sandbox
- **Input**: `{ server_id, server_name, tools: [{ name, description, python_code, helper_code?, input_schema, allowed_modules, allowed_hosts }], secrets: { key: value } }`
- **Output**: `{ success: true, server_id, tools_registered: N }`
- **Error cases**: 400 (invalid tool definition), 401 (bad API key), 500 (registration failure)

#### POST /servers/{server_id}/unregister
- **Purpose**: Remove a server and all its tools from the sandbox registry
- **Input**: None (server_id in path)
- **Output**: `{ success: true }`

#### PUT /servers/{server_id}/secrets
- **Purpose**: Update a server's secrets in the sandbox (after secret creation/update/deletion in backend)
- **Input**: `{ secrets: { key: value } }`
- **Output**: `{ success: true }`

#### POST /tools/{tool_name}/call
- **Purpose**: Execute a tool's Python code
- **Input**: `{ arguments: { ... } }`
- **Output**: `{ success: true, result: any }` or `{ success: false, error: string, stdout?: string }`
- **Error cases**: 404 (tool not found), 408 (execution timeout), 500 (execution error)

#### POST /execute
- **Purpose**: Execute arbitrary Python code (used by `mcpbox_test_code`)
- **Input**: `{ code: string, timeout?: number, allowed_modules?: string[], allowed_hosts?: string[], secrets?: object, input_data?: object }`
- **Output**: `{ success: true, result: any, stdout?: string }` or `{ success: false, error: string }`

#### POST /mcp
- **Purpose**: MCP JSON-RPC endpoint (gateway-facing)
- **Input**: MCP JSON-RPC request (`{ jsonrpc: "2.0", method: string, params?: object, id?: number }`)
- **Output**: MCP JSON-RPC response
- **Methods**: `tools/list`, `tools/call`

#### POST /packages/install
- **Purpose**: Install a Python package from PyPI
- **Input**: `{ module_name: string }`
- **Output**: `{ success: true, installed: string }` or `{ success: false, error: string }`

#### POST /packages/sync
- **Purpose**: Sync installed packages with backend's approved module list
- **Input**: `{ modules: string[] }`
- **Output**: `{ synced: N, errors: string[] }`

#### GET /packages
- **Purpose**: List installed packages
- **Output**: `{ packages: [{ name, version, installed_at }] }`

#### POST /mcp-discover
- **Purpose**: Discover tools from an external MCP server
- **Input**: `{ url: string, headers?: object }`
- **Output**: `{ tools: [{ name, description, input_schema }] }`

#### POST /mcp-health-check
- **Purpose**: Check connectivity to an external MCP server
- **Input**: `{ url: string, headers?: object }`
- **Output**: `{ healthy: true, latency_ms: number }` or `{ healthy: false, error: string }`

### Worker → MCP Gateway (HTTP via Workers VPC)

- **Interface**: HTTP over Cloudflare Workers VPC binding. Worker proxies MCP requests to `http://mcp-gateway:8002/mcp` via private tunnel.
- **Auth**: `X-MCPbox-Service-Token` header (shared secret), `X-MCPbox-User-Email` header (OIDC-verified user identity)
- **Contract enforcement**: Service token validated with `secrets.compare_digest()` (constant-time). Fail-closed on database errors.

#### POST /mcp
- **Purpose**: MCP Streamable HTTP endpoint
- **Input**: MCP JSON-RPC request with additional headers: `Mcp-Session-Id` (optional, for session continuity), `X-MCPbox-Service-Token`, `X-MCPbox-User-Email`, `X-MCPbox-Auth-Method: oidc`
- **Output**: MCP JSON-RPC response. May include `Mcp-Session-Id` header for new sessions.
- **Error cases**: 401 (missing/invalid service token), 403 (email required for method), 429 (rate limited), 502 (sandbox unreachable)

#### GET /mcp
- **Purpose**: SSE stream for server-to-client MCP notifications (e.g., `tools/list_changed`)
- **Input**: `Mcp-Session-Id` header (required)
- **Output**: SSE event stream
- **Error cases**: 404 (unknown session)

### Backend → Cloudflare API (HTTPS)

- **Interface**: REST API calls to `api.cloudflare.com`. Used by setup wizard for tunnel, VPC, Worker, and Access configuration.
- **Auth**: Cloudflare API token in `Authorization: Bearer <token>` header
- **Validation**: Token permissions verified before wizard operations

### Cloudflared → Backend (HTTP)

- **Interface**: cloudflared daemon fetches tunnel token from backend's internal API
- **Auth**: `Authorization: Bearer <SANDBOX_API_KEY>`
- **Endpoint**: `GET /internal/tunnel-token`
- **Output**: `{ token: string }` (encrypted tunnel token, decrypted by backend)

---

## External API Surface

### Admin API (`/api/*` — local access only, port 8000)

All endpoints require JWT authentication via `Authorization: Bearer <access_token>` header (except `/auth/setup` and `/auth/login`).

All list endpoints return paginated responses: `{ items: T[], total: number, page: number, page_size: number, pages: number }`

#### POST /auth/setup
- **Purpose**: Initial admin user creation (one-time)
- **Auth**: None (only works when no admin user exists)
- **Input**: `{ email: string, password: string }`
- **Output**: `{ access_token, refresh_token, token_type: "bearer" }`
- **Error cases**: 400 (admin already exists), 422 (validation error)

#### POST /auth/login
- **Purpose**: Admin login
- **Auth**: None
- **Input**: `{ email: string, password: string }`
- **Output**: `{ access_token, refresh_token, token_type: "bearer" }`
- **Error cases**: 401 (invalid credentials), 429 (rate limited: 5/min)

#### POST /auth/refresh
- **Purpose**: Refresh access token
- **Auth**: None (uses refresh token in body)
- **Input**: `{ refresh_token: string }`
- **Output**: `{ access_token, refresh_token, token_type: "bearer" }`
- **Error cases**: 401 (invalid/expired refresh token)

#### GET /api/servers
- **Purpose**: List all MCP servers
- **Auth**: JWT required
- **Input**: Query params: `page`, `page_size`
- **Output**: Paginated list of servers with tool counts

#### POST /api/servers
- **Purpose**: Create a new MCP server
- **Auth**: JWT required
- **Input**: `{ name: string, description?: string }`
- **Output**: Created server object
- **Error cases**: 422 (name validation: `^[a-z][a-z0-9_]*$`)

#### GET /api/servers/{id}
- **Purpose**: Get server details including tools
- **Auth**: JWT required
- **Output**: Server object with tools array

#### PUT /api/servers/{id}
- **Purpose**: Update server configuration
- **Auth**: JWT required
- **Input**: `{ name?, description?, allowed_modules?, allowed_hosts? }`
- **Output**: Updated server object

#### DELETE /api/servers/{id}
- **Purpose**: Delete server and all its tools
- **Auth**: JWT required
- **Output**: 204 No Content
- **Error cases**: 404 (not found)

#### POST /api/servers/{id}/start
- **Purpose**: Start server (register tools with sandbox)
- **Auth**: JWT required
- **Output**: Updated server (status: running)

#### POST /api/servers/{id}/stop
- **Purpose**: Stop server (unregister from sandbox)
- **Auth**: JWT required
- **Output**: Updated server (status: stopped)

#### POST /api/servers/{id}/tools
- **Purpose**: Create a tool on a server
- **Auth**: JWT required
- **Input**: `{ name: string, description: string, python_code: string, input_schema?: object }`
- **Output**: Created tool (status: draft)
- **Error cases**: 422 (name: `^[a-z][a-z0-9_]*$`, code: max 100KB)

#### GET /api/tools/{id}
- **Purpose**: Get tool details with version history
- **Auth**: JWT required
- **Output**: Tool object with versions

#### PUT /api/tools/{id}
- **Purpose**: Update tool code/description
- **Auth**: JWT required
- **Input**: `{ python_code?, description?, input_schema? }`
- **Output**: Updated tool object

#### DELETE /api/tools/{id}
- **Purpose**: Delete a tool
- **Auth**: JWT required
- **Output**: 204 No Content

#### POST /api/servers/{id}/secrets
- **Purpose**: Create a secret placeholder
- **Auth**: JWT required
- **Input**: `{ key: string, description?: string }`
- **Output**: Created secret (key + has_value flag, no value)

#### GET /api/servers/{id}/secrets
- **Purpose**: List server secrets (keys only, no values)
- **Auth**: JWT required
- **Output**: List of `{ id, key, description, has_value }`

#### PUT /api/secrets/{id}/value
- **Purpose**: Set secret value (admin only)
- **Auth**: JWT required
- **Input**: `{ value: string }`
- **Output**: Updated secret
- **Error cases**: 404

#### DELETE /api/secrets/{id}
- **Purpose**: Delete a secret
- **Auth**: JWT required
- **Output**: 204

#### GET /api/approvals
- **Purpose**: List pending approval requests (tools, modules, network access)
- **Auth**: JWT required
- **Output**: `{ tool_requests: [], module_requests: [], network_requests: [] }`

#### POST /api/approvals/{type}/{id}/approve
- **Purpose**: Approve a pending request
- **Auth**: JWT required (admin identity from JWT for audit trail)
- **Input**: `{ reason?: string }`
- **Output**: Updated request (status: approved)

#### POST /api/approvals/{type}/{id}/reject
- **Purpose**: Reject a pending request
- **Auth**: JWT required
- **Input**: `{ reason?: string }`
- **Output**: Updated request (status: rejected)

#### GET /api/tools/{id}/logs
- **Purpose**: Get execution logs for a tool
- **Auth**: JWT required
- **Input**: Query params: `page`, `page_size`
- **Output**: Paginated execution logs (args redacted, results truncated)

#### GET /api/activity
- **Purpose**: Activity log with search and filtering
- **Auth**: JWT required
- **Input**: Query params: `page`, `page_size`, `search`, `event_type`
- **Output**: Paginated activity log entries

#### WS /api/activity/stream
- **Purpose**: Real-time activity stream
- **Auth**: JWT via `token` query parameter (validated before WebSocket upgrade)
- **Output**: JSON activity events streamed via WebSocket

#### GET /api/dashboard/stats
- **Purpose**: Dashboard statistics (server count, tool count, recent activity)
- **Auth**: JWT required
- **Output**: `{ servers: { total, running }, tools: { total, approved }, recent_activity: [] }`

#### POST /api/export
- **Purpose**: Export servers and tools as JSON
- **Auth**: JWT required
- **Output**: JSON export blob

#### POST /api/import
- **Purpose**: Import servers and tools from JSON
- **Auth**: JWT required
- **Input**: JSON export blob
- **Output**: Import summary

#### GET /api/cloudflare/status
- **Purpose**: Get Cloudflare setup wizard status
- **Auth**: JWT required
- **Output**: Wizard state (completed steps, configuration)

#### POST /api/cloudflare/verify-token
- **Purpose**: Verify Cloudflare API token permissions
- **Auth**: JWT required
- **Input**: `{ api_token: string }`
- **Output**: Token validity and permissions

#### POST /api/cloudflare/tunnel
- **Purpose**: Create Cloudflare tunnel
- **Auth**: JWT required
- **Input**: `{ tunnel_name: string }`
- **Output**: Tunnel details

#### POST /api/cloudflare/vpc-service
- **Purpose**: Create VPC service binding
- **Auth**: JWT required
- **Output**: VPC service details

#### POST /api/cloudflare/worker
- **Purpose**: Deploy Cloudflare Worker
- **Auth**: JWT required
- **Input**: `{ worker_name: string }`
- **Output**: Worker URL and status

#### POST /api/cloudflare/access
- **Purpose**: Configure Access for SaaS (OIDC)
- **Auth**: JWT required
- **Output**: OIDC configuration details

### MCP Gateway (`/mcp` — local + tunnel, port 8002)

#### POST /mcp
- **Purpose**: MCP Streamable HTTP endpoint (JSON-RPC 2.0)
- **Auth**: None (local mode) or service token (remote mode, set by Worker)
- **Input**: MCP JSON-RPC request body
- **Output**: MCP JSON-RPC response
- **Supported methods**:
  - `initialize` — Returns server capabilities (always allowed)
  - `notifications/initialized` — Client ready notification (always allowed)
  - `tools/list` — List all approved tools from running servers (requires verified email in remote mode)
  - `tools/call` — Execute a tool (requires verified email in remote mode)
- **Error cases**: 401 (invalid service token), 403 (email required), 404 (unknown tool), 408 (execution timeout)

#### GET /mcp
- **Purpose**: SSE stream for server-to-client notifications
- **Auth**: Same as POST /mcp
- **Input**: `Mcp-Session-Id` header
- **Output**: SSE event stream (`tools/list_changed` notifications)

#### GET /health
- **Purpose**: Health check
- **Auth**: None (but restricted to localhost in MCP-only mode to prevent service discovery through tunnel)
- **Output**: `{ status: "healthy", service: "mcpbox-mcp-gateway" }`

### Internal API (`/internal/*` — sandbox/cloudflared access only)

#### GET /internal/tunnel-token
- **Purpose**: Provide tunnel token to cloudflared daemon
- **Auth**: `Authorization: Bearer <SANDBOX_API_KEY>`
- **Output**: `{ token: string }` (decrypted tunnel token)

#### POST /internal/tool-executed
- **Purpose**: Record tool execution log from sandbox
- **Auth**: `Authorization: Bearer <SANDBOX_API_KEY>`
- **Input**: `{ tool_id, server_id, arguments, result, error?, stdout?, duration_ms, success }`
- **Output**: 200 OK
