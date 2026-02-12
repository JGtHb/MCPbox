# MCPbox Documentation

> **Start here:** For AI assistants, see [CLAUDE.md](../CLAUDE.md) in the project root.

## Documents

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical design, security model, database schema |
| [PRODUCTION-DEPLOYMENT.md](PRODUCTION-DEPLOYMENT.md) | Production deployment guide and checklist |
| [REMOTE-ACCESS-SETUP.md](REMOTE-ACCESS-SETUP.md) | Remote access via Cloudflare Workers VPC |
| [CLOUDFLARE-SETUP-WIZARD.md](CLOUDFLARE-SETUP-WIZARD.md) | Automated 7-step Cloudflare setup wizard |
| [MCP-MANAGEMENT-TOOLS.md](MCP-MANAGEMENT-TOOLS.md) | MCP tools for programmatic management |
| [INCIDENT-RESPONSE.md](INCIDENT-RESPONSE.md) | Operational runbooks for failure scenarios |
| [FUTURE-EPICS.md](FUTURE-EPICS.md) | Feature roadmap |
| [COMPETITIVE-ANALYSIS.md](COMPETITIVE-ANALYSIS.md) | Why code-first approach vs. visual builders |

## Project Status

**Core epics are complete.** See [CLAUDE.md](../CLAUDE.md) for current status.

| Epic | Status |
|------|--------|
| Epic 1: Foundation | ✅ Complete |
| Epic 4: Cloudflare Tunnel | ✅ Complete |
| Epic 5: Observability | ✅ Complete |
| Epic 6: Python Code Tools | ✅ Complete |
| Epic 7: Tool Approval Workflow | ✅ Complete |

*Note: Legacy API Builder (Epic 2) and OpenAPI Import (Epic 3) have been removed in favor of MCP-first approach.*

## Documentation Guidelines

When adding new documentation:

1. **CLAUDE.md** - Update if project status or architecture changes
2. **ARCHITECTURE.md** - Update for technical design changes
3. **FUTURE-EPICS.md** - Add new feature plans here

Avoid creating new planning documents. Consolidate into existing files.
