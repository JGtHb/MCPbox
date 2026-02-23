/**
 * MCPbox MCP Proxy Worker
 *
 * This Cloudflare Worker acts as an OAuth 2.1 protected proxy between
 * MCP clients and your local MCPbox instance. It uses Workers VPC to
 * access your tunnel privately (no public hostname needed).
 *
 * Authentication architecture (Access for SaaS):
 * 1. OAuth 2.1 (Client -> Worker): Managed by @cloudflare/workers-oauth-provider.
 *    All MCP requests require a valid OAuth token.
 * 2. OIDC (Worker -> Cloudflare Access): Worker authenticates users via
 *    Cloudflare Access for SaaS (OIDC). User identity (email, name) is
 *    verified at authorization time and stored in encrypted OAuth token props.
 * 3. Service token (Worker -> MCPbox): Defense-in-depth, unchanged.
 *
 * Key difference from self-hosted Access:
 * - Access does NOT intercept HTTP requests to the Worker
 * - OAuth endpoints (/authorize, /token, /register) are publicly accessible
 * - No path-based exemptions needed (eliminates "Bug #1")
 * - All users authenticate via OIDC (consistent identity model)
 * - No Cf-Access-Jwt-Assertion headers (identity comes from OIDC id_token)
 *
 * Security:
 * - The tunnel has NO public hostname - only accessible via Workers VPC
 * - MCPbox validates the service token as defense in depth
 * - User email is verified by OIDC id_token at authorization time
 * - Unauthenticated requests are rejected by OAuthProvider (401)
 */

import OAuthProvider, { type OAuthHelpers } from '@cloudflare/workers-oauth-provider';
import { handleAccessRequest } from './access-handler';

// Workers VPC Service binding type
interface VpcService {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

// Props stored in OAuth token (encrypted, set during authorization)
export interface Props {
  email?: string;     // User email verified by OIDC id_token at authorization time
  authMethod: string; // "oidc" — always OIDC with Access for SaaS
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

  // === Cloudflare Access for SaaS (OIDC upstream) ===
  // These are obtained from the SaaS OIDC application in Cloudflare Access
  ACCESS_CLIENT_ID: string;
  ACCESS_CLIENT_SECRET: string;
  ACCESS_TOKEN_URL: string;           // e.g., https://<team>.cloudflareaccess.com/cdn-cgi/access/sso/oidc/<client-id>/token
  ACCESS_AUTHORIZATION_URL: string;   // e.g., https://<team>.cloudflareaccess.com/cdn-cgi/access/sso/oidc/<client-id>/authorize
  ACCESS_JWKS_URL: string;            // e.g., https://<team>.cloudflareaccess.com/cdn-cgi/access/certs
  COOKIE_ENCRYPTION_KEY: string;      // 32-byte hex key for encrypting approval cookies

  // OAuthHelpers injected by OAuthProvider into defaultHandler
  OAUTH_PROVIDER: OAuthHelpers;
}

// CORS headers to include in all responses
const CORS_HEADERS_LIST = 'Content-Type, Authorization, Mcp-Session-Id';

// =============================================================================
// Built-in defaults (always included, cannot be removed by admin)
// =============================================================================

const BUILTIN_CORS_ORIGINS = [
  'https://mcp.claude.ai',
  'https://claude.ai',
  'https://chatgpt.com',
  'https://chat.openai.com',
  'https://platform.openai.com',
  'https://one.dash.cloudflare.com',
];

const BUILTIN_REDIRECT_PATTERNS = [
  /^https:\/\/mcp\.claude\.ai\//,
  /^https:\/\/claude\.ai\//,
  /^https:\/\/chatgpt\.com\//,
  /^https:\/\/chat\.openai\.com\//,
  /^https:\/\/platform\.openai\.com\//,
  /^https:\/\/one\.dash\.cloudflare\.com\//,
  /^http:\/\/localhost(:\d+)?\//,
  /^http:\/\/127\.0\.0\.1(:\d+)?\//,
];

// =============================================================================
// KV-backed admin config cache (per-isolate, 60s TTL)
// =============================================================================

export interface AdminConfig {
  corsOrigins: string[];
  redirectUris: string[];
  cachedAt: number;
}

let adminConfigCache: AdminConfig | null = null;
const ADMIN_CONFIG_TTL_MS = 60_000;

/** Reset admin config cache (for testing only). */
export function resetAdminConfigCache(): void {
  adminConfigCache = null;
}

/**
 * Load admin-configured origins from KV (with caching).
 * Returns empty arrays if KV is unavailable or not configured.
 */
export async function getAdminConfig(env: Env): Promise<AdminConfig> {
  const now = Date.now();
  if (adminConfigCache && (now - adminConfigCache.cachedAt) < ADMIN_CONFIG_TTL_MS) {
    return adminConfigCache;
  }

  let corsOrigins: string[] = [];
  let redirectUris: string[] = [];

  if (env.OAUTH_KV) {
    try {
      const [corsRaw, redirectRaw] = await Promise.all([
        env.OAUTH_KV.get('config:cors_origins'),
        env.OAUTH_KV.get('config:redirect_uris'),
      ]);
      if (corsRaw) {
        const parsed = JSON.parse(corsRaw);
        if (Array.isArray(parsed)) corsOrigins = parsed.filter((s: unknown) => typeof s === 'string');
      }
      if (redirectRaw) {
        const parsed = JSON.parse(redirectRaw);
        if (Array.isArray(parsed)) redirectUris = parsed.filter((s: unknown) => typeof s === 'string');
      }
    } catch (e) {
      console.warn('Failed to read admin config from KV:', e);
    }
  }

  adminConfigCache = { corsOrigins, redirectUris, cachedAt: now };
  return adminConfigCache;
}

/**
 * Get allowed CORS origin for a request.
 *
 * Checks built-in origins + admin-configured origins from KV.
 * Falls back to 'https://mcp.claude.ai' if no match.
 */
async function getCorsOrigin(env: Env, requestOrigin: string | null): Promise<string> {
  // Legacy single-origin override (still supported, but prefer KV config)
  if (env.CORS_ALLOWED_ORIGIN) {
    if (env.CORS_ALLOWED_ORIGIN === '*') {
      console.warn('SECURITY: CORS_ALLOWED_ORIGIN="*" is insecure, ignoring.');
    } else {
      return env.CORS_ALLOWED_ORIGIN;
    }
  }

  if (!requestOrigin) {
    return 'https://mcp.claude.ai';
  }

  // Check built-in origins first (fast, no KV read)
  if (BUILTIN_CORS_ORIGINS.includes(requestOrigin)) {
    return requestOrigin;
  }

  // Check admin-configured origins from KV
  const adminConfig = await getAdminConfig(env);
  if (adminConfig.corsOrigins.includes(requestOrigin)) {
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
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': CORS_HEADERS_LIST,
    'Access-Control-Expose-Headers': 'Mcp-Session-Id',
  };
}

/**
 * Validate that a redirect URI matches allowed patterns.
 *
 * Checks built-in patterns + admin-configured URI prefixes from KV.
 */
async function isRedirectUriAllowed(redirectUri: string, env: Env): Promise<boolean> {
  // Check built-in patterns first (fast, no KV read)
  if (BUILTIN_REDIRECT_PATTERNS.some(pattern => pattern.test(redirectUri))) {
    return true;
  }

  // Check admin-configured redirect URI prefixes
  const adminConfig = await getAdminConfig(env);
  for (const prefix of adminConfig.redirectUris) {
    if (redirectUri.startsWith(prefix)) {
      return true;
    }
  }

  return false;
}

// Internal path used for URL rewriting. MCP requests to '/' are rewritten to
// this path before being passed to OAuthProvider, so that apiRoute matching
// doesn't accidentally catch OAuth flow endpoints like /authorize.
const INTERNAL_API_ROUTE = '/oauth-protected-api';

// =============================================================================
// API Handler (OAuth-protected MCP endpoint)
// =============================================================================
// Only receives requests with valid OAuth tokens (validated by OAuthProvider).
// User identity comes from OAuth token props (verified via OIDC at authorization time).
// Proxies all requests to the MCPbox MCP Gateway at /mcp.

const apiHandler = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext & { props: Props }): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    console.log(`apiHandler: ${request.method} ${path} (OAuth validated, has_email: ${!!ctx.props?.email})`);
    const requestOrigin = request.headers.get('Origin');
    const corsOrigin = await getCorsOrigin(env, requestOrigin);
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

    // Path validation — only the rewritten MCP endpoint is allowed
    if (path !== INTERNAL_API_ROUTE) {
      return new Response(JSON.stringify({ error: 'Not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // User identity comes from OIDC-verified OAuth token props
    const userEmail = ctx.props?.email || null;

    // Build headers for MCPbox Gateway
    const headers = new Headers(request.headers);

    // SECURITY: Strip ALL client-supplied X-MCPbox-* headers before setting
    // trusted values. This prevents injection of any current or future trusted
    // headers that the gateway might read.
    const headersToDelete: string[] = [];
    for (const [name] of headers) {
      if (name.toLowerCase().startsWith('x-mcpbox-')) {
        headersToDelete.push(name);
      }
    }
    for (const name of headersToDelete) {
      headers.delete(name);
    }

    // Set trusted headers from verified auth results only
    headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
    headers.set('X-Forwarded-Host', url.host);
    headers.set('X-Forwarded-Proto', 'https');
    if (userEmail) {
      headers.set('X-MCPbox-User-Email', userEmail);
    }
    headers.set('X-MCPbox-Auth-Method', 'oidc');

    // Proxy to MCPbox MCP Gateway
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
// Default Handler (OAuth flow + OIDC upstream)
// =============================================================================
// Handles /authorize, /callback. OAuthProvider auto-handles
// /.well-known/oauth-authorization-server, /token, /register.

const defaultHandler = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const corsOrigin = await getCorsOrigin(env, request.headers.get('Origin'));
    const corsHeaders = getCorsHeaders(corsOrigin);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...corsHeaders, 'Access-Control-Max-Age': '86400' },
      });
    }

    // Delegate /authorize (GET/POST) and /callback to the Access handler
    if (url.pathname === '/authorize' || url.pathname === '/callback') {
      return handleAccessRequest(request, env as Env & { OAUTH_PROVIDER: OAuthHelpers }, ctx);
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

const oauthProvider = new OAuthProvider({
  apiRoute: INTERNAL_API_ROUTE,
  apiHandler: apiHandler,
  defaultHandler: defaultHandler,
  authorizeEndpoint: '/authorize',
  tokenEndpoint: '/token',
  clientRegistrationEndpoint: '/register',
});

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const originalPathname = url.pathname;
    console.log(`Worker request: ${request.method} ${url.pathname} [${request.headers.get('User-Agent') || 'no-ua'}]`);

    const corsOrigin = await getCorsOrigin(env, request.headers.get('Origin'));
    const corsHeaders = getCorsHeaders(corsOrigin);

    // =================================================================
    // Pre-OAuth endpoints — handled before OAuthProvider.
    // =================================================================

    // CORS preflight for any path
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { ...corsHeaders, 'Access-Control-Max-Age': '86400' },
      });
    }

    // Reject PKCE plain method — only S256 is allowed
    if (url.pathname === '/authorize' && url.searchParams.get('code_challenge_method') === 'plain') {
      console.warn('SECURITY: Rejected /authorize with PKCE plain method');
      return new Response(JSON.stringify({
        error: 'invalid_request',
        error_description: 'Only S256 PKCE challenge method is supported',
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Health check (public, no OAuth needed)
    if (url.pathname === '/health' || url.pathname.startsWith('/health/')) {
      console.log('Health check request');
      return new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Protected Resource Metadata (RFC 9728)
    // IMPORTANT: resource MUST be origin-only (no path) to avoid audience mismatch
    // with OAuthProvider, which computes resourceServer as origin-only.
    // See: https://github.com/cloudflare/workers-oauth-provider/issues/108
    if (url.pathname === '/.well-known/oauth-protected-resource' ||
        url.pathname === '/.well-known/oauth-protected-resource/mcp') {
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
    // Auto-register unknown clients at /token (handles KV rotation)
    // =================================================================
    if (url.pathname === '/token' && request.method === 'POST') {
      const contentType = request.headers.get('content-type') || '';
      if (contentType.includes('application/x-www-form-urlencoded')) {
        const body = await request.text();
        const params = new URLSearchParams(body);
        const tokenClientId = params.get('client_id');
        const tokenRedirectUri = params.get('redirect_uri');
        if (tokenClientId) {
          if (tokenRedirectUri && !(await isRedirectUriAllowed(tokenRedirectUri, env))) {
            console.error(`SECURITY: Rejected /token auto-registration with invalid redirect_uri: ${tokenRedirectUri}`);
            return new Response(JSON.stringify({ error: 'invalid_redirect_uri' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }
          const existing = await env.OAUTH_KV.get(`client:${tokenClientId}`);
          if (!existing) {
            // Rate limit auto-registration at /token (same limit as /register)
            const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';
            const rateLimitKey = `ratelimit:register:${clientIp}`;
            const currentCount = parseInt(await env.OAUTH_KV.get(rateLimitKey) || '0', 10);
            if (currentCount >= 10) {
              console.warn(`SECURITY: Rate-limited /token auto-registration from ${clientIp}`);
              return new Response(JSON.stringify({ error: 'too_many_requests' }), {
                status: 429,
                headers: { 'Content-Type': 'application/json', 'Retry-After': '3600', ...corsHeaders },
              });
            }
            const clientData = {
              clientId: tokenClientId,
              redirectUris: tokenRedirectUri ? [tokenRedirectUri] : [],
              grantTypes: ['authorization_code', 'refresh_token'],
              responseTypes: ['code'],
              tokenEndpointAuthMethod: 'none',
              registrationDate: Math.floor(Date.now() / 1000),
            };
            await env.OAUTH_KV.put(`client:${tokenClientId}`, JSON.stringify(clientData));
            // Share the rate limit counter with /register (same key prefix)
            await env.OAUTH_KV.put(rateLimitKey, String(currentCount + 1), { expirationTtl: 3600 });
            console.warn(`SECURITY: Auto-registered unknown client at /token: ${tokenClientId}`);
          }
        }
        request = new Request(request.url, {
          method: request.method,
          headers: request.headers,
          body: params.toString(),
        });
      }
    }

    // =================================================================
    // Validate and rate-limit /register requests
    // =================================================================
    if (url.pathname === '/register' && request.method === 'POST') {
      // Rate limit: max 10 registrations per IP per hour
      const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';
      const rateLimitKey = `ratelimit:register:${clientIp}`;
      const currentCount = parseInt(await env.OAUTH_KV.get(rateLimitKey) || '0', 10);
      if (currentCount >= 10) {
        console.warn(`SECURITY: Rate-limited /register from ${clientIp} (${currentCount} attempts)`);
        return new Response(JSON.stringify({ error: 'too_many_requests' }), {
          status: 429,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '3600', ...corsHeaders },
        });
      }

      try {
        const registerBody = await request.text();
        const registerData = JSON.parse(registerBody);
        const redirectUris: string[] = registerData.redirect_uris || [];
        for (const uri of redirectUris) {
          if (!(await isRedirectUriAllowed(uri, env))) {
            console.error(`SECURITY: Rejected /register with invalid redirect_uri: ${uri}`);
            return new Response(JSON.stringify({ error: 'invalid_redirect_uri' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }
        }

        // Increment rate limit counter (1 hour TTL)
        await env.OAUTH_KV.put(rateLimitKey, String(currentCount + 1), { expirationTtl: 3600 });

        request = new Request(request.url, {
          method: request.method,
          headers: request.headers,
          body: registerBody,
        });
      } catch (error) {
        console.warn('/register body parse error, deferring to OAuthProvider:', error);
      }
    }

    // =================================================================
    // URL rewriting for MCP endpoint
    // =================================================================
    if (url.pathname === '/' || url.pathname === '/mcp') {
      const rewrittenUrl = new URL(request.url);
      rewrittenUrl.pathname = INTERNAL_API_ROUTE;
      request = new Request(rewrittenUrl.toString(), request);
      console.log(`Rewrote ${originalPathname} -> ${INTERNAL_API_ROUTE} for OAuth validation`);
    }

    // =================================================================
    // OAuthProvider handles everything else
    // =================================================================
    const response = await oauthProvider.fetch(request, env, ctx);
    console.log(`Worker response: ${response.status} for ${originalPathname}`);

    // Harden well-known metadata: enforce S256-only PKCE (strip 'plain')
    if (originalPathname === '/.well-known/oauth-authorization-server' && response.ok) {
      try {
        const metadata = await response.json() as Record<string, unknown>;
        metadata.code_challenge_methods_supported = ['S256'];
        return new Response(JSON.stringify(metadata), {
          status: response.status,
          headers: response.headers,
        });
      } catch {
        // If we can't parse, return original
      }
    }

    // Add resource_metadata to 401 responses for MCP endpoint (RFC 9728)
    if (response.status === 401 && (originalPathname === '/' || originalPathname === '/mcp')) {
      const newHeaders = new Headers(response.headers);
      const prmUrl = `${url.origin}/.well-known/oauth-protected-resource`;
      const existing = newHeaders.get('WWW-Authenticate') || '';
      if (existing) {
        newHeaders.set('WWW-Authenticate', `${existing}, resource_metadata="${prmUrl}"`);
      } else {
        newHeaders.set('WWW-Authenticate', `Bearer resource_metadata="${prmUrl}"`);
      }
      console.log(`401 for ${originalPathname} -- WWW-Authenticate: ${newHeaders.get('WWW-Authenticate')}`);
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: newHeaders,
      });
    }

    return response;
  },
};
