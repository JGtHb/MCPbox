/**
 * End-to-End Tests for MCPbox MCP Proxy Worker
 *
 * These tests verify the Cloudflare Worker's behavior in various scenarios:
 * - CORS handling
 * - Configuration validation
 * - Request proxying
 * - JWT extraction
 * - Error handling
 *
 * The OAuthProvider is mocked to avoid cloudflare: protocol imports in Node.
 * The mock routes '/' (apiRoute) to apiHandler and other paths to defaultHandler,
 * matching real OAuthProvider behavior without OAuth token validation.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock @cloudflare/workers-oauth-provider before importing index.
// This prevents the cloudflare: protocol import error in Node's ESM loader.
// vitest hoists vi.mock() calls above all imports automatically.
vi.mock("@cloudflare/workers-oauth-provider", () => {
  class MockOAuthProvider {
    private apiHandler: any;
    private defaultHandler: any;
    private apiRoute: string;

    constructor(opts: any) {
      this.apiHandler = opts.apiHandler;
      this.defaultHandler = opts.defaultHandler;
      this.apiRoute = opts.apiRoute || "/";
    }

    async fetch(
      request: Request,
      env: any,
      ctx: any
    ): Promise<Response> {
      const url = new URL(request.url);
      if (url.pathname === this.apiRoute) {
        // Simulate OAuth-validated request routed to apiHandler
        const ctxWithProps = { ...ctx, props: { authMethod: "oauth" } };
        return this.apiHandler.fetch(request, env, ctxWithProps);
      }
      // Other paths go to defaultHandler (OAuth flow endpoints)
      return this.defaultHandler.fetch(request, env, ctx);
    }
  }

  return {
    default: MockOAuthProvider,
  };
});

import worker, { Env } from "./index";

// Mock execution context
const createExecutionContext = () => ({
  waitUntil: vi.fn(),
  passThroughOnException: vi.fn(),
});

// Mock VPC service for testing
const createMockVpcService = (responseBody: unknown, status = 200) => ({
  fetch: vi.fn().mockResolvedValue(
    new Response(JSON.stringify(responseBody), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  ),
});

describe("MCPbox Proxy Worker", () => {
  describe("CORS Handling", () => {
    it("should handle OPTIONS preflight requests", async () => {
      const request = new Request("https://example.com/", {
        method: "OPTIONS",
        headers: {
          Origin: "https://mcp.claude.ai",
        },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://mcp.claude.ai"
      );
      expect(response.headers.get("Access-Control-Allow-Methods")).toContain(
        "POST"
      );
      expect(response.headers.get("Access-Control-Allow-Headers")).toContain(
        "Content-Type"
      );
      expect(response.headers.get("Access-Control-Allow-Headers")).toContain(
        "Cf-Access-Jwt-Assertion"
      );
    });

    it("should allow claude.ai origin", async () => {
      const request = new Request("https://example.com/", {
        method: "OPTIONS",
        headers: {
          Origin: "https://claude.ai",
        },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
    });

    it("should fallback to mcp.claude.ai for unknown origins", async () => {
      const request = new Request("https://example.com/", {
        method: "OPTIONS",
        headers: {
          Origin: "https://unknown-origin.com",
        },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://mcp.claude.ai"
      );
    });

    it("should use custom CORS origin when configured", async () => {
      const request = new Request("https://example.com/", {
        method: "OPTIONS",
        headers: {
          Origin: "https://custom-origin.com",
        },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        CORS_ALLOWED_ORIGIN: "https://custom-origin.com",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://custom-origin.com"
      );
    });
  });

  describe("Configuration Validation", () => {
    it("should return 503 when MCPBOX_TUNNEL is not configured", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: undefined,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(503);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("Service temporarily unavailable");
    });

    it("should return 503 when MCPBOX_SERVICE_TOKEN is not configured", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: undefined,
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(503);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("Service temporarily unavailable");
    });
  });

  describe("Request Proxying", () => {
    it("should forward POST requests to MCPbox via VPC", async () => {
      const mcpRequest = {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/list",
      };

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://mcp.claude.ai",
        },
        body: JSON.stringify(mcpRequest),
      });

      const mockResponse = {
        jsonrpc: "2.0",
        id: 1,
        result: {
          tools: [{ name: "test_tool", description: "A test tool" }],
        },
      };

      const mockVpcService = createMockVpcService(mockResponse);
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-service-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalledOnce();

      // Verify the target URL
      const [targetUrl, options] = mockVpcService.fetch.mock.calls[0];
      expect(targetUrl).toBe("http://mcp-gateway:8002/mcp");

      // Verify service token was added
      expect(options.headers.get("X-MCPbox-Service-Token")).toBe(
        "test-service-token"
      );
    });

    it("should preserve query parameters in forwarded requests", async () => {
      const request = new Request(
        "https://example.com/?check=full",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Origin: "https://mcp.claude.ai",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "tools/list",
          }),
        }
      );

      const mockVpcService = createMockVpcService({ status: "ok" });
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);

      const [targetUrl] = mockVpcService.fetch.mock.calls[0];
      expect(targetUrl).toBe("http://mcp-gateway:8002/mcp?check=full");
    });

    it("should add X-Forwarded headers", async () => {
      const request = new Request("https://my-worker.workers.dev/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-Forwarded-Host")).toBe(
        "my-worker.workers.dev"
      );
      expect(options.headers.get("X-Forwarded-Proto")).toBe("https");
    });

    it("should add CORS headers to proxied response", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://claude.ai",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({
        jsonrpc: "2.0",
        id: 1,
        result: { tools: [] },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
      expect(response.headers.get("Access-Control-Allow-Methods")).toBe(
        "GET, POST, OPTIONS"
      );
    });
  });

  describe("JWT Extraction", () => {
    it("should extract user email from valid Cloudflare Access JWT", async () => {
      // Create a properly structured mock JWT
      const now = Math.floor(Date.now() / 1000);
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const jwtPayload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://test.cloudflareaccess.com",
        exp: now + 3600,
        nbf: now - 60,
        iat: now - 60,
      };
      const mockSignature = btoa("mocksignature");
      const mockJwt = `${btoa(JSON.stringify(header))}.${btoa(JSON.stringify(jwtPayload))}.${mockSignature}`;

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      // Mock JWKS endpoint and crypto verification
      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }],
          }),
      });
      const importKeySpy = vi
        .spyOn(crypto.subtle, "importKey")
        .mockResolvedValue({} as CryptoKey);
      const verifySpy = vi
        .spyOn(crypto.subtle, "verify")
        .mockResolvedValue(true);

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "test.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBe(
        "user@example.com"
      );
    });

    it("should handle JWT without email claim gracefully", async () => {
      // Without CF_ACCESS env vars, JWT extraction is skipped entirely
      const jwtPayload = {
        sub: "user123",
        iat: Math.floor(Date.now() / 1000),
      };
      const mockJwt = `header.${btoa(JSON.stringify(jwtPayload))}.signature`;

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      const [, options] = mockVpcService.fetch.mock.calls[0];
      // Email header should not be set when JWT doesn't have email
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should handle malformed JWT gracefully", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": "not-a-valid-jwt",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should still succeed, just without the email header
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should handle JWT with invalid base64 payload", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": "header.!!!invalid-base64!!!.signature",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should still succeed without email extraction
      expect(response.status).toBe(200);
    });
  });

  describe("Error Handling", () => {
    it("should return 502 when VPC connection fails", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = {
        fetch: vi.fn().mockRejectedValue(new Error("Connection refused")),
      };

      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(502);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("Failed to connect to backend service");
    });

    it("should preserve upstream error status codes", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = {
        fetch: vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ error: "Unauthorized" }), {
            status: 401,
          })
        ),
      };

      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(401);
    });
  });

  describe("MCP Protocol Integration", () => {
    it("should forward tools/list requests correctly", async () => {
      const mcpRequest = {
        jsonrpc: "2.0",
        id: "test-id-1",
        method: "tools/list",
        params: {},
      };

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(mcpRequest),
      });

      const expectedResponse = {
        jsonrpc: "2.0",
        id: "test-id-1",
        result: {
          tools: [
            {
              name: "mcpbox_list_servers",
              description: "List all MCP servers",
              inputSchema: { type: "object" },
            },
          ],
        },
      };

      const mockVpcService = createMockVpcService(expectedResponse);
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as any;
      expect(body.jsonrpc).toBe("2.0");
      expect(body.id).toBe("test-id-1");
      expect(body.result.tools).toHaveLength(1);
    });

    it("should forward tools/call requests with arguments", async () => {
      const mcpRequest = {
        jsonrpc: "2.0",
        id: 42,
        method: "tools/call",
        params: {
          name: "mcpbox_create_server",
          arguments: {
            name: "my-server",
            description: "A test server",
          },
        },
      };

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(mcpRequest),
      });

      const expectedResponse = {
        jsonrpc: "2.0",
        id: 42,
        result: {
          content: [
            {
              type: "text",
              text: JSON.stringify({ id: 1, name: "my-server" }),
            },
          ],
        },
      };

      const mockVpcService = createMockVpcService(expectedResponse);
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as any;
      expect(body.id).toBe(42);
      expect(body.result.content[0].type).toBe("text");
    });

    it("should handle MCP error responses", async () => {
      const mcpRequest = {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: {
          name: "nonexistent_tool",
          arguments: {},
        },
      };

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(mcpRequest),
      });

      const errorResponse = {
        jsonrpc: "2.0",
        id: 1,
        error: {
          code: -32601,
          message: "Tool not found: nonexistent_tool",
        },
      };

      const mockVpcService = createMockVpcService(errorResponse);
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as any;
      expect(body.error.code).toBe(-32601);
    });
  });

  describe("Security", () => {
    it("should always include service token in forwarded requests", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "super-secret-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Service-Token")).toBe(
        "super-secret-token"
      );
    });

    it("should not expose service token in error responses", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = {
        fetch: vi.fn().mockRejectedValue(new Error("Network error")),
      };

      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "super-secret-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      const text = await response.text();
      expect(text).not.toContain("super-secret-token");
    });

    it("should not forward potentially dangerous headers from client", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // Attacker tries to inject their own service token
          "X-MCPbox-Service-Token": "attacker-token",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "real-service-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      const [, options] = mockVpcService.fetch.mock.calls[0];
      // The real service token should be used, not the attacker's
      expect(options.headers.get("X-MCPbox-Service-Token")).toBe(
        "real-service-token"
      );
    });
  });

  describe("Edge Cases", () => {
    it("should handle requests without Origin header", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "tools/list",
        }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      // Should fallback to default origin
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://mcp.claude.ai"
      );
    });

    it("should handle empty request body", async () => {
      const request = new Request("https://example.com/", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });

      const mockVpcService = createMockVpcService({ status: "ok" });
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
    });

    it("should handle large request payloads", async () => {
      const largePayload = {
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: {
          name: "test_tool",
          arguments: {
            data: "x".repeat(100000), // 100KB of data
          },
        },
      };

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(largePayload),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });
  });

  describe("Path Validation", () => {
    it("should allow root path as MCP endpoint", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should allow /health path", async () => {
      const request = new Request("https://example.com/health", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({ status: "ok" });
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      // /health is handled directly by the worker, not proxied
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });

    it("should reject disallowed paths with 404", async () => {
      const request = new Request("https://example.com/api/servers", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(404);
      // Should NOT have called the VPC service
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });

    it("should reject unknown paths with 404", async () => {
      const request = new Request("https://example.com/random", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(404);
    });

    it("should reject path traversal attempts", async () => {
      const request = new Request("https://example.com/mcp/../api/servers", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // URL parsing normalizes the path, so this should resolve to /api/servers and be rejected
      expect(response.status).toBe(404);
    });

    it("should include CORS headers in 404 response", async () => {
      const request = new Request("https://example.com/api/admin", {
        method: "GET",
        headers: { Origin: "https://claude.ai" },
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(404);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
    });
  });

  describe("CORS Headers in Error Responses", () => {
    it("should include CORS headers in 503 config error", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://claude.ai",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: undefined,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(503);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
    });

    it("should include CORS headers in 502 proxy error", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://mcp.claude.ai",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = {
        fetch: vi.fn().mockRejectedValue(new Error("Connection failed")),
      };

      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(502);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://mcp.claude.ai"
      );
      expect(response.headers.get("Access-Control-Allow-Headers")).toContain(
        "Cf-Access-Jwt-Assertion"
      );
    });
  });

  describe("JWT Security Validation", () => {
    // Helper to create a base64url encoded string
    // Note: btoa produces regular base64, we convert to base64url
    const base64url = (obj: object | string) => {
      const str = typeof obj === "string" ? obj : JSON.stringify(obj);
      // btoa produces base64, then we convert to base64url by replacing chars
      // We keep the padding for atob compatibility
      return btoa(str).replace(/\+/g, "-").replace(/\//g, "_");
    };

    // Helper to create a mock JWT with specific header/payload
    // The signature part needs to be valid base64url too
    const createMockJwt = (
      header: object,
      payload: object,
      signature = "bW9ja3NpZ25hdHVyZQ" // "mocksignature" in base64
    ) => {
      return `${base64url(header)}.${base64url(payload)}.${signature}`;
    };

    it("should not extract email from JWT with algorithm other than RS256", async () => {
      // JWT with HS256 algorithm (algorithm confusion attack) — verifyAccessJwt rejects it
      const header = { alg: "HS256", kid: "test-kid", typ: "JWT" };
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 3600,
        nbf: Math.floor(Date.now() / 1000) - 60,
        iat: Math.floor(Date.now() / 1000) - 60,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Worker proxies with authMethod=oauth (no email extracted from HS256 JWT)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should not extract email from JWT with 'none' algorithm", async () => {
      const header = { alg: "none", kid: "test-kid", typ: "JWT" };
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 3600,
      };
      const mockJwt = createMockJwt(header, payload, "");

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Worker proxies with authMethod=oauth (JWT with 'none' alg rejected)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should not extract email from JWT with missing sub claim", async () => {
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const payload = {
        // No sub claim
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 3600,
        nbf: Math.floor(Date.now() / 1000) - 60,
        iat: Math.floor(Date.now() / 1000) - 60,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      // Mock JWKS endpoint and crypto.subtle.verify using vi.spyOn
      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            keys: [
              {
                kid: "test-kid",
                kty: "RSA",
                n: "test-n",
                e: "AQAB",
                alg: "RS256",
              },
            ],
          }),
      });

      // Mock crypto.subtle methods using spyOn
      const importKeySpy = vi.spyOn(crypto.subtle, "importKey").mockResolvedValue({} as CryptoKey);
      const verifySpy = vi.spyOn(crypto.subtle, "verify").mockResolvedValue(true);

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      // Worker proxies with authMethod=oauth (JWT with missing sub rejected)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should not extract email from JWT with future iat claim beyond clock skew", async () => {
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const futureIat = Math.floor(Date.now() / 1000) + 120; // 2 minutes in future (beyond 60s tolerance)
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 7200,
        nbf: Math.floor(Date.now() / 1000) - 60,
        iat: futureIat,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }],
          }),
      });

      const importKeySpy = vi.spyOn(crypto.subtle, "importKey").mockResolvedValue({} as CryptoKey);
      const verifySpy = vi.spyOn(crypto.subtle, "verify").mockResolvedValue(true);

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      // Worker doesn't enforce JWT - it proxies with authMethod=oauth (gateway enforces)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should accept JWT with exp slightly in past (within clock skew)", async () => {
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const now = Math.floor(Date.now() / 1000);
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: now - 30, // Expired 30 seconds ago (within 60s tolerance)
        nbf: now - 3600,
        iat: now - 3600,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }],
          }),
      });

      const importKeySpy = vi.spyOn(crypto.subtle, "importKey").mockResolvedValue({} as CryptoKey);
      const verifySpy = vi.spyOn(crypto.subtle, "verify").mockResolvedValue(true);

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      // Should be accepted due to clock skew tolerance
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should not extract email from JWT expired beyond clock skew tolerance", async () => {
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const now = Math.floor(Date.now() / 1000);
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: now - 90, // Expired 90 seconds ago (beyond 60s tolerance)
        nbf: now - 3600,
        iat: now - 3600,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": mockJwt,
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }],
          }),
      });

      const importKeySpy = vi.spyOn(crypto.subtle, "importKey").mockResolvedValue({} as CryptoKey);
      const verifySpy = vi.spyOn(crypto.subtle, "verify").mockResolvedValue(true);

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      // Worker doesn't enforce JWT - it proxies with authMethod=oauth (gateway enforces)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });
  });

  describe("Path Traversal Defense", () => {
    it("should reject paths containing .. in the middle", async () => {
      // Use a URL that won't be normalized but contains ..
      const request = new Request("https://example.com/mcp/..hidden", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should be rejected because path doesn't match any known route
      expect(response.status).toBe(404);
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });

    it("should reject encoded path traversal attempts", async () => {
      // %2e%2e is URL-encoded ..
      // Note: URL parsing will decode this, so the path will contain ..
      const request = new Request("https://example.com/mcp/%2e%2e/test", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // URL parsing normalizes %2e%2e to .., then path doesn't match any route
      expect(response.status).toBe(404);
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });
  });

  describe("JWT Authentication", () => {
    it("should proxy requests without JWT when auth is configured (gateway enforces)", async () => {
      // Worker doesn't enforce JWT - it proxies with authMethod=oauth
      // and the gateway enforces JWT requirements
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud-12345",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Worker proxies the request - JWT enforcement is at the gateway
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should allow requests without JWT when auth is not configured", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        // No CF_ACCESS_TEAM_DOMAIN or CF_ACCESS_AUD
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should proxy requests with invalid JWT format (gateway enforces)", async () => {
      // Worker doesn't reject invalid JWTs - it proxies with authMethod=oauth
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Cf-Access-Jwt-Assertion": "not-a-valid-jwt",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud-12345",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Worker proxies - JWT enforcement is at the gateway
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("oauth");
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should include CORS headers when proxying without valid JWT", async () => {
      const request = new Request("https://example.com/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://claude.ai",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud-12345",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
    });
  });
});
