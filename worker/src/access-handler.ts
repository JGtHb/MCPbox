/**
 * Cloudflare Access for SaaS - OIDC upstream auth handler.
 *
 * This handler manages the OAuth authorization flow where Cloudflare Access
 * for SaaS acts as the upstream identity provider (OIDC). The Worker redirects
 * users to Access for authentication, then exchanges the authorization code
 * for tokens containing verified user identity (email, name, sub).
 *
 * Flow:
 * 1. GET /authorize → render approval dialog or redirect to Access
 * 2. POST /authorize → validate CSRF, approve client, redirect to Access
 * 3. GET /callback → exchange code for tokens, verify id_token, complete OAuth
 */

import type { OAuthHelpers, AuthRequest } from '@cloudflare/workers-oauth-provider';
import type { Env, Props } from './index';

type EnvWithOAuth = Env & { OAUTH_PROVIDER: OAuthHelpers };

// Encrypted cookie name for approved clients
const APPROVED_CLIENTS_COOKIE = 'mcpbox_approved_clients';

// KV key prefix for OAuth state
const STATE_KEY_PREFIX = 'oauth_state:';

// State TTL in KV (5 minutes)
const STATE_TTL_SECONDS = 300;

/**
 * Handle all OAuth flow requests: /authorize (GET/POST) and /callback (GET).
 */
export async function handleAccessRequest(
  request: Request,
  env: EnvWithOAuth,
  _ctx: ExecutionContext,
): Promise<Response> {
  const url = new URL(request.url);
  const { pathname } = url;

  if (request.method === 'GET' && pathname === '/authorize') {
    return handleAuthorizeGet(request, env);
  }

  if (request.method === 'POST' && pathname === '/authorize') {
    return handleAuthorizePost(request, env);
  }

  if (request.method === 'GET' && pathname === '/callback') {
    return handleCallback(request, env);
  }

  return new Response('Not Found', { status: 404 });
}

// =============================================================================
// GET /authorize — parse OAuth request, auto-approve known clients or show dialog
// =============================================================================

async function handleAuthorizeGet(
  request: Request,
  env: EnvWithOAuth,
): Promise<Response> {
  const oauthReqInfo = await env.OAUTH_PROVIDER.parseAuthRequest(request);
  const { clientId } = oauthReqInfo;
  if (!clientId) {
    return new Response(JSON.stringify({ error: 'Invalid request: missing client_id' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // Auto-approve known clients (Claude, Cloudflare dashboard, localhost)
  const redirectUri = new URL(request.url).searchParams.get('redirect_uri') || '';
  if (isKnownClient(redirectUri)) {
    const { stateToken, nonce } = await createOAuthState(oauthReqInfo, env.OAUTH_KV);
    return redirectToAccess(request, env, stateToken, nonce);
  }

  // Check if client was previously approved via cookie
  if (await isClientApproved(request, clientId, env.COOKIE_ENCRYPTION_KEY)) {
    const { stateToken, nonce } = await createOAuthState(oauthReqInfo, env.OAUTH_KV);
    return redirectToAccess(request, env, stateToken, nonce);
  }

  // Show approval dialog for unknown clients
  const csrfToken = generateCSRFToken();
  const stateB64 = btoa(JSON.stringify({ oauthReqInfo }));

  return new Response(renderApprovalPage(clientId, csrfToken, stateB64), {
    headers: {
      'Content-Type': 'text/html',
      'Set-Cookie': `mcpbox_csrf=${csrfToken}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=300`,
    },
  });
}

// =============================================================================
// POST /authorize — validate CSRF, approve client, redirect to Access
// =============================================================================

async function handleAuthorizePost(
  request: Request,
  env: EnvWithOAuth,
): Promise<Response> {
  const formData = await request.formData();

  // Validate CSRF token
  const csrfFromForm = formData.get('csrf_token');
  const csrfFromCookie = getCookieValue(request, 'mcpbox_csrf');
  if (!csrfFromForm || !csrfFromCookie || csrfFromForm !== csrfFromCookie) {
    return new Response('CSRF validation failed', { status: 403 });
  }

  // Extract OAuth request info from form state
  const encodedState = formData.get('state');
  if (!encodedState || typeof encodedState !== 'string') {
    return new Response('Missing state', { status: 400 });
  }

  let state: { oauthReqInfo?: AuthRequest };
  try {
    state = JSON.parse(atob(encodedState));
  } catch {
    return new Response('Invalid state', { status: 400 });
  }

  if (!state.oauthReqInfo?.clientId) {
    return new Response('Invalid request', { status: 400 });
  }

  // Mark client as approved via encrypted cookie
  const approvedCookie = await addApprovedClient(
    request, state.oauthReqInfo.clientId, env.COOKIE_ENCRYPTION_KEY
  );

  // Create secure state and redirect to Access
  const { stateToken, nonce } = await createOAuthState(state.oauthReqInfo, env.OAUTH_KV);

  return redirectToAccess(request, env, stateToken, nonce, {
    'Set-Cookie': approvedCookie,
  });
}

// =============================================================================
// GET /callback — exchange code for tokens, verify id_token, complete OAuth
// =============================================================================

async function handleCallback(
  request: Request,
  env: EnvWithOAuth,
): Promise<Response> {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  const stateParam = url.searchParams.get('state');

  if (!code || !stateParam) {
    const error = url.searchParams.get('error');
    const errorDesc = url.searchParams.get('error_description');
    console.error(`Callback error: ${error} - ${errorDesc}`);
    return new Response(JSON.stringify({
      error: error || 'missing_params',
      error_description: errorDesc || 'Missing code or state parameter',
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // Validate state and retrieve stored OAuth request info + nonce
  const stateData = await validateOAuthState(stateParam, env.OAUTH_KV);
  if (!stateData) {
    return new Response(JSON.stringify({
      error: 'invalid_state',
      error_description: 'Invalid or expired OAuth state',
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const { oauthReqInfo, nonce } = stateData;

  // Exchange authorization code for tokens from Access
  const tokenResult = await fetchUpstreamTokens(env, code, request.url);
  if (tokenResult.error) {
    // Log detailed error server-side only (never expose to client)
    console.error(`Token exchange failed: ${tokenResult.error}`);
    return new Response(JSON.stringify({
      error: 'token_exchange_failed',
      error_description: 'Failed to exchange authorization code with identity provider',
    }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // Verify the id_token and extract user claims (with nonce validation)
  const verifyResult = await verifyIdToken(env, tokenResult.idToken!, nonce || undefined);
  if (!verifyResult.ok) {
    // Log detailed reason server-side only (never expose to client)
    console.error(`id_token verification failed: ${verifyResult.reason}`);
    return new Response(JSON.stringify({
      error: 'invalid_id_token',
      error_description: 'Failed to verify identity token from Cloudflare Access',
    }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const claims = verifyResult.payload;
  const userEmail = typeof claims.email === 'string' ? claims.email : undefined;
  const userName = typeof claims.name === 'string' ? claims.name : undefined;
  const userSub = typeof claims.sub === 'string' ? claims.sub : 'mcpbox-user';

  console.log(`OIDC callback: verified user ${userEmail} (sub: ${userSub})`);

  // Complete the OAuth authorization — issue a Worker token to the MCP client
  const { redirectTo } = await env.OAUTH_PROVIDER.completeAuthorization({
    request: oauthReqInfo,
    userId: userEmail || userSub,
    metadata: { label: userName || 'MCPbox User' },
    scope: oauthReqInfo.scope,
    props: {
      email: userEmail,
      authMethod: 'oidc',
    } as Props,
  });

  return Response.redirect(redirectTo, 302);
}

// =============================================================================
// Upstream token exchange
// =============================================================================

interface TokenResult {
  accessToken?: string;
  idToken?: string;
  error?: string;
}

async function fetchUpstreamTokens(
  env: Env,
  code: string,
  callbackUrl: string,
): Promise<TokenResult> {
  const redirectUri = new URL('/callback', callbackUrl).href;

  try {
    const resp = await fetch(env.ACCESS_TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: env.ACCESS_CLIENT_ID,
        client_secret: env.ACCESS_CLIENT_SECRET,
        code,
        redirect_uri: redirectUri,
      }).toString(),
    });

    if (!resp.ok) {
      const text = await resp.text();
      return { error: `Token endpoint returned ${resp.status}: ${text}` };
    }

    const data = await resp.json() as {
      access_token?: string;
      id_token?: string;
      error?: string;
      error_description?: string;
    };

    if (data.error) {
      return { error: `${data.error}: ${data.error_description || ''}` };
    }

    if (!data.id_token) {
      return { error: 'No id_token in response' };
    }

    return {
      accessToken: data.access_token,
      idToken: data.id_token,
    };
  } catch (error) {
    return { error: `Token exchange failed: ${error}` };
  }
}

// =============================================================================
// ID token verification using Access JWKS
// =============================================================================

// JWKS cache (module-level, survives across requests within same isolate)
let jwksCache: { keys: Array<JsonWebKey & { kid: string }>; cachedAt: number } | null = null;
const JWKS_CACHE_TTL_MS = 5 * 60 * 1000;

async function fetchAccessPublicKey(
  env: Env,
  kid: string,
): Promise<CryptoKey | null> {
  const now = Date.now();

  // Try cached keys first
  if (jwksCache && (now - jwksCache.cachedAt) < JWKS_CACHE_TTL_MS) {
    const jwk = jwksCache.keys.find(k => k.kid === kid);
    if (jwk) {
      return crypto.subtle.importKey(
        'jwk', jwk,
        { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
        false, ['verify'],
      );
    }
  }

  // Fetch fresh JWKS
  try {
    const resp = await fetch(env.ACCESS_JWKS_URL);
    if (!resp.ok) {
      console.error(`JWKS fetch failed: ${resp.status}`);
      return null;
    }

    const data = await resp.json() as { keys: Array<JsonWebKey & { kid: string }> };
    jwksCache = { keys: data.keys, cachedAt: now };

    const jwk = data.keys.find(k => k.kid === kid);
    if (!jwk) {
      console.error(`Key ${kid} not found in JWKS`);
      return null;
    }

    return crypto.subtle.importKey(
      'jwk', jwk,
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
      false, ['verify'],
    );
  } catch (error) {
    console.error(`JWKS fetch error: ${error}`);
    return null;
  }
}

type VerifyResult =
  | { ok: true; payload: Record<string, unknown> }
  | { ok: false; reason: string };

async function verifyIdToken(
  env: Env,
  token: string,
  expectedNonce?: string,
): Promise<VerifyResult> {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) {
      return { ok: false, reason: 'invalid JWT format (expected 3 parts)' };
    }

    const [headerB64, payloadB64, signatureB64] = parts;
    const header = JSON.parse(atob(headerB64.replace(/-/g, '+').replace(/_/g, '/')));

    // Require RS256 algorithm (prevent algorithm confusion attacks)
    if (header.alg && header.alg !== 'RS256') {
      return { ok: false, reason: `unexpected algorithm ${header.alg}` };
    }

    if (!header.kid) {
      return { ok: false, reason: 'missing kid in JWT header' };
    }

    const key = await fetchAccessPublicKey(env, header.kid);
    if (!key) {
      return { ok: false, reason: `key ${header.kid} not found in JWKS at ${env.ACCESS_JWKS_URL}` };
    }

    const signedContent = new TextEncoder().encode(`${headerB64}.${payloadB64}`);
    const signature = Uint8Array.from(
      atob(signatureB64.replace(/-/g, '+').replace(/_/g, '/')),
      c => c.charCodeAt(0),
    );

    const valid = await crypto.subtle.verify(
      'RSASSA-PKCS1-v1_5', key, signature, signedContent,
    );

    if (!valid) {
      return { ok: false, reason: 'signature verification failed' };
    }

    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

    const now = Math.floor(Date.now() / 1000);

    // Validate expiration (60s clock skew tolerance)
    if (payload.exp && payload.exp < (now - 60)) {
      return { ok: false, reason: `token expired (exp=${payload.exp}, now=${now})` };
    }

    // Validate not-before (60s clock skew tolerance)
    if (payload.nbf && payload.nbf > (now + 60)) {
      return { ok: false, reason: `token not yet valid (nbf=${payload.nbf}, now=${now})` };
    }

    // Validate issuer — must match Cloudflare Access OIDC issuer
    const expectedIssuer = getExpectedIssuer(env);
    if (expectedIssuer && payload.iss !== expectedIssuer) {
      return { ok: false, reason: `issuer mismatch (got ${payload.iss}, expected ${expectedIssuer})` };
    }

    // Validate audience — must match our OIDC client_id
    if (payload.aud) {
      const audList = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
      if (!audList.includes(env.ACCESS_CLIENT_ID)) {
        return { ok: false, reason: `audience mismatch (got ${payload.aud}, expected ${env.ACCESS_CLIENT_ID})` };
      }
    }

    // Validate nonce (prevents replay attacks in OIDC flow)
    if (expectedNonce) {
      if (payload.nonce !== expectedNonce) {
        return { ok: false, reason: 'nonce mismatch' };
      }
    }

    return { ok: true, payload };
  } catch (error) {
    return { ok: false, reason: `verification exception: ${error}` };
  }
}

/**
 * Derive expected OIDC issuer from ACCESS_AUTHORIZATION_URL.
 * Format: https://{team}.cloudflareaccess.com/cdn-cgi/access/sso/oidc/{client_id}/authorization
 * Issuer: https://{team}.cloudflareaccess.com/cdn-cgi/access/sso/oidc/{client_id}
 */
function getExpectedIssuer(env: Env): string | null {
  try {
    const url = new URL(env.ACCESS_AUTHORIZATION_URL);
    // Strip the trailing /authorization (or /authorize) to get the issuer base
    const path = url.pathname.replace(/\/(authorization|authorize)$/, '');
    return `${url.origin}${path}`;
  } catch {
    return null;
  }
}

// =============================================================================
// OAuth state management (KV-backed)
// =============================================================================

interface OAuthStateData {
  oauthReqInfo: AuthRequest;
  nonce: string;
}

async function createOAuthState(
  oauthReqInfo: AuthRequest,
  kv: KVNamespace,
): Promise<{ stateToken: string; nonce: string }> {
  const stateToken = crypto.randomUUID();
  const nonce = crypto.randomUUID();
  const data: OAuthStateData = { oauthReqInfo, nonce };
  await kv.put(
    `${STATE_KEY_PREFIX}${stateToken}`,
    JSON.stringify(data),
    { expirationTtl: STATE_TTL_SECONDS },
  );
  return { stateToken, nonce };
}

async function validateOAuthState(
  stateToken: string,
  kv: KVNamespace,
): Promise<OAuthStateData | null> {
  const key = `${STATE_KEY_PREFIX}${stateToken}`;
  const stored = await kv.get(key);
  if (!stored) return null;

  // Delete to prevent replay
  await kv.delete(key);

  try {
    const parsed = JSON.parse(stored);
    // Handle both old format (AuthRequest directly) and new format ({ oauthReqInfo, nonce })
    if (parsed.oauthReqInfo) {
      return parsed as OAuthStateData;
    }
    // Legacy: stored was just AuthRequest
    return { oauthReqInfo: parsed as AuthRequest, nonce: '' };
  } catch {
    return null;
  }
}

// =============================================================================
// Client approval (encrypted cookies)
// =============================================================================

function isKnownClient(redirectUri: string): boolean {
  const knownPatterns = [
    /^https:\/\/mcp\.claude\.ai\//,
    /^https:\/\/claude\.ai\//,
    /^https:\/\/one\.dash\.cloudflare\.com\//,
    /^http:\/\/localhost(:\d+)?\//,
    /^http:\/\/127\.0\.0\.1(:\d+)?\//,
  ];
  return knownPatterns.some(p => p.test(redirectUri));
}

async function isClientApproved(
  request: Request,
  clientId: string,
  encryptionKey: string,
): Promise<boolean> {
  const cookie = getCookieValue(request, APPROVED_CLIENTS_COOKIE);
  if (!cookie) return false;

  try {
    const decrypted = await decryptCookie(cookie, encryptionKey);
    const approved: string[] = JSON.parse(decrypted);
    return approved.includes(clientId);
  } catch {
    return false;
  }
}

async function addApprovedClient(
  request: Request,
  clientId: string,
  encryptionKey: string,
): Promise<string> {
  let approved: string[] = [];

  const existing = getCookieValue(request, APPROVED_CLIENTS_COOKIE);
  if (existing) {
    try {
      const decrypted = await decryptCookie(existing, encryptionKey);
      approved = JSON.parse(decrypted);
    } catch {
      // Start fresh
    }
  }

  if (!approved.includes(clientId)) {
    approved.push(clientId);
  }

  const encrypted = await encryptCookie(JSON.stringify(approved), encryptionKey);
  return `${APPROVED_CLIENTS_COOKIE}=${encrypted}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`;
}

// =============================================================================
// Cookie encryption (AES-GCM)
// =============================================================================

async function encryptCookie(plaintext: string, keyHex: string): Promise<string> {
  const keyData = hexToBytes(keyHex);
  const key = await crypto.subtle.importKey('raw', keyData, 'AES-GCM', false, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(plaintext),
  );
  // Encode as iv:ciphertext in base64
  const combined = new Uint8Array(iv.length + new Uint8Array(encrypted).length);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);
  return btoa(String.fromCharCode(...combined));
}

async function decryptCookie(encoded: string, keyHex: string): Promise<string> {
  const keyData = hexToBytes(keyHex);
  const key = await crypto.subtle.importKey('raw', keyData, 'AES-GCM', false, ['decrypt']);
  const combined = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
  const iv = combined.slice(0, 12);
  const ciphertext = combined.slice(12);
  const decrypted = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv },
    key,
    ciphertext,
  );
  return new TextDecoder().decode(decrypted);
}

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

// =============================================================================
// Helpers
// =============================================================================

function getCookieValue(request: Request, name: string): string | null {
  const cookies = request.headers.get('Cookie');
  if (!cookies) return null;
  const match = cookies.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function generateCSRFToken(): string {
  return crypto.randomUUID();
}

function redirectToAccess(
  request: Request,
  env: Env,
  stateToken: string,
  nonce: string,
  extraHeaders: Record<string, string> = {},
): Response {
  const redirectUri = new URL('/callback', request.url).href;
  const params = new URLSearchParams({
    client_id: env.ACCESS_CLIENT_ID,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state: stateToken,
    nonce,
  });

  return new Response(null, {
    status: 302,
    headers: {
      ...extraHeaders,
      Location: `${env.ACCESS_AUTHORIZATION_URL}?${params.toString()}`,
    },
  });
}

function renderApprovalPage(clientId: string, csrfToken: string, stateB64: string): string {
  // Sanitize clientId for display
  const safeClientId = clientId.replace(/[<>&"']/g, c => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#x27;',
  }[c] || c));

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCPbox - Authorize Client</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 60px auto; padding: 0 20px; }
    .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 32px; }
    h1 { font-size: 1.25rem; margin: 0 0 8px; }
    p { color: #6b7280; margin: 0 0 24px; line-height: 1.5; }
    .client-id { font-family: monospace; background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }
    button { background: #2563eb; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1rem; cursor: pointer; width: 100%; }
    button:hover { background: #1d4ed8; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Authorize MCP Client</h1>
    <p>The client <span class="client-id">${safeClientId}</span> wants to connect to your MCPbox server. You'll be redirected to sign in with your identity provider.</p>
    <form method="POST" action="/authorize">
      <input type="hidden" name="csrf_token" value="${csrfToken}">
      <input type="hidden" name="state" value="${stateB64}">
      <button type="submit">Approve &amp; Sign In</button>
    </form>
  </div>
</body>
</html>`;
}
