# Test Coverage Map

## Summary

MCPbox maintains **1,139+ test functions** across backend, sandbox, frontend, and worker. Security-critical paths (sandbox escape, SSRF, auth) have excellent coverage. Backend API coverage is good for core endpoints but has gaps in secondary endpoints. Frontend coverage is poor (4 components tested out of ~30). Worker tests are comprehensive.

| Component | Test Files | Test Functions | Estimated Coverage | Grade |
|-----------|-----------|---------------|-------------------|-------|
| Backend | 37 | ~600 | 65-70% | B |
| Sandbox | 13 | ~204 | 75-80% | A |
| Frontend | 4 | ~36 | 15-20% | D |
| Worker | 1 | ~85 | 85% | A |

**Coverage minimum enforced**: Backend `fail_under = 60` in `pyproject.toml`. No minimum for other components.

---

## Coverage by Module

### Backend (`backend/tests/`)

| Module | Unit Tests | Integration Tests | E2E Tests | Estimated Coverage | Critical Gaps |
|--------|-----------|-------------------|-----------|-------------------|---------------|
| `api/approvals.py` | - | 40+ tests | - | 85% | - |
| `api/auth.py` | - | 15+ tests | - | 80% | - |
| `api/cloudflare.py` | - | 30+ tests | - | 80% | - |
| `api/servers.py` | - | 25+ tests | - | 75% | - |
| `api/tools.py` | - | 27 tests | - | 75% | - |
| `api/mcp_gateway.py` | 1 file | 39 tests | - | 70% | Large file (854 lines), needs more edge cases |
| `api/export_import.py` | - | 30+ tests | - | 80% | - |
| `api/dashboard.py` | - | tests exist | - | 60% | - |
| `api/activity.py` | - | 10 tests | - | 50% | WebSocket stream testing limited |
| `api/execution_logs.py` | - | **None** | - | **0%** | **No tests at all** |
| `api/server_secrets.py` | - | **None** | - | **0%** | **No tests at all** |
| `api/health.py` | - | **None** | - | **0%** | **No tests (low risk)** |
| `api/settings.py` | - | indirect only | - | 20% | Route prefix issue untested |
| `api/external_mcp_sources.py` | - | **None** | - | **0%** | New feature, needs tests |
| `services/mcp_management.py` | - | 16 tests | - | 30% | **1,927 lines with only 16 tests** |
| `services/sandbox_client.py` | - | 17 tests | - | 40% | **998 lines, error recovery untested** |
| `services/crypto.py` | 17 tests | - | - | 85% | - |
| `services/approval.py` | - | 25+ tests | - | 80% | - |
| `services/cloudflare.py` | - | 30+ tests | - | 75% | - |
| `services/tool.py` | - | 23 tests | - | 70% | - |
| `services/activity_logger.py` | 18 tests | - | - | 75% | - |
| `services/service_token_cache.py` | 6 tests | - | - | 70% | - |
| `services/url_validator.py` | 25+ tests | - | - | 85% | - |
| `services/execution_log.py` | - | **None** | - | **0%** | **Untested service** |
| `services/tool_change_notifier.py` | - | **None** | - | **0%** | **Untested service** |
| `services/global_config.py` | - | **None** | - | **0%** | - |
| `services/server.py` | 1 file | - | - | 40% | Basic service, lower risk |
| `middleware/admin_auth.py` | - | tests exist | - | 70% | - |
| `middleware/rate_limit.py` | - | tests exist | - | 60% | Edge cases missing |
| `core/config.py` | tests exist | - | - | 60% | - |
| `core/security.py` | tested via auth | - | - | 70% | - |

### Sandbox (`sandbox/tests/`)

| Module | Unit Tests | Integration Tests | E2E Tests | Estimated Coverage | Critical Gaps |
|--------|-----------|-------------------|-----------|-------------------|---------------|
| `executor.py` | 40+ safety, 30+ escape, 30+ hardening | 15+ execute | - | 80% | Concurrent execution untested |
| `ssrf.py` | 25+ tests | - | - | 85% | - |
| `registry.py` | 15+ tests | - | - | 75% | - |
| `mcp_client.py` | 20+ tests | - | - | 70% | SSRF validation gap untested |
| `mcp_session_pool.py` | 15+ tests | - | - | 70% | - |
| `package_installer.py` | 20+ tests | - | - | 75% | - |
| `routes.py` | tested via integration | - | - | 60% | Some endpoints not directly tested |
| `main.py` | 12+ startup tests | - | - | 70% | - |

### Frontend (`frontend/src/**/__tests__/`)

| Module | Unit Tests | Integration Tests | E2E Tests | Estimated Coverage | Critical Gaps |
|--------|-----------|-------------------|-----------|-------------------|---------------|
| `pages/Dashboard.tsx` | 10 tests | - | - | 60% | - |
| `components/ServerCard` | 8 tests | - | - | 70% | - |
| `components/ConfirmModal` | 12 tests | - | - | 80% | - |
| `components/LoadingSpinner` | 6 tests | - | - | 90% | - |
| `pages/Servers.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/ServerDetail.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/Approvals.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/Activity.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/Settings.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/Tunnel.tsx` | **None** | - | - | **0%** | **Untested page** |
| `pages/CloudflareWizard.tsx` | **None** | - | - | **0%** | **Untested page** |
| `hooks/*` | **None** | - | - | **0%** | **No hook tests** |
| `api/*` | **None** | - | - | **0%** | **No API client tests** |

### Worker (`worker/src/`)

| Module | Unit Tests | Integration Tests | E2E Tests | Estimated Coverage | Critical Gaps |
|--------|-----------|-------------------|-----------|-------------------|---------------|
| `index.ts` | 85 tests | - | - | 85% | - |
| `access-handler.ts` | tested via index | - | - | 70% | Some OIDC edge cases |

---

## Test Infrastructure

### Frameworks
- **Backend**: pytest with `pytest-asyncio` (async tests), `httpx` (async HTTP client), `testcontainers` (PostgreSQL)
- **Sandbox**: pytest with `pytest-asyncio`, `pytest-cov` (coverage)
- **Frontend**: vitest 4.x with React Testing Library
- **Worker**: vitest 4.x

### How to Run

```bash
# All checks (recommended before PRs)
./scripts/pre-pr-check.sh

# Backend tests (requires Docker for testcontainers)
cd backend && pytest tests -v

# Backend with coverage
cd backend && pytest tests -v --cov=app --cov-report=term-missing

# Sandbox tests
cd sandbox && pytest tests -v --cov=app

# Frontend tests
cd frontend && npm test

# Worker tests
cd worker && npm test

# Specific test file
cd backend && pytest tests/test_approvals.py -v

# Specific test function
cd backend && pytest tests/test_tools.py::test_create_tool -v
```

### CI Integration

**File**: `.github/workflows/ci.yml`

| Job | Runs On | Coverage Upload |
|-----|---------|----------------|
| Backend Tests | push/PR | codecov (backend) |
| Sandbox Tests | push/PR | codecov (sandbox) |
| Frontend Tests | push/PR | No |
| Worker Tests | push/PR | No |
| Linting (ruff) | push/PR | N/A |
| Type Check (mypy) | push/PR | N/A |
| Dependency Audit | push/PR | N/A |

### Key Fixtures (`backend/tests/conftest.py`, 625 lines)

- `db_engine`, `db_session` — PostgreSQL with auto-cleanup per test
- `async_client` — httpx AsyncClient with DB dependency override
- `admin_user`, `admin_user_factory` — Admin user creation
- `auth_tokens`, `admin_headers` — JWT token generation
- `server_factory`, `tool_factory` — Test data factories
- `mock_sandbox_client` — Mocked sandbox HTTP client
- `reset_circuit_breakers` (autouse) — Prevents cascade failures between tests
- `reset_rate_limiter` (autouse) — Prevents 429 errors in tests
- `reset_service_token_cache` (autouse) — Ensures local mode in tests

### Linting & Formatting

- **Backend/Sandbox**: ruff (format + lint), mypy (strict type checking)
- **Frontend**: ESLint + Prettier + TypeScript strict mode
- **Pre-commit**: `.pre-commit-config.yaml` with ruff, trailing whitespace, YAML validation, large file detection
- **Config**: `ruff.toml` — line length 100, rules: E, W, F, I, B, C4, UP

---

## Critical Untested Paths

Ordered by risk (highest first):

### 1. Tool Approval TOCTOU (SEC-001, SEC-002)
- **Affected modules**: `backend/app/services/tool.py:88-146, 251-289`
- **Risk if broken**: Approved tools can have their code silently replaced or rolled back to malicious versions
- **Recommended test type**: Integration test — verify `approval_status` resets when `python_code` changes on approved tool, and when rollback restores different code
- **Priority**: Critical

### 2. Server Secrets API
- **Affected modules**: `backend/app/api/server_secrets.py`
- **Risk if broken**: Secret creation, retrieval, update, deletion could fail silently. Secret values could leak in API responses.
- **Recommended test type**: Integration tests — CRUD operations, verify values are encrypted, verify responses don't include actual values
- **Priority**: High

### 3. Execution Logs API
- **Affected modules**: `backend/app/api/execution_logs.py`
- **Risk if broken**: Tool execution history inaccessible or leaking sensitive data
- **Recommended test type**: Integration tests — log retrieval, pagination, filtering, verify secrets are redacted
- **Priority**: High

### 4. MCP Management Service (Underexercised)
- **Affected modules**: `backend/app/services/mcp_management.py` (1,927 lines, only 16 tests)
- **Risk if broken**: LLM tool creation/management workflows break silently
- **Recommended test type**: Unit + integration tests for each of the 24 management tools
- **Priority**: High

### 5. Sandbox Client Error Recovery
- **Affected modules**: `backend/app/services/sandbox_client.py` (998 lines, 17 tests)
- **Risk if broken**: Timeout, connection refused, partial responses not handled correctly
- **Recommended test type**: Unit tests with mocked error scenarios (timeout, connection error, malformed JSON)
- **Priority**: Medium

### 6. Frontend Pages (5+ untested)
- **Affected modules**: All page components except Dashboard
- **Risk if broken**: UI rendering errors, form submission failures, routing issues
- **Recommended test type**: Component tests with React Testing Library
- **Priority**: Medium

### 7. External MCP Sources API
- **Affected modules**: `backend/app/api/external_mcp_sources.py`
- **Risk if broken**: External source connections and passthrough tool discovery fails
- **Recommended test type**: Integration tests
- **Priority**: Medium

### 8. Tool Change Notifier
- **Affected modules**: `backend/app/services/tool_change_notifier.py`
- **Risk if broken**: Connected MCP clients don't receive tool list updates
- **Recommended test type**: Unit tests verifying notification broadcast
- **Priority**: Low

---

## Test Quality Issues

### Hardcoded Test Values
- `SANDBOX_API_KEY = "test-sandbox-api-key-for-testing-only"` — used across multiple test files
- `MCPBOX_ENCRYPTION_KEY = "0" * 64` — not realistic padding
- `TEST_ADMIN_PASSWORD = "testpassword123"` — hardcoded everywhere
- Service token: `'0' * 32` — meets minimum length but unrealistic
- **Impact**: Low — these are test fixtures, not production values. But could mask validation edge cases.

### Large Test Files Without Class Organization
- `test_approvals.py` — 819 lines, no class grouping
- `test_mcp_gateway.py` — 38KB, no class grouping
- `test_cloudflare.py` — 22KB, no class grouping
- **Impact**: Harder to navigate and run subsets of tests

### Mock/Real Contract Mismatch Risk
- Some tests mock the sandbox client but don't verify the mock response shape matches the actual sandbox API contract
- Example: `mock_client.execute.return_value = {"success": True, "result": 2}` — real sandbox may return different fields
- **Impact**: Integration issues could be missed

### Missing Error Path Coverage
- Database connection errors (not tested — relies on testcontainers always working)
- External API failures (Cloudflare, PyPI, OSV responses when services are down)
- Timeout scenarios in sandbox communication
- Malformed JSON responses from sandbox
- Partial failures in batch operations (e.g., multi-tool server registration)

### Tests with No Assertions (None Found)
Spot-check verified that all test functions contain assertions. No empty or assertion-free tests found.
