# MCPbox Documentation

> **Start here:** For AI assistants, see [CLAUDE.md](../CLAUDE.md) in the project root.

## Documents

### Setup & Operations

| Document | Description |
|----------|-------------|
| [PRODUCTION-DEPLOYMENT.md](PRODUCTION-DEPLOYMENT.md) | Environment variables, HTTPS, monitoring, backups |
| [REMOTE-ACCESS-SETUP.md](REMOTE-ACCESS-SETUP.md) | Remote access via Cloudflare Workers VPC |
| [CLOUDFLARE-SETUP-WIZARD.md](CLOUDFLARE-SETUP-WIZARD.md) | Automated 6-step Cloudflare setup wizard |
| [INCIDENT-RESPONSE.md](INCIDENT-RESPONSE.md) | Operational runbooks for failure scenarios |

### Architecture & Design

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical design, module map, database schema, Docker networks |
| [AUTH-FLOW.md](AUTH-FLOW.md) | Worker + Gateway authentication and authorization flow |
| [DECISIONS.md](DECISIONS.md) | Architecture decision records (ADRs) |
| [SECURITY.md](SECURITY.md) | Security risk registry and mitigations |

### Reference

| Document | Description |
|----------|-------------|
| [MCP-MANAGEMENT-TOOLS.md](MCP-MANAGEMENT-TOOLS.md) | Reference for all 24 `mcpbox_*` tools |
| [FEATURES.md](FEATURES.md) | Feature inventory with status and test coverage |
| [TESTING.md](TESTING.md) | Test coverage map and infrastructure |
| [FRONTEND-STANDARDS.md](FRONTEND-STANDARDS.md) | UI style guide (Rosé Pine theme) |

### Strategy

| Document | Description |
|----------|-------------|
| [COMPETITIVE-ANALYSIS.md](COMPETITIVE-ANALYSIS.md) | How MCPbox fits in the MCP ecosystem |
| [FUTURE-EPICS.md](FUTURE-EPICS.md) | Feature roadmap |

## Documentation Guidelines

When adding new documentation:

1. **CLAUDE.md** — Update if project status or architecture changes
2. **ARCHITECTURE.md** — Update for technical design changes
3. **FUTURE-EPICS.md** — Add new feature plans here

Avoid creating new planning documents. Consolidate into existing files.
