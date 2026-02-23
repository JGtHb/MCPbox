# Contributing to MCPbox

Thanks for your interest in contributing! MCPbox is a self-extending MCP platform where LLMs create their own tools.

## Getting Started

```bash
git clone https://github.com/JGtHb/MCPbox.git
cd MCPbox
cp .env.example .env
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
2. **Fork and branch** from `main`
3. **Write tests** for new features and bug fixes
4. **Run `./scripts/pre-pr-check.sh`** before submitting — it runs formatting, linting, and all test suites
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

## Security

If you discover a security vulnerability, please open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repository instead of opening a public issue.

## License

By contributing, you agree that your contributions will be licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).
