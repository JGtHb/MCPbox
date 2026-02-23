---
title: API Reference
parent: Reference
nav_order: 3
---

# API Reference

MCPBox exposes two HTTP interfaces: the Admin API and the MCP Gateway.

## Admin API

Base URL: `http://localhost:8000`

All endpoints except `/auth/*` and `/health` require JWT authentication via `Authorization: Bearer <token>` header.

List endpoints return paginated responses: `{ items, total, page, page_size, pages }`.

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/setup` | POST | Create the initial admin account (one-time) |
| `/auth/login` | POST | Log in and receive JWT tokens |
| `/auth/refresh` | POST | Refresh an expired access token |
| `/auth/logout` | POST | Invalidate current tokens |
| `/auth/me` | GET | Get current user info |
| `/auth/change-password` | POST | Change password |

### Servers

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers` | GET | List all servers |
| `/api/servers` | POST | Create a server |
| `/api/servers/{id}` | GET | Get server details |
| `/api/servers/{id}` | PATCH | Update a server |
| `/api/servers/{id}` | DELETE | Delete a server and its tools |
| `/api/servers/{id}/allowed-hosts` | POST | Add an allowed network host |
| `/api/servers/{id}/allowed-hosts` | DELETE | Remove an allowed network host |

### Sandbox (Server Lifecycle)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sandbox/servers/{id}/start` | POST | Start a server (register tools with sandbox) |
| `/api/sandbox/servers/{id}/stop` | POST | Stop a server (unregister tools) |
| `/api/sandbox/servers/{id}/restart` | POST | Restart a server |
| `/api/sandbox/servers/{id}/status` | GET | Get server sandbox status |
| `/api/sandbox/servers/{id}/logs` | GET | Get server sandbox logs |

### Tools

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers/{id}/tools` | POST | Create a tool |
| `/api/servers/{id}/tools` | GET | List tools in a server |
| `/api/tools/{id}` | GET | Get tool details |
| `/api/tools/{id}` | PATCH | Update a tool |
| `/api/tools/{id}` | DELETE | Delete a tool |
| `/api/tools/{id}/versions` | GET | List tool versions |
| `/api/tools/{id}/versions/compare` | GET | Compare two versions |
| `/api/tools/{id}/versions/{version}` | GET | Get a specific version |
| `/api/tools/{id}/versions/{version}/rollback` | POST | Roll back to a version |
| `/api/tools/validate-code` | POST | Validate Python code |
| `/api/tools/test-code` | POST | Test a saved tool |

### Secrets

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers/{id}/secrets` | GET | List server secrets (keys only) |
| `/api/servers/{id}/secrets` | POST | Create a secret placeholder |
| `/api/servers/{id}/secrets/{key}` | PUT | Set a secret's value |
| `/api/servers/{id}/secrets/{key}` | DELETE | Delete a secret |

### Approvals

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approvals/stats` | GET | Get approval statistics |
| `/api/approvals/tools` | GET | List pending tool approvals |
| `/api/approvals/tools/{id}/action` | POST | Approve or reject a tool |
| `/api/approvals/tools/{id}/revoke` | POST | Revoke tool approval |
| `/api/approvals/modules` | GET | List pending module requests |
| `/api/approvals/modules/{id}/action` | POST | Approve or reject a module request |
| `/api/approvals/network` | GET | List pending network requests |
| `/api/approvals/network/{id}/action` | POST | Approve or reject a network request |

### Settings

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/settings` | GET | List all settings |
| `/api/settings/security-policy` | GET | Get security policy |
| `/api/settings/security-policy` | PATCH | Update security policy |
| `/api/settings/modules` | GET | Get module whitelist config |
| `/api/settings/modules` | PATCH | Update module whitelist |
| `/api/settings/modules/enhanced` | GET | Get enhanced module config with install status |
| `/api/settings/modules/pypi/{name}` | GET | Look up a module on PyPI |
| `/api/settings/modules/{name}/install` | POST | Install a Python module |
| `/api/settings/modules/sync` | POST | Sync installed modules |

### External MCP Sources

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/external-sources/servers/{id}/sources` | POST | Add an external MCP source |
| `/api/external-sources/servers/{id}/sources` | GET | List sources for a server |
| `/api/external-sources/sources/{id}` | GET | Get source details |
| `/api/external-sources/sources/{id}` | PUT | Update a source |
| `/api/external-sources/sources/{id}` | DELETE | Delete a source |
| `/api/external-sources/sources/{id}/discover` | POST | Discover tools from a source |
| `/api/external-sources/sources/{id}/import` | POST | Import tools from a source |

### Other

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard` | GET | Dashboard statistics |
| `/api/activity/logs` | GET | Activity log with search/filter |
| `/api/activity/stats` | GET | Activity statistics |
| `/api/activity/recent` | GET | Recent activity |
| `/api/activity/stream` | WebSocket | Real-time activity stream |
| `/api/export/servers` | GET | Export all servers and tools as JSON |
| `/api/export/servers/{id}` | GET | Export a single server |
| `/api/export/import` | POST | Import servers and tools from JSON |
| `/api/config` | GET | Get system configuration |
| `/health` | GET | Basic health check |
| `/health/detail` | GET | Detailed health with service status |
| `/health/services` | GET | Individual service health |

## MCP Gateway

Base URL: `http://localhost:8000/mcp` (local) or `https://worker-url/mcp` (remote)

Uses [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) with JSON-RPC 2.0.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | MCP JSON-RPC requests (`initialize`, `tools/list`, `tools/call`) |
| `/mcp` | GET | SSE stream for server-to-client notifications |

In local mode, no authentication is required. In remote mode, the Cloudflare Worker handles OAuth 2.1 and adds service token headers.
