# First-Run Experience Review

**Date:** 2026-02-24
**Reviewer perspective:** New user with Docker/Docker Compose installed, no prior MCPbox knowledge
**Method:** Documentation walkthrough cross-referenced against actual code and configuration

---

## Summary

The first-run experience is **functional but has several friction points** that will cost new users time. The biggest issue is a contradiction between the README Quick Start (which omits critical steps) and the Installation guide (which is thorough). Users who follow only the README will hit confusing errors. The frontend onboarding flow itself is well-designed.

**Counts:** 4 Blockers, 7 Friction points, 7 Smooth areas

---

## 1. Clone and Configure

### 1.1 README clarity about what MCPbox does

**Rating:** :green_circle: SMOOTH

The README explains the concept clearly with a concrete example (checking Claude status). The "See It in Action" section and "What is MCPbox?" paragraph give a new user a good mental model within 30 seconds.

### 1.2 README Quick Start omits generating SANDBOX_API_KEY and POSTGRES_PASSWORD

**Rating:** :red_circle: BLOCKER

The README Quick Start (lines 49-59) says:

```bash
cp .env.example .env
# Generate a secure encryption key and add to .env as MCPBOX_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d
```

This only generates `MCPBOX_ENCRYPTION_KEY` and tells the user to "add to .env" without showing how. It does **not** mention `SANDBOX_API_KEY` or `POSTGRES_PASSWORD`, both of which are required. Running `docker compose up -d` after this will fail with:

```
ERROR: missing required environment variable: POSTGRES_PASSWORD is required
```

Meanwhile, `docs/getting-started/installation.md` has the correct, complete instructions:

```bash
cp .env.example .env
echo "MCPBOX_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "SANDBOX_API_KEY=$(openssl rand -hex 32)" >> .env
```

**Fix:** Update the README Quick Start to match the installation guide. Either inline all three `echo` commands, or add a single script (e.g., `./scripts/generate-env.sh`) that generates all secrets.

### 1.3 Secret generation command inconsistency

**Rating:** :yellow_circle: FRICTION

Three different sources suggest different commands:

| Source | Command |
|--------|---------|
| README Quick Start | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `.env.example` comments | `openssl rand -hex 32` |
| Installation guide | `openssl rand -hex 32` (via `echo >>` pattern) |

The Python command is fine but requires Python on the host. The `openssl` command is more universally available. More importantly, the README generates the value but doesn't show how to put it in `.env` (the user must manually edit the file), while the installation guide uses `echo >>` to append automatically.

**Fix:** Standardize on one approach everywhere. The `echo "VAR=$(openssl rand -hex 32)" >> .env` pattern from the installation guide is the best because it generates AND inserts in one step.

### 1.4 MCPBOX_ENCRYPTION_KEY format explanation

**Rating:** :green_circle: SMOOTH

The `.env.example` clearly states "64 hex chars = 32 bytes". The installation guide has a table explaining the format. The backend validator (`backend/app/core/config.py:63-67`) produces a clear error:

```
MCPBOX_ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes),
got {n} characters. Generate with: openssl rand -hex 32
```

### 1.5 Running `docker compose up` without `.env`

**Rating:** :green_circle: SMOOTH

Docker Compose uses `${VAR:?message}` syntax for required variables. If `.env` is missing or variables are empty, the user sees:

```
ERROR: missing required environment variable: POSTGRES_PASSWORD is required
```

The error is clear and appears before any containers start. However, it only shows the **first** missing variable, not all of them, so the user may need to iterate.

---

## 2. First Start

### 2.1 README Quick Start omits database migration step

**Rating:** :red_circle: BLOCKER

The README Quick Start says just `docker compose up -d`. It does **not** mention `alembic upgrade head`. However, the installation guide correctly includes:

```bash
docker compose run --rm backend alembic upgrade head
docker compose up -d
```

**What actually happens:** The `backend/entrypoint.sh` runs `alembic upgrade head` automatically when the container starts (for port 8000 only). So the README Quick Start **happens to work** because the entrypoint handles migrations. But this contradicts both:

- `CLAUDE.md` Gotcha #9: "alembic upgrade head required — Auto table creation disabled. Run migrations before first start."
- The installation guide which shows the manual migration step

This creates confusion: CLAUDE.md and the installation guide say migrations are manual, but the entrypoint automates them. If the entrypoint migration fails silently (e.g., due to a network issue with postgres), the user gets a cryptic database error later with no mention of alembic.

**Fix:** Either:
1. Remove the manual migration step from the installation guide and document that it's automatic (and update CLAUDE.md gotcha #9), OR
2. Remove the auto-migration from `entrypoint.sh` and keep it manual

Option 1 is better for first-run UX. If keeping auto-migration, add error handling to `entrypoint.sh` so migration failures produce a clear message.

### 2.2 First-run migration failure produces no actionable error

**Rating:** :yellow_circle: FRICTION

If the auto-migration in `entrypoint.sh` fails (e.g., postgres not ready despite healthcheck), the script does `set -e` and exits. The user sees the container restart loop but the migration error scrolls past in logs. There's no retry logic and no "migration failed, please run X" message.

If a user somehow bypasses migration entirely, the first API call (`/auth/status`) crashes with:

```
sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.UndefinedTableError)
relation "admin_user" does not exist
```

**Fix:** Add a startup health check that verifies critical tables exist, or wrap the migration in entrypoint.sh with a clear error message on failure.

### 2.3 What the user sees at http://localhost:3000

**Rating:** :green_circle: SMOOTH

The frontend has a well-designed first-run flow:

1. **Loading spinner** while checking `/auth/status`
2. **Setup page** ("MCPbox Setup — Create your admin account") with username/password/confirm fields
3. **Login page** after account creation
4. **Onboarding modal** (2-step) after first login:
   - Step 1: Security profile selection (Strict/Balanced/Permissive) with "Strict" recommended
   - Step 2: Optional remote access setup
5. **Dashboard** with stats, activity feed, system status

This is the strongest part of the first-run experience. The onboarding modal can be skipped, security defaults are sensible, and the flow is linear.

### 2.4 First-run errors in docker compose logs

**Rating:** :yellow_circle: FRICTION

On a clean first start, the logs show a security warning:

```
SECURITY: JWT_SECRET_KEY not set — derived from MCPBOX_ENCRYPTION_KEY.
Set a separate JWT_SECRET_KEY for production deployments.
```

This is correct behavior (JWT_SECRET_KEY is optional) but may alarm a new user who doesn't understand if this is an error or just a recommendation. The `.env.example` marks `JWT_SECRET_KEY` as optional with a comment "If omitted, derived from MCPBOX_ENCRYPTION_KEY (less secure)" which is fine, but a new user scanning logs for errors may not connect the two.

**Fix:** Downgrade the log level from "SECURITY:" prefix to "INFO:" or add context like "This is safe for local use."

---

## 3. Create First Tool

### 3.1 Creating a tool from the UI

**Rating:** :yellow_circle: FRICTION

Tools cannot be created from the admin UI. The UI is for **reviewing and approving** tools, not creating them. Tools are created by the LLM via MCP tools (`mcpbox_create_tool`). This is by design, but the README and Quick Start guide don't make this immediately obvious.

A new user opening the dashboard sees "No servers yet" with the hint "Use `mcpbox_create_server` to create one" — but this hint assumes the user already has an MCP client connected. The dashboard doesn't explain that tools are created by the LLM, not by the admin.

**Fix:** Add a "Getting Started" card or banner on the empty dashboard that says something like: "MCPbox tools are created by your LLM. Connect an MCP client to get started. [See how →]"

### 3.2 Approval workflow explanation

**Rating:** :green_circle: SMOOTH

`docs/guides/approval-workflow.md` clearly explains the three approval types, the tool state machine (draft → pending_review → approved/rejected), and what to look for when reviewing. The onboarding modal's security profile selection sets up auto-approve vs manual-approve expectations early.

### 3.3 First tool guide accuracy

**Rating:** :green_circle: SMOOTH

`docs/guides/first-tool.md` walks through the complete lifecycle with a concrete example (checking Claude status). The MCP tool calls shown match the actual API. The guide covers what globals are available in tool code (`http`, `json`, `datetime`, `arguments`, `secrets`), parameter handling, and module requests.

---

## 4. Connect MCP Client

### 4.1 MCP client configuration examples

**Rating:** :green_circle: SMOOTH

`docs/getting-started/connecting-clients.md` provides correct JSON config for Claude Code and instructions for Cursor. The endpoint `http://localhost:8000/mcp` is correct — the backend serves `/mcp` at port 8000 (registered via `mcp_router` in `backend/app/main.py:152`).

### 4.2 Documented endpoint works

**Rating:** :red_circle: BLOCKER — documentation is misleading about architecture

`http://localhost:8000/mcp` **does work** (the backend includes the MCP router). However, the nginx config (`frontend/nginx.conf.template`) does **not** proxy `/mcp` to the backend. This means:

- `http://localhost:8000/mcp` — works (direct backend access)
- `http://localhost:3000/mcp` — does NOT work (nginx has no `/mcp` proxy rule, returns the React SPA's index.html)

The documentation correctly points to port 8000, so users who follow the docs will be fine. But this becomes a problem if a user assumes that since the web UI is at `:3000`, MCP should also go through `:3000`. The architecture diagram shows the frontend proxying to the backend, which reinforces this assumption.

Additionally, the `docker-compose.yml` binds the backend to `127.0.0.1:${MCPBOX_BACKEND_PORT:-8000}:8000`, which is correct for local access. But if a user changes the port via `MCPBOX_BACKEND_PORT`, they must also update their MCP client config — this is not documented.

**Fix:** Add a note in the connecting-clients doc: "If you changed `MCPBOX_BACKEND_PORT` in `.env`, use that port instead of 8000." Consider adding an nginx proxy rule for `/mcp` so that `localhost:3000/mcp` also works.

### 4.3 Misconfigured client errors

**Rating:** :yellow_circle: FRICTION

If a user points their MCP client at the wrong URL:

- **Wrong port (e.g., :3000):** Gets HTML back (React SPA), client shows a generic "connection failed" or JSON parse error with no mention of MCPbox
- **Backend not running:** Connection refused — client-dependent error message, not from MCPbox
- **Wrong path (e.g., /api/mcp):** Gets 404 from backend, but the error body is a generic FastAPI 404

None of these errors tell the user "you should connect to `http://localhost:8000/mcp`." This is a limitation of being a server rather than a client, but a custom 404 page with a hint would help.

**Fix:** Add a catch-all route or custom 404 handler in the backend that mentions the correct MCP endpoint when a request looks like an MCP attempt.

---

## 5. Error Messages

### 5.1 Missing `.env` error message

**Rating:** :green_circle: SMOOTH

Docker Compose's `${VAR:?message}` syntax produces clear errors:

```
ERROR: missing required environment variable: POSTGRES_PASSWORD is required
ERROR: missing required environment variable: MCPBOX_ENCRYPTION_KEY is required
ERROR: missing required environment variable: SANDBOX_API_KEY is required
```

Only shows one at a time, but iterating through them is straightforward.

### 5.2 Database not migrated error message

**Rating:** :yellow_circle: FRICTION

Since `entrypoint.sh` auto-runs migrations, this scenario only occurs if migrations fail silently. The resulting error is:

```
sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.UndefinedTableError)
relation "admin_user" does not exist
```

This is a raw SQLAlchemy traceback with no mention of alembic or how to fix it.

**Fix:** Add a startup check that verifies the database schema is initialized, with a clear error message: "Database tables not found. Run: docker compose run --rm backend alembic upgrade head"

### 5.3 Invalid MCPBOX_ENCRYPTION_KEY error message

**Rating:** :green_circle: SMOOTH

Validation errors from `backend/app/core/config.py` are specific and actionable:

- Empty: `"MCPBOX_ENCRYPTION_KEY is required. Generate with: openssl rand -hex 32"`
- Wrong length: `"MCPBOX_ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes), got {n} characters. Generate with: openssl rand -hex 32"`
- Invalid chars: `"MCPBOX_ENCRYPTION_KEY must contain only hexadecimal characters (0-9, a-f). Generate with: openssl rand -hex 32"`

Each error includes the generation command.

### 5.4 SANDBOX_API_KEY too short

**Rating:** :green_circle: SMOOTH

Similarly clear: `"SANDBOX_API_KEY must be at least 32 characters, got {n}. Generate with: openssl rand -hex 32"`

---

## Ordered Friction Point List

| # | Rating | Area | Issue | Impact |
|---|--------|------|-------|--------|
| 1 | :red_circle: BLOCKER | README Quick Start | Omits `SANDBOX_API_KEY` and `POSTGRES_PASSWORD` generation; `docker compose up` fails immediately | User cannot start without finding the installation guide |
| 2 | :red_circle: BLOCKER | README Quick Start | Shows `python` command to generate key but doesn't show how to add it to `.env`; installation guide uses `echo >>` which works | User must figure out manual file editing |
| 3 | :red_circle: BLOCKER | Migration confusion | README says just `docker compose up -d`; installation guide says run `alembic upgrade head` first; `entrypoint.sh` auto-runs migrations; CLAUDE.md says migrations are manual — four contradictory signals | User doesn't know which source to trust; if auto-migration fails, no clear error |
| 4 | :red_circle: BLOCKER | Dashboard empty state | No UI guidance that tools are created by the LLM, not the admin UI; dashboard says "Use `mcpbox_create_server`" which assumes MCP client is connected | User opens UI expecting to create tools and is stuck |
| 5 | :yellow_circle: FRICTION | Secret generation | Three sources use different commands (`python`, `openssl`), different insertion methods (manual vs `echo >>`) | User confused about which approach is correct |
| 6 | :yellow_circle: FRICTION | Migration failure | If entrypoint.sh migration fails, error is a raw SQLAlchemy traceback with no mention of alembic | User cannot self-diagnose |
| 7 | :yellow_circle: FRICTION | Security log warning | `SECURITY: JWT_SECRET_KEY not set` warning on first start may alarm users | User may think something is broken |
| 8 | :yellow_circle: FRICTION | Port change undocumented | Changing `MCPBOX_BACKEND_PORT` requires updating MCP client config; not documented | User changes port, MCP client can't connect |
| 9 | :yellow_circle: FRICTION | Wrong URL errors | Connecting MCP client to wrong URL (`:3000/mcp`, wrong path) gives generic errors with no MCPbox-specific guidance | User can't self-diagnose connection issues |
| 10 | :yellow_circle: FRICTION | One error at a time | Docker Compose shows only the first missing env var, not all of them | User iterates 3 times to get all secrets |
| 11 | :yellow_circle: FRICTION | UI tool creation | Cannot create tools from admin UI (by design), but this isn't explained in the UI itself for new users | User expects CRUD operations from the admin panel |
| 12 | :green_circle: SMOOTH | README concept | Clear explanation of what MCPbox does with concrete example | — |
| 13 | :green_circle: SMOOTH | Missing `.env` errors | Docker Compose `${VAR:?msg}` pattern gives clear errors before containers start | — |
| 14 | :green_circle: SMOOTH | Key validation errors | All three validators include format requirements AND generation commands | — |
| 15 | :green_circle: SMOOTH | Frontend onboarding | Setup → Login → Security Profile → Dashboard flow is well-designed and skippable | — |
| 16 | :green_circle: SMOOTH | Approval workflow docs | Clear state machine, review guidance, three approval types explained | — |
| 17 | :green_circle: SMOOTH | First tool guide | Complete lifecycle example matching actual API | — |
| 18 | :green_circle: SMOOTH | MCP client docs | Correct endpoint, multiple client examples, verification steps | — |

---

## Recommended Priority Fixes

### P0 — Fix before next release

1. **Rewrite README Quick Start** to match the installation guide: include all three secret generation commands with `echo >>` syntax, or add a `./scripts/generate-env.sh` helper
2. **Reconcile migration documentation**: Since `entrypoint.sh` auto-runs migrations, remove the manual step from the installation guide and update CLAUDE.md gotcha #9. Add error handling to `entrypoint.sh` for migration failures.
3. **Add first-run guidance to dashboard empty state**: When no servers exist and no MCP client has connected, show a getting-started card explaining the workflow (connect client → LLM creates tools → you approve)

### P1 — Improve within next few releases

4. **Standardize secret generation commands** across all docs to use the `openssl` + `echo >>` approach
5. **Add database schema validation on startup** with a clear error message pointing to `alembic upgrade head`
6. **Add port-change documentation** for MCP client configuration
7. **Downgrade JWT_SECRET_KEY derivation log** from `SECURITY:` to `INFO:` with added context about safety for local use
