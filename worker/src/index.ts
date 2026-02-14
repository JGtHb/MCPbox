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
const CORS_HEADERS_LIST = 'Content-Type, Authorization';

/**
 * Get allowed CORS origin from config.
 * Defaults to restricting to Claude's MCP Server Portal domains.
 */
function getCorsOrigin(env: Env, requestOrigin: string | null): string {
  if (env.CORS_ALLOWED_ORIGIN) {
    if (env.CORS_ALLOWED_ORIGIN === '*') {
      console.warn('SECURITY: CORS_ALLOWED_ORIGIN="*" is insecure, ignoring.');
    } else {
      return env.CORS_ALLOWED_ORIGIN;
    }
  }

  const allowedOrigins = [
    'https://mcp.claude.ai',
    'https://claude.ai',
    'https://one.dash.cloudflare.com',
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
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': CORS_HEADERS_LIST,
  };
}

// Static allowed redirect URI patterns for OAuth client registration
const ALLOWED_REDIRECT_PATTERNS = [
  /^https:\/\/mcp\.claude\.ai\//,
  /^https:\/\/claude\.ai\//,
  /^https:\/\/one\.dash\.cloudflare\.com\//,
  /^http:\/\/localhost(:\d+)?\//,
  /^http:\/\/127\.0\.0\.1(:\d+)?\//,
];

/**
 * Validate that a redirect URI matches an allowed pattern.
 */
function isRedirectUriAllowed(redirectUri: string): boolean {
  return ALLOWED_REDIRECT_PATTERNS.some(pattern => pattern.test(redirectUri));
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
    headers.set('X-MCPbox-Service-Token', env.MCPBOX_SERVICE_TOKEN);
    headers.set('X-Forwarded-Host', url.host);
    headers.set('X-Forwarded-Proto', 'https');

    // SECURITY: Strip client-supplied headers, set from verified auth results only
    headers.delete('X-MCPbox-User-Email');
    if (userEmail) {
      headers.set('X-MCPbox-User-Email', userEmail);
    }
    headers.delete('X-MCPbox-Auth-Method');
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
    const corsOrigin = getCorsOrigin(env, request.headers.get('Origin'));
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
    console.log(`Worker request: ${request.method} ${url.pathname}${url.search} [${request.headers.get('User-Agent') || 'no-ua'}]`);

    const corsOrigin = getCorsOrigin(env, request.headers.get('Origin'));
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

    // Health check (public, no OAuth needed)
    if (url.pathname === '/health' || url.pathname.startsWith('/health/')) {
      console.log('Health check request');
      return new Response(JSON.stringify({ status: 'ok' }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Protected Resource Metadata (RFC 9728)
    if (url.pathname === '/.well-known/oauth-protected-resource' ||
        url.pathname === '/.well-known/oauth-protected-resource/mcp') {
      const isMcpPath = url.pathname.endsWith('/mcp');
      const resource = isMcpPath ? `${url.origin}/mcp` : url.origin;
      const prmResponse = {
        resource,
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
          if (tokenRedirectUri && !isRedirectUriAllowed(tokenRedirectUri)) {
            console.error(`SECURITY: Rejected /token auto-registration with invalid redirect_uri: ${tokenRedirectUri}`);
            return new Response(JSON.stringify({ error: 'invalid_redirect_uri' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }
          const existing = await env.OAUTH_KV.get(`client:${tokenClientId}`);
          if (!existing) {
            const clientData = {
              clientId: tokenClientId,
              redirectUris: tokenRedirectUri ? [tokenRedirectUri] : [],
              grantTypes: ['authorization_code', 'refresh_token'],
              responseTypes: ['code'],
              tokenEndpointAuthMethod: 'none',
              registrationDate: Math.floor(Date.now() / 1000),
            };
            await env.OAUTH_KV.put(`client:${tokenClientId}`, JSON.stringify(clientData));
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
    // Validate redirect URIs in /register requests
    // =================================================================
    if (url.pathname === '/register' && request.method === 'POST') {
      try {
        const registerBody = await request.text();
        const registerData = JSON.parse(registerBody);
        const redirectUris: string[] = registerData.redirect_uris || [];
        for (const uri of redirectUris) {
          if (!isRedirectUriAllowed(uri)) {
            console.error(`SECURITY: Rejected /register with invalid redirect_uri: ${uri}`);
            return new Response(JSON.stringify({ error: 'invalid_redirect_uri' }), {
              status: 400,
              headers: { 'Content-Type': 'application/json', ...corsHeaders },
            });
          }
        }
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

    // Add resource_metadata to 401 responses for MCP endpoint (RFC 9728)
    if (response.status === 401 && (originalPathname === '/' || originalPathname === '/mcp')) {
      const newHeaders = new Headers(response.headers);
      const prmSuffix = originalPathname === '/mcp' ? '/mcp' : '';
      const prmUrl = `${url.origin}/.well-known/oauth-protected-resource${prmSuffix}`;
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
