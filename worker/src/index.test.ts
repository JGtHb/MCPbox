/**
 * End-to-End Tests for MCPbox MCP Proxy Worker
 *
 * These tests verify the Cloudflare Worker's behavior in various scenarios:
 * - CORS handling
 * - Configuration validation
 * - Request proxying
 * - JWT extraction
 * - Error handling
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock OAuthProvider to pass requests through to apiHandler/defaultHandler
// without requiring real OAuth tokens. This allows testing the Worker's
// request handling logic without the Cloudflare Workers runtime.
vi.mock("@cloudflare/workers-oauth-provider", () => {
  return {
    default: class MockOAuthProvider {
      apiRoute: string;
      apiHandler: { fetch: Function };
      defaultHandler: { fetch: Function };

      constructor(config: {
        apiRoute: string;
        apiHandler: { fetch: Function };
        defaultHandler: { fetch: Function };
      }) {
        this.apiRoute = config.apiRoute;
        this.apiHandler = config.apiHandler;
        this.defaultHandler = config.defaultHandler;
      }

      async fetch(
        request: Request,
        env: unknown,
        ctx: unknown
      ): Promise<Response> {
        const url = new URL(request.url);
        if (url.pathname.startsWith(this.apiRoute)) {
          // Simulate OAuthProvider passing validated request to apiHandler
          // with props (as it would after OAuth validation)
          const enrichedCtx = {
            ...(ctx as object),
            props: { authMethod: "oauth" },
          };
          return this.apiHandler.fetch(request, env, enrichedCtx);
        }
        // Non-API routes go to defaultHandler
        return this.defaultHandler.fetch(request, env, ctx);
      }
    },
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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

      const request = new Request("https://example.com/mcp", {
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
        "https://example.com/mcp?session=abc123",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Origin: "https://mcp.claude.ai",
          },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
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
      expect(targetUrl).toBe("http://mcp-gateway:8002/mcp?session=abc123");
    });

    it("should add X-Forwarded headers", async () => {
      const request = new Request("https://my-worker.workers.dev/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
        "GET, POST, DELETE, OPTIONS"
      );
    });
  });

  describe("OAuth Props Email", () => {
    it("should store email in OAuth props at /authorize when JWT is present", async () => {
      // Create a mock JWT with email
      const jwtPayload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 3600,
        nbf: Math.floor(Date.now() / 1000) - 60,
        iat: Math.floor(Date.now() / 1000) - 60,
      };
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const mockJwt = `${btoa(JSON.stringify(header)).replace(/\+/g, "-").replace(/\//g, "_")}.${btoa(JSON.stringify(jwtPayload)).replace(/\+/g, "-").replace(/\//g, "_")}.bW9ja3NpZw`;

      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://mcp.claude.ai/callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        {
          method: "GET",
          headers: {
            "Cf-Access-Jwt-Assertion": mockJwt,
          },
        },
      );

      // Mock JWKS and crypto for JWT verification
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

      let completedProps: any = null;
      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        CF_ACCESS_TEAM_DOMAIN: "myteam.cloudflareaccess.com",
        CF_ACCESS_AUD: "test-aud",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({
            clientId: "test-client",
            scope: [],
          }),
          completeAuthorization: vi.fn().mockImplementation(async (args: any) => {
            completedProps = args.props;
            return { redirectTo: "https://mcp.claude.ai/callback?code=test" };
          }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;
      importKeySpy.mockRestore();
      verifySpy.mockRestore();

      // Verify the props include the email
      expect(completedProps).toBeDefined();
      expect(completedProps.authMethod).toBe("oauth");
      expect(completedProps.email).toBe("user@example.com");
    });

    it("should not store email in props when JWT is not present at /authorize", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://mcp.claude.ai/callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      let completedProps: any = null;
      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({
            clientId: "test-client",
            scope: [],
          }),
          completeAuthorization: vi.fn().mockImplementation(async (args: any) => {
            completedProps = args.props;
            return { redirectTo: "https://mcp.claude.ai/callback?code=test" };
          }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      // Props should have authMethod but no email (userId is 'mcpbox-user')
      expect(completedProps).toBeDefined();
      expect(completedProps.authMethod).toBe("oauth");
      expect(completedProps.email).toBeUndefined();
    });
  });

  describe("JWT Extraction", () => {
    it("should not set email header when JWT verification not configured", async () => {
      // Without CF_ACCESS_TEAM_DOMAIN/CF_ACCESS_AUD, JWT verification is skipped.
      // Without email in props, no X-MCPbox-User-Email header is set.
      // Email extraction is tested in the "OAuth Props Email" section.
      const jwtPayload = {
        email: "user@example.com",
        sub: "user123",
        iat: Math.floor(Date.now() / 1000),
      };
      const mockJwt = `header.${btoa(JSON.stringify(jwtPayload))}.signature`;

      const request = new Request("https://example.com/mcp", {
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
        // No CF_ACCESS_TEAM_DOMAIN or CF_ACCESS_AUD — JWT verification skipped
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      const [, options] = mockVpcService.fetch.mock.calls[0];
      // Email header should not be set — JWT verification was skipped
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should handle JWT without email claim gracefully", async () => {
      const jwtPayload = {
        sub: "user123",
        iat: Math.floor(Date.now() / 1000),
      };
      const mockJwt = `header.${btoa(JSON.stringify(jwtPayload))}.signature`;

      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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

      const request = new Request("https://example.com/mcp", {
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

      const request = new Request("https://example.com/mcp", {
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

      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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

      const request = new Request("https://example.com/mcp", {
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
    it("should allow /mcp path", async () => {
      const request = new Request("https://example.com/mcp", {
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

    it("should reject /mcp/health path (only /health is pre-OAuth)", async () => {
      // /mcp/health is NOT a recognized path. Only /health is handled pre-OAuth.
      // Unrecognized paths go to defaultHandler which returns 404.
      const request = new Request("https://example.com/mcp/health", {
        method: "GET",
      });

      const mockVpcService = createMockVpcService({ status: "ok" });
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(404);
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
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
      // defaultHandler returns plain text "Not found"
      const text = await response.text();
      expect(text).toBe("Not found");
      // Should NOT have called the VPC service
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });

    it("should rewrite root path to API route (forwarded to gateway)", async () => {
      // POST / and POST /mcp are both rewritten to INTERNAL_API_ROUTE
      // and forwarded to the gateway via VPC.
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

      // Root path is rewritten and forwarded (not 404)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
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
      const request = new Request("https://example.com/mcp", {
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
      const request = new Request("https://example.com/mcp", {
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
    // The Worker does NOT enforce JWTs — it only uses them for identification.
    // Invalid/missing JWTs are gracefully ignored and the request is forwarded
    // to the gateway. JWT enforcement happens at the gateway level.
    // These tests verify that invalid JWTs don't set the email header.

    // Helper to create a base64url encoded string
    const base64url = (obj: object | string) => {
      const str = typeof obj === "string" ? obj : JSON.stringify(obj);
      return btoa(str).replace(/\+/g, "-").replace(/\//g, "_");
    };

    const createMockJwt = (
      header: object,
      payload: object,
      signature = "bW9ja3NpZ25hdHVyZQ"
    ) => {
      return `${base64url(header)}.${base64url(payload)}.${signature}`;
    };

    it("should ignore JWT with algorithm other than RS256 and forward request", async () => {
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

      const request = new Request("https://example.com/mcp", {
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

      // Mock JWKS fetch
      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }] }),
      });

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;

      // Request forwarded (not rejected) — JWT is for identification only
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();

      // Invalid JWT should NOT set the email header
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should ignore JWT with 'none' algorithm and forward request", async () => {
      const header = { alg: "none", kid: "test-kid", typ: "JWT" };
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: Math.floor(Date.now() / 1000) + 3600,
      };
      const mockJwt = createMockJwt(header, payload, "");

      const request = new Request("https://example.com/mcp", {
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

      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }] }),
      });

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should forward request with valid JWT and set email header", async () => {
      const header = { alg: "RS256", kid: "test-kid", typ: "JWT" };
      const now = Math.floor(Date.now() / 1000);
      const payload = {
        sub: "user123",
        email: "user@example.com",
        aud: "test-aud",
        iss: "https://myteam.cloudflareaccess.com",
        exp: now + 3600,
        nbf: now - 60,
        iat: now - 60,
      };
      const mockJwt = createMockJwt(header, payload);

      const request = new Request("https://example.com/mcp", {
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
        json: () => Promise.resolve({ keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }] }),
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

      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();

      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBe("user@example.com");
      expect(options.headers.get("X-MCPbox-Auth-Method")).toBe("jwt");
    });

    it("should ignore expired JWT and forward without email", async () => {
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

      const request = new Request("https://example.com/mcp", {
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
        json: () => Promise.resolve({ keys: [{ kid: "test-kid", kty: "RSA", n: "test-n", e: "AQAB" }] }),
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

      // Forwarded without email (expired JWT ignored)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
      const [, options] = mockVpcService.fetch.mock.calls[0];
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

      // Should be rejected because path contains ..
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

      // URL parsing normalizes %2e%2e to .., then path validation rejects it
      expect(response.status).toBe(404);
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });
  });

  describe("JWT Authentication", () => {
    it("should forward requests without JWT when auth is configured (no enforcement)", async () => {
      // Worker does NOT enforce JWTs — it only uses them for identification.
      // Missing JWT means no email header, but request is still forwarded.
      const request = new Request("https://example.com/mcp", {
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

      // Request forwarded (not rejected) — JWT enforcement is at the gateway
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();

      // No email header without JWT
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should allow requests without JWT when auth is not configured", async () => {
      const request = new Request("https://example.com/mcp", {
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

    it("should forward requests with invalid JWT when auth is configured (no enforcement)", async () => {
      // Invalid JWT is ignored — request forwarded without email header.
      const request = new Request("https://example.com/mcp", {
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

      // Mock fetch for JWKS endpoint
      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ keys: [] }),
      });

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      global.fetch = originalFetch;

      // Forwarded, not rejected
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();

      // No email header with invalid JWT
      const [, options] = mockVpcService.fetch.mock.calls[0];
      expect(options.headers.get("X-MCPbox-User-Email")).toBeNull();
    });

    it("should include CORS headers when upstream returns 401", async () => {
      const request = new Request("https://example.com/mcp", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "https://claude.ai",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      // VPC returns 401 (e.g., gateway rejected the request)
      const mockVpcService = createMockVpcService({ error: "Unauthorized" }, 401);
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(401);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://claude.ai"
      );
    });
  });

  describe("URL Rewriting", () => {
    it("should rewrite POST / to internal API route and forward to gateway", async () => {
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

      // Should be forwarded to gateway (not 404), proving it was rewritten
      // to the API route and processed by OAuthProvider → apiHandler
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should rewrite POST /mcp to internal API route and forward to gateway", async () => {
      const request = new Request("https://example.com/mcp", {
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

      // Should be forwarded to gateway (not 404)
      expect(response.status).toBe(200);
      expect(mockVpcService.fetch).toHaveBeenCalled();
    });

    it("should not rewrite GET /authorize (OAuth flow endpoint)", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test&redirect_uri=https://mcp.claude.ai/callback&response_type=code",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // /authorize is handled by defaultHandler, not rewritten to API route.
      // It should NOT return 401 (which would mean it went through OAuth validation).
      // It may return 400 (invalid OAuth request) or 302 (redirect), but not 401 or 404.
      expect(response.status).not.toBe(401);
      expect(response.status).not.toBe(404);
    });

    it("should not rewrite GET /.well-known/oauth-authorization-server", async () => {
      const request = new Request(
        "https://example.com/.well-known/oauth-authorization-server",
        { method: "GET" },
      );

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // This path is handled by OAuthProvider as a built-in (not by apiHandler).
      // With our mock, it falls through to defaultHandler → 404.
      // The key assertion: VPC was NOT called, proving it wasn't rewritten to the API route.
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
      expect(response.status).not.toBe(200);
    });

    it("should handle OPTIONS /mcp before URL rewriting (CORS preflight)", async () => {
      const request = new Request("https://example.com/mcp", {
        method: "OPTIONS",
        headers: { Origin: "https://mcp.claude.ai" },
      });

      const mockVpcService = createMockVpcService({});
      const mockEnv = {
        MCPBOX_TUNNEL: mockVpcService,
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // OPTIONS is handled pre-OAuth, should return 200 with CORS headers
      expect(response.status).toBe(200);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://mcp.claude.ai"
      );
      // Should NOT have called the VPC service
      expect(mockVpcService.fetch).not.toHaveBeenCalled();
    });
  });

  describe("PRM Endpoints", () => {
    it("should return PRM with origin-only resource at root path", async () => {
      const request = new Request(
        "https://my-worker.workers.dev/.well-known/oauth-protected-resource",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as {
        resource: string;
        authorization_servers: string[];
      };
      expect(body.resource).toBe("https://my-worker.workers.dev");
      expect(body.authorization_servers).toEqual([
        "https://my-worker.workers.dev",
      ]);
    });

    it("should return PRM with /mcp resource at /mcp path", async () => {
      const request = new Request(
        "https://my-worker.workers.dev/.well-known/oauth-protected-resource/mcp",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as {
        resource: string;
        authorization_servers: string[];
      };
      expect(body.resource).toBe("https://my-worker.workers.dev/mcp");
      expect(body.authorization_servers).toEqual([
        "https://my-worker.workers.dev",
      ]);
    });

    it("should include bearer_methods_supported in PRM response", async () => {
      const request = new Request(
        "https://example.com/.well-known/oauth-protected-resource",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(200);
      const body = (await response.json()) as {
        bearer_methods_supported: string[];
        scopes_supported: string[];
      };
      expect(body.bearer_methods_supported).toEqual(["header"]);
      expect(body.scopes_supported).toEqual([]);
    });
  });

  describe("Redirect URI Validation", () => {
    it("should allow claude.ai redirect URIs", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://mcp.claude.ai/oauth/callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({ clientId: "test-client", scope: [] }),
          completeAuthorization: vi.fn().mockResolvedValue({ redirectTo: "https://mcp.claude.ai/oauth/callback?code=test" }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should not be rejected for redirect_uri (302 redirect on success)
      expect(response.status).not.toBe(400);
    });

    it("should allow Cloudflare dashboard redirect URIs", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://one.dash.cloudflare.com/mcp-callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({ clientId: "test-client", scope: [] }),
          completeAuthorization: vi.fn().mockResolvedValue({ redirectTo: "https://one.dash.cloudflare.com/mcp-callback?code=test" }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should not be rejected for redirect_uri
      expect(response.status).not.toBe(400);
    });

    it("should allow portal hostname redirect URIs when configured", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://mcp.example.com/servers-callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        MCP_PORTAL_HOSTNAME: "mcp.example.com",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({ clientId: "test-client", scope: [] }),
          completeAuthorization: vi.fn().mockResolvedValue({ redirectTo: "https://mcp.example.com/servers-callback?code=test" }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should not be rejected for redirect_uri
      expect(response.status).not.toBe(400);
    });

    it("should reject arbitrary domain redirect URIs", async () => {
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://evil.com/steal-token&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      // No OAUTH_PROVIDER needed — redirect_uri validation happens before parseAuthRequest
      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(400);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("Invalid redirect_uri");
    });

    it("should validate with static patterns when MCP_PORTAL_HOSTNAME is not set", async () => {
      // Without MCP_PORTAL_HOSTNAME, only static patterns should work
      const request = new Request(
        "https://example.com/authorize?client_id=test-client&redirect_uri=https://mcp.claude.ai/callback&response_type=code&code_challenge=test&code_challenge_method=S256",
        { method: "GET" },
      );

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        // No MCP_PORTAL_HOSTNAME
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null),
          put: vi.fn().mockResolvedValue(undefined),
        },
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({ clientId: "test-client", scope: [] }),
          completeAuthorization: vi.fn().mockResolvedValue({ redirectTo: "https://mcp.claude.ai/callback?code=test" }),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Static patterns still work without MCP_PORTAL_HOSTNAME
      expect(response.status).not.toBe(400);
    });
  });

  describe("401 WWW-Authenticate Header", () => {
    it("should include resource_metadata in 401 for /mcp path", async () => {
      const request = new Request("https://my-worker.workers.dev/mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      // VPC returns 401 → apiHandler returns 401 → outer handler adds WWW-Authenticate
      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({ error: "Unauthorized" }, 401),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(401);
      const wwwAuth = response.headers.get("WWW-Authenticate");
      expect(wwwAuth).toContain("resource_metadata=");
      expect(wwwAuth).toContain(
        "/.well-known/oauth-protected-resource/mcp"
      );
    });

    it("should include resource_metadata in 401 for / path", async () => {
      const request = new Request("https://my-worker.workers.dev/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      });

      // VPC returns 401 → apiHandler returns 401 → outer handler adds WWW-Authenticate
      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({ error: "Unauthorized" }, 401),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(401);
      const wwwAuth = response.headers.get("WWW-Authenticate");
      expect(wwwAuth).toContain("resource_metadata=");
      // Root path should NOT include /mcp suffix
      expect(wwwAuth).toContain(
        "/.well-known/oauth-protected-resource\""
      );
      expect(wwwAuth).not.toContain(
        "/.well-known/oauth-protected-resource/mcp"
      );
    });
  });

  describe("CORS for Cloudflare Dashboard", () => {
    it("should allow one.dash.cloudflare.com origin", async () => {
      const request = new Request("https://example.com/mcp", {
        method: "OPTIONS",
        headers: { Origin: "https://one.dash.cloudflare.com" },
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
        "https://one.dash.cloudflare.com"
      );
    });
  });

  describe("/register Redirect URI Validation", () => {
    it("should reject /register with invalid redirect_uris", async () => {
      const request = new Request("https://example.com/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          redirect_uris: ["https://evil.com/steal-token"],
          grant_types: ["authorization_code"],
          response_types: ["code"],
          token_endpoint_auth_method: "none",
        }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(400);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("invalid_redirect_uri");
    });

    it("should allow /register with valid redirect_uris", async () => {
      const request = new Request("https://example.com/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          redirect_uris: ["https://mcp.claude.ai/callback"],
          grant_types: ["authorization_code"],
          response_types: ["code"],
          token_endpoint_auth_method: "none",
        }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      // Should pass validation and reach OAuthProvider (mock returns 404 via defaultHandler)
      expect(response.status).not.toBe(400);
    });

    it("should reject /register if any redirect_uri is invalid", async () => {
      const request = new Request("https://example.com/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          redirect_uris: [
            "https://mcp.claude.ai/callback",
            "https://evil.com/steal",
          ],
        }),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(400);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("invalid_redirect_uri");
    });
  });

  describe("/token Auto-Registration Validation", () => {
    it("should reject /token auto-registration with invalid redirect_uri", async () => {
      const params = new URLSearchParams({
        client_id: "new-client",
        redirect_uri: "https://evil.com/steal",
        grant_type: "authorization_code",
        code: "test-code",
      });

      const request = new Request("https://example.com/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null), // client doesn't exist
          put: vi.fn().mockResolvedValue(undefined),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      const response = await worker.fetch(request, mockEnv, ctx as any);

      expect(response.status).toBe(400);
      const body = (await response.json()) as { error: string };
      expect(body.error).toBe("invalid_redirect_uri");
      // Should NOT have registered the client
      expect(mockEnv.OAUTH_KV.put).not.toHaveBeenCalled();
    });

    it("should include redirect_uri in auto-registered client data", async () => {
      const params = new URLSearchParams({
        client_id: "new-client",
        redirect_uri: "https://mcp.claude.ai/callback",
        grant_type: "authorization_code",
        code: "test-code",
      });

      const request = new Request("https://example.com/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
      });

      const mockEnv = {
        MCPBOX_TUNNEL: createMockVpcService({}),
        MCPBOX_SERVICE_TOKEN: "test-token",
        OAUTH_KV: {
          get: vi.fn().mockResolvedValue(null), // client doesn't exist
          put: vi.fn().mockResolvedValue(undefined),
        },
      } as unknown as Env;

      const ctx = createExecutionContext();
      await worker.fetch(request, mockEnv, ctx as any);

      // Client should be registered with the redirect_uri
      expect(mockEnv.OAUTH_KV.put).toHaveBeenCalled();
      const putCall = mockEnv.OAUTH_KV.put.mock.calls[0];
      const clientData = JSON.parse(putCall[1]);
      expect(clientData.redirectUris).toEqual(["https://mcp.claude.ai/callback"]);
    });
  });
});
