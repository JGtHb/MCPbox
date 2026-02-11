/**
 * MCPbox MCP Proxy Worker
 *
 * This Cloudflare Worker acts as an OAuth 2.1 protected proxy between
 * MCP clients and your local MCPbox instance. It uses Workers VPC to
 * access your tunnel privately (no public hostname needed).
 *
 * Authentication layers:
 * 1. OAuth 2.1 (Client -> Worker): Managed by @cloudflare/workers-oauth-provider.
 *    All MCP requests require a valid OAuth token. Cloudflare's MCP Server
 *    sync discovers the OAuth endpoints and completes the flow automatically.
 * 2. Cf-Access-Jwt-Assertion (User identity): Users via MCP Portal also have
 *    a JWT from Cloudflare Access, used to identify the user for tool execution.
 * 3. Service token (Worker -> MCPbox): Defense-in-depth, unchanged.
 *
 * Security:
 * - The tunnel has NO public hostname - only accessible via Workers VPC
 * - MCPbox validates the service token as defense in depth
 * - User email is extracted from the MCP Portal JWT for audit logging
 * - Unauthenticated requests are rejected by OAuthProvider (401)
 */

import OAuthProvider, { type OAuthHelpers } from '@cloudflare/workers-oauth-provider';

// Workers VPC Service binding type
interface VpcService {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

// Props stored in OAuth token (encrypted, set during authorization)
interface Props {
  authMethod: string;
}

export interface Env {
  // Workers VPC binding to MCPbox tunnel (configured in wrangler.toml)
  MCPBOX_TUNNEL: VpcService;
  // Shared secret for authenticating with MCPbox (defense in depth)
  MCPBOX_SERVICE_TOKEN: string;
  // KV namespace for OAuth token/grant storage
  OAUTH_KV: KVNamespace;
  // CORS origin (defaults to MCP Server Portal domain)
  CORS_ALLOWED_ORIGIN?: string;
  // Cloudflare Access team domain for JWT verification (e.g., "myteam.cloudflareaccess.com")
  CF_ACCESS_TEAM_DOMAIN?: string;
  // Cloudflare Access Application AUD (audience) for JWT verification
  CF_ACCESS_AUD?: string;
  // OAuthHelpers injected by OAuthProvider into defaultHandler
  OAUTH_PROVIDER: OAuthHelpers;
}

// Clock skew tolerance for JWT validation (seconds)
const CLOCK_SKEW_TOLERANCE_SECONDS = 60;

// JWKS cache TTL (milliseconds)
const JWKS_CACHE_TTL_MS = 5 * 60 * 1000;

// JWKS cache storage
interface JWKSCache {
  keys: Array<{ kid: string; kty: string; n: string; e: string; alg?: string }>;
  cachedAt: number;
}
const jwksCache: Map<string, JWKSCache> = new Map();

// CORS headers to include in all responses
const CORS_HEADERS_LIST = 'Content-Type, Authorization, Cf-Access-Jwt-Assertion';

/**
 * Get allowed CORS origin from config.
 * Defaults to restricting to Claude's MCP Server Portal domains.
 */
function getCorsOrigin(env: Env, requestOrigin: string | null): string {
  if (env.CORS_ALLOWED_ORIGIN) {
    // Reject wildcard CORS to prevent cross-origin attacks
    if (env.CORS_ALLOWED_ORIGIN === '*') {
      console.warn('SECURITY: CORS_ALLOWED_ORIGIN="*" is insecure, ignoring. Use a specific origin.');
    } else {
      return env.CORS_ALLOWED_ORIGIN;
    }
  }

  const allowedOrigins = [
    'https://mcp.claude.ai',
    'https://claude.ai',
  ];

  if (requestOrigin && allowedOrigins.includes(requestOrigin)) {
    return requestOrigin;
  }

  return 'https://mcp.claude.ai';
}

/**
 * Build CORS headers for responses.
 */
function getCorsHeaders(corsOrigin: string): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': corsOrigin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': CORS_HEADERS_LIST,
  };
}

/**
 * Decode a JWT payload without verification.
 * Used for extracting claims after cryptographic verification.
 */
function decodeJwtPayload(jwt: string): Record<string, unknown> | null {
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
      return null;
    }
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}

/**
 * Safely extract email from a JWT token.
 */
function extractEmailFromJwt(jwt: string): string | null {
  const payload = decodeJwtPayload(jwt);
  if (!payload) return null;
  return typeof payload.email === 'string' ? payload.email : null;
}

/**
 * HMAC-based constant-time string comparison.
 * Uses HMAC-SHA256 to avoid leaking string lengths via timing.
 */
async function timingSafeEqual(a: string, b: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode('mcpbox-comparison-key'),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sigA = new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(a)));
  const sigB = new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(b)));
  let result = 0;
  for (let i = 0; i < sigA.length; i++) {
    result |= sigA[i] ^ sigB[i];
  }
  return result === 0;
}

/**
 * Fetch JWKS from Cloudflare Access with caching.
 */
async function getJWKS(
  teamDomain: string,
  forceRefresh: boolean = false
): Promise<Array<{ kid: string; kty: string; n: string; e: string; alg?: string }> | null> {
  const cacheKey = teamDomain;
  const now = Date.now();

  if (!forceRefresh) {
    const cached = jwksCache.get(cacheKey);
    if (cached && (now - cached.cachedAt) < JWKS_CACHE_TTL_MS) {
      return cached.keys;
    }
  }

  const jwksUrl = `https://${teamDomain}/cdn-cgi/access/certs`;
  try {
    const jwksResponse = await fetch(jwksUrl);
    if (!jwksResponse.ok) {
      console.error(`JWT: Failed to fetch JWKS from ${jwksUrl}: ${jwksResponse.status}`);
      return null;
    }

    const jwks = await jwksResponse.json() as {
      keys: Array<{ kid: string; kty: string; n: string; e: string; alg?: string }>
    };

    jwksCache.set(cacheKey, {
      keys: jwks.keys,
      cachedAt: now,
    });

    return jwks.keys;
  } catch (error) {
    console.error(`JWT: Error fetching JWKS: ${error}`);
    return null;
  }
}

/**
 * Verify a Cloudflare Access JWT using the JWKS endpoint.
 * Returns the decoded payload if valid, null otherwise.
 */
async function verifyAccessJwt(
  jwt: string,
  teamDomain: string,
  expectedAud: string
): Promise<Record<string, unknown> | null> {
  try {
    const parts = jwt.split('.');
    if (parts.length !== 3) {
      console.error('JWT: Invalid format - expected 3 parts');
      return null;
    }

    const [headerB64, payloadB64, signatureB64] = parts;

    const header = JSON.parse(atob(headerB64.replace(/-/g, '+').replace(/_/g, '/')));

    if (header.alg !== 'RS256') {
      console.error(`JWT: Invalid algorithm '${header.alg}', expected RS256`);
      return null;
    }

    if (!header.kid) {
      console.error('JWT: Missing kid in header');
      return null;
    }

    let keys = await getJWKS(teamDomain);
    if (!keys) {
      return null;
    }

    let key = keys.find((k) => k.kid === header.kid);

    if (!key) {
      keys = await getJWKS(teamDomain, true);
      if (!keys) {
        return null;
      }
      key = keys.find((k) => k.kid === header.kid);
    }

    if (!key) {
      console.error(`JWT: Key ${header.kid} not found in JWKS`);
      return null;
    }

    const cryptoKey = await crypto.subtle.importKey(
      'jwk',
      key,
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
      false,
      ['verify']
    );

    const signedContent = new TextEncoder().encode(`${headerB64}.${payloadB64}`);
    const signature = Uint8Array.from(atob(signatureB64.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));

    const valid = await crypto.subtle.verify(
      'RSASSA-PKCS1-v1_5',
      cryptoKey,
      signature,
      signedContent
    );

    if (!valid) {
      console.error('JWT: Signature verification failed');
      return null;
    }

    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

    const now = Math.floor(Date.now() / 1000);
    if (payload.exp && payload.exp < (now - CLOCK_SKEW_TOLERANCE_SECONDS)) {
      console.error('JWT: Token expired');
      return null;
    }

    if (payload.nbf && payload.nbf > (now + CLOCK_SKEW_TOLERANCE_SECONDS)) {
      console.error('JWT: Token not yet valid');
      return null;
    }

    if (payload.iat && payload.iat > (now + CLOCK_SKEW_TOLERANCE_SECONDS)) {
      console.error('JWT: Token issued in the future');
      return null;
    }

    const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
    if (!aud.includes(expectedAud)) {
      console.error(`JWT: Audience mismatch - expected ${expectedAud}, got ${payload.aud}`);
      return null;
    }

    const expectedIssuer = `https://${teamDomain}`;
    if (payload.iss !== expectedIssuer) {
      console.error(`JWT: Issuer mismatch - expected ${expectedIssuer}, got ${payload.iss}`);
      return null;
    }

    if (!payload.sub || typeof payload.sub !== 'string') {
      console.error('JWT: Missing or invalid sub claim');
      return null;
    }

    return payload;
  } catch (error) {
    console.error('JWT verification error:', error);
    return null;
  }
}

// Allowed redirect URI patterns for OAuth client registration
const ALLOWED_REDIRECT_PATTERNS = [
  /^https:\/\/mcp\.claude\.ai\//,
  /^https:\/\/claude\.ai\//,
  /^http:\/\/localhost(:\d+)?\//,
  /^http:\/\/127\.0\.0\.1(:\d+)?\//,
];

/**
 * Validate that a redirect URI matches an allowed pattern.
 */
function isRedirectUriAllowed(redirectUri: string): boolean {
  return ALLOWED_REDIRECT_PATTERNS.some(pattern => pattern.test(redirectUri));
}

// =============================================================================
// API Handler (OAuth-protected MCP endpoint at /)
// =============================================================================
// Only receives requests with valid OAuth tokens (validated by OAuthProvider).
// Additionally checks for Cf-Access-Jwt-Assertion for user identity.
// Proxies all requests to the MCPbox MCP Gateway at /mcp.

const apiHandler = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext & { props: Props }): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    console.log(`apiHandler: ${request.method} ${path} (OAuth validated, props: ${JSON.stringify(ctx.props)})`);
    const requestOrigin = request.headers.get('Origin');
    const corsOrigin = getCorsOrigin(env, requestOrigin);
    const corsHeaders = getCorsHeaders(corsOrigin);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...corsHeaders, 'Access-Control-Max-Age': '86400' },
      });
    }

    // Validate required configuration
    if (!env.MCPBOX_TUNNEL) {
      console.error('MCPBOX_TUNNEL VPC binding not configured.');
      return new Response(JSON.stringify({ error: 'Service temporarily unavailable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    if (!env.MCPBOX_SERVICE_TOKEN) {
      console.error('MCPBOX_SERVICE_TOKEN secret not set.');
      return new Response(JSON.stringify({ error: 'Service temporarily unavailable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Path validation — only the MCP endpoint (/) is allowed through apiHandler.
    // All other paths (health, PRM, etc.) are handled before OAuthProvider.
    if (path !== '/') {
      return new Response(JSON.stringify({ error: 'Not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // OAuth token is already validated by OAuthProvider.
    // Now check for Access JWT for user identification.
    let userEmail: string | null = null;
    let authMethod = 'oauth';  // default: OAuth-only (Cloudflare sync)

    const cfJwt = request.headers.get('Cf-Access-Jwt-Assertion');
    if (cfJwt && env.CF_ACCESS_TEAM_DOMAIN && env.CF_ACCESS_AUD) {
      const jwtPayload = await verifyAccessJwt(cfJwt, env.CF_ACCESS_TEAM_DOMAIN, env.CF_ACCESS_AUD);
      if (jwtPayload) {
        userEmail = typeof jwtPayload.email === 'string' ? jwtPayload.email : null;
        authMethod = 'jwt';
      }
    }

    // Build headers for MCPbox Gateway
    const headers = new Headers(request.headers);
    headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
    headers.set('X-Forwarded-Host', url.host);
    headers.set('X-Forwarded-Proto', 'https');

    // SECURITY: Strip client-supplied headers, set from verified auth results only
    headers.delete('X-MCPbox-User-Email');
    if (userEmail) {
      headers.set('X-MCPbox-User-Email', userEmail);
    }
    headers.delete('X-MCPbox-Auth-Method');
    headers.set('X-MCPbox-Auth-Method', authMethod);

    // Proxy to MCPbox MCP Gateway — the backend always serves MCP at /mcp
    try {
      const targetUrl = `http://mcp-gateway:8002/mcp${url.search}`;
      const response = await env.MCPBOX_TUNNEL.fetch(targetUrl, {
        method: request.method,
        headers,
        body: request.body,
      });

      const responseHeaders = new Headers(response.headers);
      Object.entries(corsHeaders).forEach(([k, v]) => responseHeaders.set(k, v));

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (error) {
      console.error('Proxy error:', error);
      return new Response(JSON.stringify({ error: 'Failed to connect to backend service' }), {
        status: 502,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }
  },
};

// =============================================================================
// Default Handler (OAuth flow endpoints)
// =============================================================================
// Handles /authorize. OAuthProvider auto-handles
// /.well-known/oauth-authorization-server, /token, /register.
// Health and PRM endpoints are handled before OAuthProvider in the outer handler.

const defaultHandler = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const corsOrigin = getCorsOrigin(env, request.headers.get('Origin'));
    const corsHeaders = getCorsHeaders(corsOrigin);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...corsHeaders, 'Access-Control-Max-Age': '86400' },
      });
    }

    // OAuth authorize endpoint
    if (url.pathname === '/authorize') {
      console.log(`OAuth authorize request: ${request.method} ${url.pathname}${url.search}`);
      try {
        // Use verified email as OAuth userId when JWT is present (for per-user
        // token tracking). Cloudflare's internal sync (Portal "Authenticate
        // server", MCP server sync) does NOT include Cf-Access-Jwt-Assertion,
        // so we cannot require it here. Security enforcement happens at the
        // gateway: initialize, tools/list, and tools/call all require JWT for
        // requests from the Worker (defense-in-depth in mcp_gateway.py).
        let userId = 'mcpbox-user';

        if (env.CF_ACCESS_TEAM_DOMAIN && env.CF_ACCESS_AUD) {
          const cfJwt = request.headers.get('Cf-Access-Jwt-Assertion');
          if (cfJwt) {
            const jwtPayload = await verifyAccessJwt(cfJwt, env.CF_ACCESS_TEAM_DOMAIN, env.CF_ACCESS_AUD);
            if (jwtPayload) {
              userId = typeof jwtPayload.email === 'string' ? jwtPayload.email : 'mcpbox-user';
              console.log(`OAuth authorize: JWT verified for ${userId}`);
            }
          }
        }

        // Auto-register unknown clients. Clients may have been registered in a
        // previous KV namespace (e.g., after KV rotation). Validate redirect_uri
        // against allowed patterns to prevent open-redirect attacks.
        const clientId = url.searchParams.get('client_id');
        const redirectUri = url.searchParams.get('redirect_uri');
        if (clientId && redirectUri) {
          if (!isRedirectUriAllowed(redirectUri)) {
            console.error(`OAuth authorize: rejected redirect_uri: ${redirectUri}`);
            return new Response(JSON.stringify({ error: 'Invalid redirect_uri' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }

          const existingRaw = await env.OAUTH_KV.get(`client:${clientId}`);
          const existing = existingRaw ? JSON.parse(existingRaw) : null;
          if (!existing || !existing.redirectUris?.includes(redirectUri)) {
            const clientData = {
              clientId,
              redirectUris: existing?.redirectUris?.includes(redirectUri)
                ? existing.redirectUris
                : [...(existing?.redirectUris || []), redirectUri],
              grantTypes: ['authorization_code', 'refresh_token'],
              responseTypes: ['code'],
              tokenEndpointAuthMethod: 'none',
              registrationDate: existing?.registrationDate || Math.floor(Date.now() / 1000),
            };
            await env.OAUTH_KV.put(`client:${clientId}`, JSON.stringify(clientData));
            console.warn(`SECURITY: Auto-registered/updated client: ${clientId} with redirect_uri: ${redirectUri}`);
          }
        }

        const oauthReqInfo = await env.OAUTH_PROVIDER.parseAuthRequest(request);
        if (!oauthReqInfo.clientId) {
          return new Response(JSON.stringify({ error: 'Invalid OAuth request: missing client_id' }), {
            status: 400,
            headers: { 'Content-Type': 'application/json', ...corsHeaders },
          });
        }

        const { redirectTo } = await env.OAUTH_PROVIDER.completeAuthorization({
          request: oauthReqInfo,
          userId,
          metadata: { label: 'MCPbox' },
          scope: oauthReqInfo.scope,
          props: { authMethod: 'oauth' } as Props,
        });

        return Response.redirect(redirectTo, 302);
      } catch (error) {
        console.error('OAuth authorize error:', error);
        return new Response(JSON.stringify({
          error: 'Authorization failed',
          details: error instanceof Error ? error.message : String(error),
        }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      }
    }

    console.log(`defaultHandler: unhandled path ${url.pathname}`);
    return new Response('Not found', {
      status: 404,
      headers: corsHeaders,
    });
  },
};

// =============================================================================
// Export OAuth-wrapped Worker
// =============================================================================
// apiRoute: '/' — OAuthProvider protects the root path (MCP endpoint).
// This eliminates the audience mismatch that previously required the Bug #108
// workaround. With the MCP server hostname at the Worker's origin (no /mcp
// subpath), OAuthProvider's origin-based audience computation matches naturally.

const oauthProvider = new OAuthProvider({
  apiRoute: '/',
  apiHandler: apiHandler,
  defaultHandler: defaultHandler,
  authorizeEndpoint: '/authorize',
  tokenEndpoint: '/token',
  clientRegistrationEndpoint: '/register',
});

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    console.log(`Worker request: ${request.method} ${url.pathname}${url.search} [${request.headers.get('User-Agent') || 'no-ua'}]`);

    const corsOrigin = getCorsOrigin(env, request.headers.get('Origin'));
    const corsHeaders = getCorsHeaders(corsOrigin);

    // =================================================================
    // Pre-OAuth endpoints — must be accessible without OAuth tokens.
    // These are handled before OAuthProvider because apiRoute: '/'
    // would otherwise route them through OAuth validation.
    // =================================================================

    // CORS preflight for any path
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...corsHeaders, 'Access-Control-Max-Age': '86400' },
      });
    }

    // Health check (public, no OAuth needed)
    if (url.pathname === '/health' || url.pathname.startsWith('/health/')) {
      console.log('Health check request');
      return new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Protected Resource Metadata (RFC 9728) — required for MCP authorization.
    // Cloudflare's MCP sync probes this to discover OAuth requirements.
    if (url.pathname === '/.well-known/oauth-protected-resource') {
      const prmResponse = {
        resource: url.origin,
        authorization_servers: [url.origin],
        bearer_methods_supported: ['header'],
        scopes_supported: [],
      };
      console.log(`PRM request: ${url.pathname} -> ${JSON.stringify(prmResponse)}`);
      return new Response(JSON.stringify(prmResponse), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // =================================================================
    // Service token bypass: Cloudflare sync may send the service token
    // as a Bearer token. This bypasses OAuthProvider and proxies
    // directly to the gateway with auth_method "bearer" (sync-only,
    // no tool execution allowed at gateway level).
    // =================================================================
    if (url.pathname === '/') {
      const authHeader = request.headers.get('Authorization');
      if (authHeader && env.MCPBOX_SERVICE_TOKEN) {
        const token = authHeader.startsWith('Bearer ')
          ? authHeader.slice(7)
          : null;
        if (token && await timingSafeEqual(token, env.MCPBOX_SERVICE_TOKEN)) {
          console.log(`Service token auth for ${url.pathname} (Cloudflare sync)`);

          if (!env.MCPBOX_TUNNEL) {
            return new Response(JSON.stringify({ error: 'Service temporarily unavailable' }), {
              status: 503,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }

          // Build headers for MCPbox Gateway (sync path)
          const headers = new Headers(request.headers);
          headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
          headers.set('X-Forwarded-Host', url.host);
          headers.set('X-Forwarded-Proto', 'https');
          headers.delete('X-MCPbox-User-Email');
          headers.delete('X-MCPbox-Auth-Method');
          headers.set('X-MCPbox-Auth-Method', 'bearer');

          try {
            const targetUrl = `http://mcp-gateway:8002/mcp${url.search}`;
            const response = await env.MCPBOX_TUNNEL.fetch(targetUrl, {
              method: request.method,
              headers,
              body: request.body,
            });
            const responseHeaders = new Headers(response.headers);
            Object.entries(corsHeaders).forEach(([k, v]) => responseHeaders.set(k, v));
            console.log(`Worker response: ${response.status} for ${url.pathname} (service token)`);
            return new Response(response.body, {
              status: response.status,
              statusText: response.statusText,
              headers: responseHeaders,
            });
          } catch (error) {
            console.error('Proxy error (service token path):', error);
            return new Response(JSON.stringify({ error: 'Failed to connect to backend service' }), {
              status: 502,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }
        }
      }
    }

    // =================================================================
    // Auto-register unknown clients at /token (handles KV rotation).
    // OAuthProvider handles /token as a built-in, but it requires the
    // client to be registered. This ensures clients that were registered
    // in a previous KV namespace are re-registered before token exchange.
    // =================================================================
    if (url.pathname === '/token' && request.method === 'POST') {
      const contentType = request.headers.get('content-type') || '';
      if (contentType.includes('application/x-www-form-urlencoded')) {
        const body = await request.text();
        const params = new URLSearchParams(body);
        const tokenClientId = params.get('client_id');
        if (tokenClientId) {
          const existing = await env.OAUTH_KV.get(`client:${tokenClientId}`);
          if (!existing) {
            const clientData = {
              clientId: tokenClientId,
              redirectUris: [],
              grantTypes: ['authorization_code', 'refresh_token'],
              responseTypes: ['code'],
              tokenEndpointAuthMethod: 'none',
              registrationDate: Math.floor(Date.now() / 1000),
            };
            await env.OAUTH_KV.put(`client:${tokenClientId}`, JSON.stringify(clientData));
            console.warn(`SECURITY: Auto-registered unknown client at /token: ${tokenClientId} (possible KV rotation)`);
          }
        }
        // Reconstruct request since we consumed the body with text()
        request = new Request(request.url, {
          method: request.method,
          headers: request.headers,
          body: params.toString(),
        });
      }
    }

    // =================================================================
    // OAuthProvider handles everything else:
    // - /.well-known/oauth-authorization-server (built-in)
    // - /token (built-in)
    // - /register (built-in)
    // - /authorize (via defaultHandler)
    // - / (via apiHandler, requires valid OAuth token)
    // =================================================================
    const response = await oauthProvider.fetch(request, env, ctx);
    console.log(`Worker response: ${response.status} for ${url.pathname}`);

    // Add resource_metadata to 401 responses for MCP endpoint (RFC 9728).
    // This tells MCP clients where to find the OAuth authorization server.
    if (response.status === 401 && url.pathname === '/') {
      const newHeaders = new Headers(response.headers);
      const prmUrl = `${url.origin}/.well-known/oauth-protected-resource`;
      const existing = newHeaders.get('WWW-Authenticate') || '';
      if (existing) {
        newHeaders.set('WWW-Authenticate',
          `${existing}, resource_metadata="${prmUrl}"`
        );
      } else {
        newHeaders.set('WWW-Authenticate',
          `Bearer resource_metadata="${prmUrl}"`
        );
      }
      console.log(`401 for / -- WWW-Authenticate: ${newHeaders.get('WWW-Authenticate')}`);
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: newHeaders,
      });
    }

    return response;
  },
};
