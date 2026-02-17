---
paths:
  - "backend/**"
  - "sandbox/**"
---
# Python Code Style

- Python 3.11+ required. Use `Type | None` syntax, not `Optional[Type]`
- Type hints on all function signatures (enforced by mypy `disallow_untyped_defs = true`)
- Line length: 100 characters (ruff enforced)
- Imports sorted by isort (ruff I rule)
- Use `async def` for all route handlers and service methods that touch the database or make HTTP calls
- HTTPException status codes: use `from starlette import status` enums (e.g., `status.HTTP_404_NOT_FOUND`), not integer literals
- All list API endpoints must return paginated responses: `{ items, total, page, page_size, pages }`
- Business logic goes in `services/`, not in route handlers. Route handlers should validate input, call service, return response.
- Database access via SQLAlchemy async ORM with `AsyncSession`. Never use raw SQL.
- Pydantic schemas in `schemas/` for all request/response validation
- Configuration via `backend/app/core/config.py` settings singleton. Never hardcode config values.
- Format before committing: `ruff format backend/app sandbox/app`
- Lint check: `ruff check backend/app sandbox/app`
