# Pre-Release Cleanup Review Session

You are reviewing MCPbox's pre-release cleanup candidates documented in `docs/CONSIDER-REMOVING.md`. This is a systematic triage session where the user decides the fate of each item, and you implement the decisions immediately.

## Process

Work through `docs/CONSIDER-REMOVING.md` **one section at a time** (9 sections total). For each section:

1. **Present** the items in that section with a brief summary of each
2. **Ask** the user for a decision on each item using these options:
   - **Remove** — Delete the code/file now
   - **Fix** — Make the code change described in the recommendation
   - **Defer** — Keep as-is, move to a backlog issue or comment
   - **Keep** — The current state is intentional, remove from the document
3. **Implement** all decisions for that section before moving to the next
4. **Run tests** after implementing changes in each section (`./scripts/pre-pr-check.sh` or targeted test commands)
5. **Commit** the section's changes with a descriptive message
6. **Update documentation** — mark resolved items in `CONSIDER-REMOVING.md` and `INCONSISTENCIES.md` as you go

## Section Order (by impact/risk)

1. **Dead / Duplicate Files** (1a-1c) — trivial, no code risk
2. **Vestigial Database Enum Values** (2a-2b) — requires Alembic migration
3. **Deprecated / Backwards-Compatibility Code** (3a-3b) — API/crypto changes
4. **Overlapping / Duplicate Code** (4a-4c) — refactoring
5. **Code Quality Issues** (5a-5d) — bug fix + refactoring
6. **Hardcoded Values** (6a-6b) — config extraction
7. **Half-Implemented Features** (7a-7b) — feature scope decisions
8. **In-Memory State** (8a-8b) — documentation + minor feature
9. **Duplicate Middleware Initialization** (9a) — refactoring

## Implementation Rules

- Read affected files before making changes (never edit blind)
- For database migrations: create via `cd backend && alembic revision --autogenerate -m "description"`, then verify the generated migration
- For removed files: `git rm` to track the deletion
- For API changes: update corresponding frontend code, test mocks, and API-CONTRACTS.md
- After each section: run the relevant test suite (backend, sandbox, frontend, worker)
- If tests fail: fix before proceeding. Never leave a section with failing tests
- When marking items resolved in CONSIDER-REMOVING.md, use strikethrough + status: `### ~~1a. Duplicate Architecture Doc~~ — **REMOVED**`

## Key Files to Reference

- `docs/CONSIDER-REMOVING.md` — the master list you're working through
- `docs/INCONSISTENCIES.md` — update resolved items here too
- `docs/FEATURES.md` — update if feature scope decisions are made (7a, 7b)
- `docs/TESTING.md` — update if test coverage changes
- `CLAUDE.md` — update if known gotchas or doc references change

## Completion

After all 9 sections are reviewed and implemented:

1. Final `./scripts/pre-pr-check.sh` run
2. Update CONSIDER-REMOVING.md header with summary of decisions
3. Single final commit for any remaining doc updates
4. Create PR with summary of all changes made

## Context

- Nothing has been released — no backwards-compatibility obligations
- 33 Alembic migrations exist, latest is `0033_add_discovered_tools_cache.py`
- Backend tests require Docker (testcontainers PostgreSQL)
- Two entry points share code: `backend/app/main.py` and `backend/app/mcp_only.py`
- Frontend uses `/api/config` endpoint (not the root `/config`)
