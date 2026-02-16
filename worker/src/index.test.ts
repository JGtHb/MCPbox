/**
 * Tests for MCPbox MCP Proxy Worker (OIDC-based architecture)
 *
 * These tests verify the Cloudflare Worker's behavior with the new OIDC
 * (Access for SaaS) authentication flow. The Worker uses OAuthProvider from
 * @cloudflare/workers-oauth-provider to wrap MCP endpoints with OAuth 2.1.
 *
 * Architecture:
 * - OAuthProvider wraps the Worker, routing requests to apiHandler or defaultHandler
 * - apiHandler handles OAuth-protected MCP requests (proxied to MCPbox gateway via VPC)
 * - defaultHandler handles /authorize, /callback (OIDC upstream), and unmatched paths
 * - Pre-OAuth endpoints (/health, PRM, OPTIONS) are handled before OAuthProvider
 *
 * We mock OAuthProvider to bypass real OAuth token validation and test
 * the MCPbox-specific logic (URL rewriting, header injection, CORS, etc.).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock OAuthProvider to pass requests through to apiHandler/defaultHandler
// without requiring real OAuth tokens. This lets us test MCPbox-specific logic.
vi.mock('@cloudflare/workers-oauth-provider', () => {
  return {
    default: class MockOAuthProvider {
      apiRoute: string;
      apiHandler: { fetch: Function };
      defaultHandler: { fetch: Function };

      constructor(config: {
        apiRoute: string;
        apiHandler: { fetch: Function };
        defaultHandler: { fetch: Function };
        authorizeEndpoint: string;
        tokenEndpoint: string;
        clientRegistrationEndpoint: string;
      }) {
        this.apiRoute = config.apiRoute;
        this.apiHandler = config.apiHandler;
        this.defaultHandler = config.defaultHandler;
      }

      async fetch(
        request: Request,
        env: unknown,
        ctx: unknown,
      ): Promise<Response> {
        const url = new URL(request.url);
        if (url.pathname === this.apiRoute) {
          // Simulate OAuthProvider validating the token and injecting props into ctx.
          // Default: no email (anonymous OAuth client). Tests that need email
          // should provide it via _testProps on the env.
          const testEnv = env as Record<string, unknown>;
          const props = testEnv._testProps || { authMethod: 'oidc' };
          const enrichedCtx = {
            ...(ctx as object),
            props,
          };
          return this.apiHandler.fetch(request, env, enrichedCtx);
        }
        // Non-API routes go to defaultHandler
        return this.defaultHandler.fetch(request, env, ctx);
      }
    },
  };
});

import worker, { type Env } from './index';

// ---------------------------------------------------------------------------
// Test Helpers
// ---------------------------------------------------------------------------

const createExecutionContext = () => ({
  waitUntil: vi.fn(),
  passThroughOnException: vi.fn(),
});

/** Create a mock VPC service binding that returns a canned response. */
const createMockVpcService = (responseBody: unknown, status = 200) => ({
  fetch: vi.fn().mockResolvedValue(
    new Response(JSON.stringify(responseBody), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  ),
});

/** Create a mock KV namespace. */
const createMockKV = () => ({
  get: vi.fn().mockResolvedValue(null),
  put: vi.fn().mockResolvedValue(undefined),
  delete: vi.fn().mockResolvedValue(undefined),
});

/** Base env with all required fields for apiHandler to succeed. */
const createBaseEnv = (overrides: Partial<Record<string, unknown>> = {}) => {
  const defaults: Record<string, unknown> = {
    MCPBOX_TUNNEL: createMockVpcService({}),
    MCPBOX_SERVICE_TOKEN: 'test-service-token-32chars-min!!!!',
    OAUTH_KV: createMockKV(),
    ACCESS_CLIENT_ID: 'test-access-client-id',
    ACCESS_CLIENT_SECRET: 'test-access-client-secret',
    ACCESS_TOKEN_URL: 'https://myteam.cloudflareaccess.com/cdn-cgi/access/sso/oidc/test/token',
    ACCESS_AUTHORIZATION_URL: 'https://myteam.cloudflareaccess.com/cdn-cgi/access/sso/oidc/test/authorize',
    ACCESS_JWKS_URL: 'https://myteam.cloudflareaccess.com/cdn-cgi/access/certs',
    COOKIE_ENCRYPTION_KEY: 'a'.repeat(64),
  };
  return { ...defaults, ...overrides } as unknown as Env;
};

// =============================================================================
// Tests
// =============================================================================

describe('MCPbox Proxy Worker', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // ===========================================================================
  // 1. Pre-OAuth Endpoints (no auth needed)
  // ===========================================================================

  describe('Pre-OAuth Endpoints', () => {
    it('GET /health returns 200 with { status: "ok" }', async () => {
      const request = new Request('https://example.com/health', { method: 'GET' });
      const env = createBaseEnv();
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as { status: string };
      expect(body.status).toBe('ok');
      expect(response.headers.get('Content-Type')).toBe('application/json');
    });

    it('GET /health/ also returns 200 (startsWith match)', async () => {
      const request = new Request('https://example.com/health/', { method: 'GET' });
      const env = createBaseEnv();
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as { status: string };
      expect(body.status).toBe('ok');
    });

    it('GET /.well-known/oauth-protected-resource returns correct PRM metadata', async () => {
      const request = new Request(
        'https://my-worker.workers.dev/.well-known/oauth-protected-resource',
        { method: 'GET' },
      );
      const env = createBaseEnv();
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as Record<string, unknown>;
      expect(body.resource).toBe('https://my-worker.workers.dev');
      expect(body.authorization_servers).toEqual(['https://my-worker.workers.dev']);
      expect(body.bearer_methods_supported).toEqual(['header']);
      expect(body.scopes_supported).toEqual([]);
    });

    it('GET /.well-known/oauth-protected-resource/mcp returns PRM with origin-only resource', async () => {
      // resource MUST be origin-only (no path) to avoid audience mismatch
      // with OAuthProvider, which computes resourceServer as origin-only.
      const request = new Request(
        'https://my-worker.workers.dev/.well-known/oauth-protected-resource/mcp',
        { method: 'GET' },
      );
      const env = createBaseEnv();
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as Record<string, unknown>;
      expect(body.resource).toBe('https://my-worker.workers.dev');
      expect(body.authorization_servers).toEqual(['https://my-worker.workers.dev']);
    });

    it('OPTIONS requests return CORS headers without hitting VPC', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'OPTIONS',
        headers: { Origin: 'https://mcp.claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
      expect(response.headers.get('Access-Control-Allow-Methods')).toContain('POST');
      expect(response.headers.get('Access-Control-Allow-Headers')).toContain('Content-Type');
      expect(response.headers.get('Access-Control-Allow-Headers')).toContain('Authorization');
      expect(response.headers.get('Access-Control-Max-Age')).toBe('86400');
      // VPC should NOT have been called
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });

    it('OPTIONS requests on any path return CORS (including /api/servers)', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/api/servers', {
        method: 'OPTIONS',
        headers: { Origin: 'https://claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://claude.ai');
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // 2. URL Rewriting
  // ===========================================================================

  describe('URL Rewriting', () => {
    it('POST / rewrites to internal API route and proxies to gateway', async () => {
      const mockVpc = createMockVpcService({ jsonrpc: '2.0', id: 1, result: {} });
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpc.fetch).toHaveBeenCalledOnce();
      const [targetUrl] = mockVpc.fetch.mock.calls[0];
      expect(targetUrl).toBe('http://mcp-gateway:8002/mcp');
    });

    it('POST /mcp rewrites to internal API route and proxies to gateway', async () => {
      const mockVpc = createMockVpcService({ jsonrpc: '2.0', id: 1, result: {} });
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      expect(mockVpc.fetch).toHaveBeenCalledOnce();
      const [targetUrl] = mockVpc.fetch.mock.calls[0];
      expect(targetUrl).toBe('http://mcp-gateway:8002/mcp');
    });

    it('POST /mcp preserves query parameters', async () => {
      const mockVpc = createMockVpcService({ status: 'ok' });
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp?session=abc123', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [targetUrl] = mockVpc.fetch.mock.calls[0];
      expect(targetUrl).toBe('http://mcp-gateway:8002/mcp?session=abc123');
    });

    it('unknown paths return 404 via defaultHandler', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/api/servers', { method: 'GET' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(404);
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });

    it('/mcp/health is not a recognized path (returns 404)', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp/health', { method: 'GET' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(404);
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });

    it('path traversal attempt resolves to rejected path', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp/../api/servers', { method: 'GET' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(404);
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });

    it('/authorize is NOT rewritten (handled by defaultHandler for OIDC)', async () => {
      const env = createBaseEnv({
        OAUTH_PROVIDER: {
          parseAuthRequest: vi.fn().mockResolvedValue({ clientId: 'test', scope: [] }),
          completeAuthorization: vi.fn().mockResolvedValue({ redirectTo: 'https://mcp.claude.ai/callback?code=x' }),
        },
      });
      const request = new Request(
        'https://example.com/authorize?client_id=test&redirect_uri=https://mcp.claude.ai/callback&response_type=code',
        { method: 'GET' },
      );
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // /authorize goes through defaultHandler, not through apiHandler.
      // It should not return 401 (OAuth) or 200 (proxy success).
      expect(response.status).not.toBe(401);
    });

    it('/.well-known/oauth-authorization-server is NOT rewritten (passes to OAuthProvider)', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request(
        'https://example.com/.well-known/oauth-authorization-server',
        { method: 'GET' },
      );
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // Not rewritten to API route, so VPC is never called
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // 3. OAuth Client Registration (POST /register)
  // ===========================================================================

  describe('OAuth Client Registration (POST /register)', () => {
    it('accepts valid redirect URI (mcp.claude.ai)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['https://mcp.claude.ai/callback'],
          grant_types: ['authorization_code'],
          response_types: ['code'],
          token_endpoint_auth_method: 'none',
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // Should pass validation (not 400). Reaches OAuthProvider mock -> defaultHandler -> 404
      expect(response.status).not.toBe(400);
    });

    it('accepts valid redirect URI (claude.ai)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['https://claude.ai/oauth/callback'],
          grant_types: ['authorization_code'],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).not.toBe(400);
    });

    it('accepts valid redirect URI (one.dash.cloudflare.com)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['https://one.dash.cloudflare.com/mcp-callback'],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).not.toBe(400);
    });

    it('accepts valid redirect URI (localhost)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['http://localhost:3000/callback'],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).not.toBe(400);
    });

    it('accepts valid redirect URI (127.0.0.1)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['http://127.0.0.1:8080/callback'],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).not.toBe(400);
    });

    it('rejects invalid redirect URI with 400', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: ['https://evil.com/steal-token'],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(400);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('invalid_redirect_uri');
    });

    it('rejects if any redirect_uri is invalid (mixed valid/invalid)', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          redirect_uris: [
            'https://mcp.claude.ai/callback',
            'https://evil.com/steal',
          ],
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(400);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('invalid_redirect_uri');
    });
  });

  // ===========================================================================
  // 4. Auto-Registration at /token
  // ===========================================================================

  describe('Auto-Registration at /token', () => {
    it('auto-registers unknown client with valid redirect_uri', async () => {
      const mockKv = createMockKV();
      const env = createBaseEnv({ OAUTH_KV: mockKv });
      const params = new URLSearchParams({
        client_id: 'new-client',
        redirect_uri: 'https://mcp.claude.ai/callback',
        grant_type: 'authorization_code',
        code: 'test-code',
      });
      const request = new Request('https://example.com/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      // Client should be auto-registered in KV
      expect(mockKv.put).toHaveBeenCalled();
      const [kvKey, kvValue] = mockKv.put.mock.calls[0];
      expect(kvKey).toBe('client:new-client');
      const clientData = JSON.parse(kvValue);
      expect(clientData.clientId).toBe('new-client');
      expect(clientData.redirectUris).toEqual(['https://mcp.claude.ai/callback']);
      expect(clientData.grantTypes).toContain('authorization_code');
    });

    it('rejects /token auto-registration with invalid redirect_uri', async () => {
      const mockKv = createMockKV();
      const env = createBaseEnv({ OAUTH_KV: mockKv });
      const params = new URLSearchParams({
        client_id: 'new-client',
        redirect_uri: 'https://evil.com/steal',
        grant_type: 'authorization_code',
        code: 'test-code',
      });
      const request = new Request('https://example.com/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(400);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('invalid_redirect_uri');
      // Should NOT have registered the client
      expect(mockKv.put).not.toHaveBeenCalled();
    });

    it('does not re-register existing client', async () => {
      const mockKv = createMockKV();
      mockKv.get.mockResolvedValue(JSON.stringify({ clientId: 'existing-client' }));
      const env = createBaseEnv({ OAUTH_KV: mockKv });
      const params = new URLSearchParams({
        client_id: 'existing-client',
        redirect_uri: 'https://mcp.claude.ai/callback',
        grant_type: 'authorization_code',
        code: 'test-code',
      });
      const request = new Request('https://example.com/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      // Should look up but not write again
      expect(mockKv.get).toHaveBeenCalledWith('client:existing-client');
      expect(mockKv.put).not.toHaveBeenCalled();
    });

    it('allows /token without redirect_uri (no validation needed)', async () => {
      const mockKv = createMockKV();
      const env = createBaseEnv({ OAUTH_KV: mockKv });
      const params = new URLSearchParams({
        client_id: 'some-client',
        grant_type: 'refresh_token',
        refresh_token: 'some-token',
      });
      const request = new Request('https://example.com/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // No redirect_uri → no validation error
      expect(response.status).not.toBe(400);
    });

    it('rate-limits /token auto-registration (shares counter with /register)', async () => {
      const mockKv = createMockKV();
      // Simulate rate limit already at threshold
      mockKv.get.mockImplementation(async (key: string) => {
        if (key.startsWith('ratelimit:register:')) return '10';
        if (key.startsWith('client:')) return null; // client not registered
        return null;
      });
      const env = createBaseEnv({ OAUTH_KV: mockKv });
      const params = new URLSearchParams({
        client_id: 'new-rate-limited-client',
        redirect_uri: 'https://mcp.claude.ai/callback',
        grant_type: 'authorization_code',
        code: 'test-code',
      });
      const request = new Request('https://example.com/token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'CF-Connecting-IP': '1.2.3.4',
        },
        body: params.toString(),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(429);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('too_many_requests');
      // Should NOT have registered the client
      expect(mockKv.put).not.toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // 5. CORS
  // ===========================================================================

  describe('CORS', () => {
    it('allows https://mcp.claude.ai origin', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://mcp.claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
    });

    it('allows https://claude.ai origin', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://claude.ai');
    });

    it('allows https://one.dash.cloudflare.com origin', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://one.dash.cloudflare.com' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://one.dash.cloudflare.com');
    });

    it('falls back to https://mcp.claude.ai for non-allowed origins', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://unknown-origin.com' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
    });

    it('falls back to https://mcp.claude.ai when no Origin header', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/health', { method: 'GET' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
    });

    it('uses custom CORS_ALLOWED_ORIGIN when set', async () => {
      const env = createBaseEnv({ CORS_ALLOWED_ORIGIN: 'https://custom.example.com' });
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://anything.com' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://custom.example.com');
    });

    it('rejects CORS_ALLOWED_ORIGIN="*" and falls back to default', async () => {
      const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const env = createBaseEnv({ CORS_ALLOWED_ORIGIN: '*' });
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://mcp.claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // Should fall back to default behavior (not *)
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
      consoleSpy.mockRestore();
    });

    it('includes CORS headers in error responses (503)', async () => {
      const env = createBaseEnv({ MCPBOX_TUNNEL: undefined });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Origin: 'https://claude.ai',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(503);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://claude.ai');
    });

    it('includes CORS headers in error responses (502)', async () => {
      const failingVpc = { fetch: vi.fn().mockRejectedValue(new Error('Connection failed')) };
      const env = createBaseEnv({ MCPBOX_TUNNEL: failingVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Origin: 'https://mcp.claude.ai',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(502);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://mcp.claude.ai');
    });

    it('includes CORS headers in 404 responses from defaultHandler', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/api/admin', {
        method: 'GET',
        headers: { Origin: 'https://claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(404);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://claude.ai');
    });

    it('includes correct allowed methods and headers', async () => {
      const env = createBaseEnv();
      const request = new Request('https://example.com/', {
        method: 'OPTIONS',
        headers: { Origin: 'https://mcp.claude.ai' },
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.headers.get('Access-Control-Allow-Methods')).toBe('GET, POST, DELETE, OPTIONS');
      expect(response.headers.get('Access-Control-Allow-Headers')).toBe('Content-Type, Authorization, Mcp-Session-Id');
    });
  });

  // ===========================================================================
  // 6. API Handler (OAuth-protected MCP endpoint)
  // ===========================================================================

  describe('API Handler (OAuth-protected MCP endpoint)', () => {
    it('adds X-MCPbox-Service-Token header to proxied requests', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({
        MCPBOX_TUNNEL: mockVpc,
        MCPBOX_SERVICE_TOKEN: 'my-secret-service-token-is-long-enough',
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      expect(mockVpc.fetch).toHaveBeenCalledOnce();
      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-MCPbox-Service-Token')).toBe('my-secret-service-token-is-long-enough');
    });

    it('sets X-MCPbox-User-Email from OAuth props (OIDC-verified email)', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({
        MCPBOX_TUNNEL: mockVpc,
        // _testProps is consumed by our MockOAuthProvider to inject into ctx.props
        _testProps: { email: 'user@example.com', authMethod: 'oidc' },
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-MCPbox-User-Email')).toBe('user@example.com');
    });

    it('does not set X-MCPbox-User-Email when OAuth props have no email', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({
        MCPBOX_TUNNEL: mockVpc,
        _testProps: { authMethod: 'oidc' }, // no email
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-MCPbox-User-Email')).toBeNull();
    });

    it('SECURITY: strips client-supplied X-MCPbox-User-Email header', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({
        MCPBOX_TUNNEL: mockVpc,
        _testProps: { authMethod: 'oidc' }, // no email in props
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // Attacker tries to inject email
          'X-MCPbox-User-Email': 'attacker@evil.com',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      // Attacker's email should be stripped (no email in props = no header)
      expect(options.headers.get('X-MCPbox-User-Email')).toBeNull();
    });

    it('SECURITY: strips client-supplied X-MCPbox-Auth-Method header', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          // Attacker tries to set auth method
          'X-MCPbox-Auth-Method': 'admin',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      // Auth method is always overwritten to 'oidc'
      expect(options.headers.get('X-MCPbox-Auth-Method')).toBe('oidc');
    });

    it('always sets X-MCPbox-Auth-Method to "oidc"', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-MCPbox-Auth-Method')).toBe('oidc');
    });

    it('SECURITY: overwrites attacker service token with real one', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({
        MCPBOX_TUNNEL: mockVpc,
        MCPBOX_SERVICE_TOKEN: 'real-service-token-long-enough-for-test',
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-MCPbox-Service-Token': 'attacker-token',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-MCPbox-Service-Token')).toBe('real-service-token-long-enough-for-test');
    });

    it('adds X-Forwarded-Host and X-Forwarded-Proto headers', async () => {
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://my-worker.workers.dev/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      await worker.fetch(request, env, ctx as any);

      const [, options] = mockVpc.fetch.mock.calls[0];
      expect(options.headers.get('X-Forwarded-Host')).toBe('my-worker.workers.dev');
      expect(options.headers.get('X-Forwarded-Proto')).toBe('https');
    });

    it('returns 503 when MCPBOX_TUNNEL is not configured', async () => {
      const env = createBaseEnv({ MCPBOX_TUNNEL: undefined });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(503);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('Service temporarily unavailable');
    });

    it('returns 503 when MCPBOX_SERVICE_TOKEN is not configured', async () => {
      const env = createBaseEnv({ MCPBOX_SERVICE_TOKEN: '' });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(503);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('Service temporarily unavailable');
    });

    it('returns 404 for non-API-route paths inside apiHandler', async () => {
      // This tests the apiHandler path check. The mock OAuthProvider only routes
      // to apiHandler when pathname === INTERNAL_API_ROUTE. But in real code,
      // non-rewritten paths go to defaultHandler which returns 404.
      const mockVpc = createMockVpcService({});
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/some/random/path', { method: 'POST' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(404);
      expect(mockVpc.fetch).not.toHaveBeenCalled();
    });

    it('returns 502 when VPC connection fails', async () => {
      const failingVpc = { fetch: vi.fn().mockRejectedValue(new Error('Connection refused')) };
      const env = createBaseEnv({ MCPBOX_TUNNEL: failingVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(502);
      const body = await response.json() as { error: string };
      expect(body.error).toBe('Failed to connect to backend service');
    });

    it('does not leak service token in error responses', async () => {
      const failingVpc = { fetch: vi.fn().mockRejectedValue(new Error('Network error')) };
      const env = createBaseEnv({
        MCPBOX_TUNNEL: failingVpc,
        MCPBOX_SERVICE_TOKEN: 'super-secret-token-do-not-leak!!',
      });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      const text = await response.text();
      expect(text).not.toContain('super-secret-token-do-not-leak!!');
    });

    it('preserves upstream status codes from gateway', async () => {
      const mockVpc = createMockVpcService({ error: 'Internal error' }, 500);
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(500);
    });

    it('adds CORS headers to proxied response', async () => {
      const mockVpc = createMockVpcService({ jsonrpc: '2.0', id: 1, result: { tools: [] } });
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Origin: 'https://claude.ai',
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      expect(response.headers.get('Access-Control-Allow-Origin')).toBe('https://claude.ai');
      expect(response.headers.get('Access-Control-Allow-Methods')).toBe('GET, POST, DELETE, OPTIONS');
    });

    it('forwards MCP tools/list requests correctly', async () => {
      const expectedResponse = {
        jsonrpc: '2.0',
        id: 'test-1',
        result: { tools: [{ name: 'mcpbox_list_servers', description: 'List servers' }] },
      };
      const mockVpc = createMockVpcService(expectedResponse);
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 'test-1', method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as any;
      expect(body.jsonrpc).toBe('2.0');
      expect(body.id).toBe('test-1');
      expect(body.result.tools).toHaveLength(1);
    });

    it('forwards MCP tools/call requests with arguments', async () => {
      const expectedResponse = {
        jsonrpc: '2.0',
        id: 42,
        result: { content: [{ type: 'text', text: '{"id": 1}' }] },
      };
      const mockVpc = createMockVpcService(expectedResponse);
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://example.com/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 42,
          method: 'tools/call',
          params: { name: 'mcpbox_create_server', arguments: { name: 'my-server' } },
        }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(200);
      const body = await response.json() as any;
      expect(body.id).toBe(42);
      expect(body.result.content[0].type).toBe('text');
    });
  });

  // ===========================================================================
  // 7. 401 Response Handling (WWW-Authenticate with resource_metadata)
  // ===========================================================================

  describe('401 Response Handling', () => {
    it('401 for / includes WWW-Authenticate with resource_metadata (no /mcp suffix)', async () => {
      // When VPC returns 401, the outer handler adds resource_metadata
      const mockVpc = createMockVpcService({ error: 'Unauthorized' }, 401);
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://my-worker.workers.dev/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(401);
      const wwwAuth = response.headers.get('WWW-Authenticate');
      expect(wwwAuth).toBeTruthy();
      expect(wwwAuth).toContain('resource_metadata=');
      expect(wwwAuth).toContain('/.well-known/oauth-protected-resource"');
      // Should NOT contain /mcp suffix for root path
      expect(wwwAuth).not.toContain('/.well-known/oauth-protected-resource/mcp');
    });

    it('401 for /mcp includes WWW-Authenticate with resource_metadata', async () => {
      // PRM URL is always origin-only (no /mcp suffix) to match the
      // resource field in PRM responses and avoid audience mismatch.
      const mockVpc = createMockVpcService({ error: 'Unauthorized' }, 401);
      const env = createBaseEnv({ MCPBOX_TUNNEL: mockVpc });
      const request = new Request('https://my-worker.workers.dev/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
      });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      expect(response.status).toBe(401);
      const wwwAuth = response.headers.get('WWW-Authenticate');
      expect(wwwAuth).toBeTruthy();
      expect(wwwAuth).toContain('resource_metadata=');
      expect(wwwAuth).toContain('/.well-known/oauth-protected-resource');
      // Should NOT contain /mcp suffix — PRM URL is origin-only
      expect(wwwAuth).not.toContain('/.well-known/oauth-protected-resource/mcp');
    });

    it('non-MCP-path 401 does NOT get resource_metadata added', async () => {
      // 401 for paths other than / or /mcp should not get WWW-Authenticate modification.
      // This is somewhat theoretical since only / and /mcp reach apiHandler,
      // but let's test that defaultHandler 404s don't become 401s with resource_metadata.
      const env = createBaseEnv();
      const request = new Request('https://example.com/random', { method: 'GET' });
      const ctx = createExecutionContext();

      const response = await worker.fetch(request, env, ctx as any);

      // Returns 404 (not 401), so no WWW-Authenticate
      expect(response.status).toBe(404);
      expect(response.headers.get('WWW-Authenticate')).toBeNull();
    });
  });
});
