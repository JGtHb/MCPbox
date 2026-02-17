---
paths:
  - "backend/tests/**"
  - "sandbox/tests/**"
  - "frontend/src/**/__tests__/**"
  - "worker/src/**"
---
# Testing Rules

## General
- Run `./scripts/pre-pr-check.sh` before all PRs
- All new API endpoints require integration tests
- All bug fixes require a regression test
- All new services require unit tests for business logic
- Test files: `test_<module>.py`, test functions: `test_<behavior>`

## Backend Tests
- Use `@pytest.mark.asyncio` for async tests (asyncio_mode = auto in config)
- Use fixtures from `conftest.py`: `db_session`, `async_client`, `admin_headers`, `server_factory`, `tool_factory`
- Mock sandbox client with `mock_sandbox_client` fixture for API tests
- Autouse fixtures handle circuit breaker, rate limiter, and service token cache reset
- Test API key: must be 32+ chars (validation enforced)
- Encryption key for tests: must be exactly 64 hex characters
- Coverage minimum: 60% (enforced in pyproject.toml)

## Sandbox Tests
- Focus on security: sandbox escape attempts, SSRF prevention, code safety validation
- Use `AuthenticatedTestClient` fixture for authenticated requests
- Test both allowed and blocked code patterns

## Frontend Tests
- vitest with React Testing Library
- Mock API calls, don't make real HTTP requests
- Test user interactions, not implementation details

## Worker Tests
- vitest
- Test OAuth flows, CORS handling, URL rewriting, service token injection
- Verify header stripping (prevent spoofing)

## What to Assert
- HTTP status codes (especially error paths: 401, 403, 404, 422)
- Response shape matches Pydantic schema expectations
- Side effects (database state, sandbox calls, activity logs)
- Security: auth required, secrets not leaked, input validated
