# Pull Request Skill

Create a pull request with proper pre-checks and CI monitoring.

## Phase 1: Pre-flight Checks

1. **Run ruff on all modified Python files:**
   ```bash
   # Find modified Python files relative to main
   git diff --name-only origin/main...HEAD -- '*.py' | xargs -r ruff check --fix
   git diff --name-only origin/main...HEAD -- '*.py' | xargs -r ruff format
   ```

2. **Check for uncommitted changes from linting:**
   ```bash
   git status
   # If there are changes, commit them with message "style: apply ruff formatting"
   ```

3. **Push branch to origin:**
   ```bash
   git push -u origin HEAD
   ```

## Phase 2: Create or Update PR

1. **Check if PR already exists:**
   ```bash
   gh pr list --head $(git branch --show-current) --json number,url
   ```

2. **If no PR exists, create one:**
   ```bash
   gh pr create --title "..." --body "$(cat <<'EOF'
   ## Summary
   <bullet points>

   ## Test plan
   <checklist>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

3. **If PR exists, just push (already done in Phase 1)**

## Phase 3: Monitor CI and Fix Failures

This is the critical phase. After PR is created/updated:

1. **Wait for CI to start:**
   ```bash
   sleep 10  # Give GitHub time to start checks
   ```

2. **Poll CI status until complete:**
   ```bash
   gh pr view --json statusCheckRollup
   ```
   - Check every 30 seconds
   - Continue until all checks are COMPLETED

3. **If any checks FAILED:**
   a. Get the failed job logs:
      ```bash
      gh run view <run_id> --log-failed | tail -500
      ```

   b. Analyze failures and categorize:
      - **Linting failures**: Run ruff again, commit, push
      - **Test failures**: Analyze error messages, fix code or tests
      - **Type errors**: Fix type annotations

   c. For each failure:
      - Read the relevant source files
      - Understand what the test expects vs what happened
      - Fix the issue (code or test, depending on which is wrong)
      - Commit with descriptive message
      - Push

   d. **Loop back to step 2** - wait for new CI run

4. **Success criteria:**
   - All CI checks pass (SUCCESS or NEUTRAL)
   - Report final PR URL to user

## Failure Analysis Patterns

### Rate Limit Errors (429)
- Check if `_reset_rate_limiter_state()` is being called
- Ensure `conftest.py` has proper autouse fixture
- May need to reset RateLimiter singleton between tests

### KeyError in Response
- Test expects a field that API no longer returns
- Check actual API response schema
- Update test expectations to match current API

### Assert X == Y (wrong status code)
- 401: Missing auth headers - add `admin_headers` fixture
- 404: Endpoint path changed or resource not found
- 422: Request validation failed - check request body
- 500: Server error - check logs for exception

### Mock Not Working
- For FastAPI dependencies: use `app.dependency_overrides[func] = lambda: mock`
- Don't use `patch("module.func")` for Depends() functions

### Outdated Test Expectations
- Count mismatches (e.g., `19 == 14`): Feature added new items
- Field existence: API schema changed
- Update tests to match current implementation

## Usage

```
/pr
```

Arguments (optional): $ARGUMENTS
- Can specify PR title as argument

## Important Notes

- **Never give up after first CI failure** - always analyze and fix
- **Loop until green** - keep fixing until all checks pass
- **Commit fixes separately** - one commit per logical fix for clarity
- **Read actual code** before fixing - don't guess at solutions
