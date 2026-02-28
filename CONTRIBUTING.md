# Contributing to MCPbox

Thanks for your interest in contributing! MCPbox is a self-extending MCP platform where LLMs create their own tools.

## Branching Model

| Branch | Purpose | Deploys to |
|--------|---------|------------|
| `develop` | Default branch. All PRs merge here. | CI only |
| `main` | Stable releases only. | Tagged releases |

- **Feature work**: branch from `develop`, open a PR back to `develop`
- **Releases**: open a PR from `develop` → `main`, merge it, then tag `vX.Y.Z`
- **Hotfixes**: branch from `main`, PR to both `main` and `develop`
- **All changes to `main` and `develop` go through PRs** — never push directly

## Getting Started

```bash
git clone https://github.com/JGtHb/MCPbox.git
cd MCPbox
git checkout develop

cp .env.example .env

# Generate required secrets
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env

docker compose run --rm backend alembic upgrade head
docker compose up -d
```

## Development Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (backend/sandbox development)
- Node.js 20+ (frontend/worker development)

### Running Tests

```bash
# All checks (format, lint, tests) — run before every PR
./scripts/pre-pr-check.sh

# Individual test suites
cd backend && pytest tests -v          # requires Docker (testcontainers)
cd sandbox && pytest tests -v
cd frontend && npm test
cd worker && npm test

# Lint only
ruff check backend/app sandbox/app
ruff format --check backend/app sandbox/app
```

Backend tests use [testcontainers](https://testcontainers-python.readthedocs.io/) to spin up a PostgreSQL instance — Docker must be running.

### Database Migrations

```bash
cd backend && alembic upgrade head
```

Always use Alembic migrations. Auto table creation is disabled.

## Making Changes

1. **Check existing issues** before creating new ones
2. **Fork and branch** from `develop`
3. **Write tests** for new features and bug fixes
4. **Run `./scripts/pre-pr-check.sh`** before submitting
5. **Follow existing code style** — Ruff handles Python formatting and linting

### Code Structure

| Directory | What goes here |
|-----------|---------------|
| `backend/app/api/` | FastAPI route handlers |
| `backend/app/services/` | Business logic |
| `backend/app/schemas/` | Pydantic request/response models |
| `backend/app/models/` | SQLAlchemy ORM models |
| `backend/tests/` | Backend tests |
| `frontend/src/pages/` | React page components |
| `frontend/src/api/` | API client functions |
| `sandbox/app/` | Sandboxed Python executor |
| `worker/src/` | Cloudflare Worker (TypeScript) |

### Adding a New API Endpoint

1. Route handler in `backend/app/api/`
2. Register in `backend/app/api/router.py`
3. Service in `backend/app/services/`
4. Pydantic schemas in `backend/app/schemas/`
5. Tests in `backend/tests/`

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Write a clear description of what changed and why
- Include test coverage for new functionality
- All CI checks must pass
- PRs target `develop` unless it's a hotfix

## Releases

Releases are cut from `develop` → `main` via PR:

1. Open a PR from `develop` → `main` (never push directly)
2. Merge the PR
3. Tag: `git tag v0.X.0 && git push origin v0.X.0`
4. GitHub Actions creates a release with auto-generated notes

## Security

If you discover a security vulnerability, please open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repository instead of opening a public issue.

## License

By contributing, you agree that your contributions will be licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).
