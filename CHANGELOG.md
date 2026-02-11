# Changelog

All notable changes to MCPbox will be documented in this file.

## [Unreleased] - Production Readiness Review

### Security
- Add `.dev.vars` and `.dev.vars.*` to `.gitignore` to prevent accidental commit of Cloudflare Worker secrets

### Fixed
- Fix unawaited `CircuitBreaker.reset_all()` in health endpoint — the `/health/circuits/reset` endpoint was silently doing nothing
- Fix unawaited `CircuitBreaker.reset_all()` in test fixtures — circuit breaker state wasn't being reset between tests
- Fix unawaited `SandboxClient.reset_circuit()` in test — async function called without await
- Fix race condition in `CircuitBreaker.reset_all()` and `get_all_states()` — use `list()` snapshot to prevent `RuntimeError` during concurrent dict modification
- Fix WebSocket reconnect race condition in activity stream — clear previous timeout before setting new one to prevent duplicate reconnection attempts
- Fix untracked `setTimeout` calls in Settings page — add ref-based cleanup to prevent state updates after component unmount

### Removed
- Remove unused `fetchConfig()`, `useConfig()`, and `configKeys` from frontend API
- Remove unused `HealthDetailResponse`, `AppConfig`, and `ApiError` interfaces from frontend types
- Remove dead re-exports from `api/index.ts`
- Remove no-op `PythonExecutor.close()` method and empty `__init__` constructor
- Apply formatting fixes to 3 files with pre-existing `ruff format` issues

### Tests
- Add 34 sandbox escape integration tests (`test_sandbox_escape.py`)
  - Dunder attribute blocking: `__class__`, `__mro__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`
  - Dangerous builtin removal: `type()`, `getattr()`, `setattr()`, `eval()`, `exec()`, `compile()`, `open()`
  - Discovery function blocking: `vars()`, `dir()`
  - Import whitelist enforcement and allowed module verification
- Add 22 code safety unit tests (`test_code_safety.py`)
  - Direct tests for `validate_code_safety()` regex pattern detection
  - Edge cases: safe code, multiline scanning, custom source names

### Documentation
- Update README security section to accurately reflect sandbox protections (application-level, not seccomp/read-only)
- Update README architecture diagram to show separate MCP Gateway (:8002)
- Update documentation links to include all available docs
- Add CHANGELOG
