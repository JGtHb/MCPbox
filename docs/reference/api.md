---
title: API Reference
parent: Reference
nav_order: 3
---

# API Reference

MCPBox exposes two HTTP interfaces: the Admin API and the MCP Gateway.

## Admin API

Base URL: `http://localhost:8000`

All endpoints except `/auth/setup` and `/auth/login` require JWT authentication via `Authorization: Bearer <token>` header.

List endpoints return paginated responses: `{ items, total, page, page_size, pages }`.

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/setup` | POST | Create the initial admin account (one-time) |
| `/auth/login` | POST | Log in and receive JWT tokens |
| `/auth/refresh` | POST | Refresh an expired access token |

### Servers

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers` | GET | List all servers |
| `/api/servers` | POST | Create a server |
| `/api/servers/{id}` | GET | Get server details |
| `/api/servers/{id}` | PUT | Update a server |
| `/api/servers/{id}` | DELETE | Delete a server and its tools |
| `/api/servers/{id}/start` | POST | Start a server |
| `/api/servers/{id}/stop` | POST | Stop a server |

### Tools

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers/{id}/tools` | POST | Create a tool |
| `/api/tools/{id}` | GET | Get tool details |
| `/api/tools/{id}` | PUT | Update a tool |
| `/api/tools/{id}` | DELETE | Delete a tool |
| `/api/tools/{id}/logs` | GET | Get execution logs |

### Secrets

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/servers/{id}/secrets` | GET | List server secrets (keys only) |
| `/api/servers/{id}/secrets` | POST | Create a secret placeholder |
| `/api/secrets/{id}/value` | PUT | Set a secret's value |
| `/api/secrets/{id}` | DELETE | Delete a secret |

### Approvals

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/approvals` | GET | List all pending requests |
| `/api/approvals/{type}/{id}/approve` | POST | Approve a request |
| `/api/approvals/{type}/{id}/reject` | POST | Reject a request |

### Other

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard/stats` | GET | Dashboard statistics |
| `/api/activity` | GET | Activity log with search/filter |
| `/api/activity/stream` | WebSocket | Real-time activity stream |
| `/api/export` | POST | Export servers and tools as JSON |
| `/api/import` | POST | Import servers and tools from JSON |
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
