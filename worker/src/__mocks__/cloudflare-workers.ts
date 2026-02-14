/**
 * Stub for cloudflare:workers module.
 * Provides minimal implementations needed by @cloudflare/workers-oauth-provider
 * so tests can run outside the Cloudflare Workers runtime.
 */
export class WorkerEntrypoint {
  ctx: unknown;
  env: unknown;
  constructor(ctx?: unknown, env?: unknown) {
    this.ctx = ctx;
    this.env = env;
  }
  fetch(_request: Request): Response | Promise<Response> {
    return new Response("Not implemented", { status: 501 });
  }
}
