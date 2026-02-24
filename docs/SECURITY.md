# Security Model

## Overview

MCPbox executes LLM-generated Python code in a sandboxed environment. Security is enforced through multiple independent layers so that no single bypass compromises the system.

## Security Layers

### 1. Code Validation
- **AST analysis** blocks dangerous patterns before execution (dunder access, attribute chains, metaclass manipulation)
- **Import whitelisting** restricts available modules to an admin-approved set
- **Static safety checks** reject code that attempts to escape the sandbox

### 2. Sandbox Isolation
- Code runs in a restricted execution namespace with dangerous builtins removed
- Module access mediated through attribute-filtered proxies
- Resource limits enforced: memory (256 MB), CPU time (60 s), file descriptors (256), stdout (1 MB)
- Network access gated by admin approval with SSRF prevention (private IP blocking, IP pinning, redirect restrictions)

### 3. Approval Workflow
- Tools created by LLMs start in `draft` status and cannot execute until an admin approves them
- Code changes after approval automatically reset the tool to `pending_review`
- Version rollbacks reset approval status unconditionally
- LLMs cannot self-approve tools

### 4. Authentication & Authorization
- **Local mode**: Localhost-only access, no authentication required
- **Remote mode**: Three-layer defense-in-depth:
  - OAuth 2.1 via Cloudflare Worker
  - OIDC identity via Cloudflare Access for SaaS
  - Service token validation between Worker and Gateway
- Admin JWT tokens with server-side blacklist for logout
- Constant-time token comparison for service tokens

### 5. Encryption
- Server secrets encrypted at rest with AES-256-GCM
- Secrets injected as read-only mappings at execution time, never persisted in tool code
- Encryption key derived from operator-provided environment variable

### 6. Network Architecture
- Four isolated Docker networks segment traffic between services
- Sandbox has no direct database or internet access (except admin-approved outbound)
- MCP Gateway runs as a separate process with its own middleware stack
- Cloudflare Tunnel provides remote access without exposing ports

## Operator Responsibilities

- Set strong values for `MCPBOX_ENCRYPTION_KEY` (64 hex chars) and `SANDBOX_API_KEY` (32+ chars)
- Review and approve tool code before allowing execution
- Review module whitelist requests — some modules can enable sandbox escape
- Review network access requests — outbound HTTP can be used for data exfiltration
- Keep Docker images and dependencies updated
- See [PRODUCTION-DEPLOYMENT.md](PRODUCTION-DEPLOYMENT.md) for hardening guidance

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly by opening a GitHub Security Advisory on this repository. Do not file a public issue for security bugs.
