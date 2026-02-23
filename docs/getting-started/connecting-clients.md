---
title: Connecting MCP Clients
parent: Getting Started
nav_order: 3
---

# Connecting MCP Clients

MCPBox works with any MCP-compatible client. In local mode, the MCP endpoint is `http://localhost:8000/mcp` — no authentication required.

## Claude Code

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "mcpbox": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Cursor

In Cursor settings, add an MCP server with the URL `http://localhost:8000/mcp`.

## Other MCP Clients

Any client that supports [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) can connect. Point it at:

```
http://localhost:8000/mcp
```

## Verify the Connection

After connecting, ask your LLM to list its available tools. You should see 24 tools with the `mcpbox_` prefix:

```
mcpbox_list_servers, mcpbox_create_server, mcpbox_create_tool,
mcpbox_test_code, mcpbox_request_publish, mcpbox_start_server, ...
```

If the tools don't appear, check that MCPBox is running (`docker compose ps`) and the health endpoint responds (`curl http://localhost:8000/health`).

## Remote Access

To connect MCP clients from outside your local network (e.g., claude.ai, remote Cursor), you need to set up Cloudflare remote access. See [Remote Access Setup]({% link guides/remote-access.md %}).

## Next Steps

- [Create your first tool]({% link guides/first-tool.md %}) — Walk through building a tool with your LLM
