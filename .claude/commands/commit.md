# Commit Skill

Run pre-commit checks and create a commit with proper formatting.

## Steps

1. **Run ruff linter and formatter on all modified Python files:**
   ```bash
   # Get list of modified Python files (staged and unstaged)
   git diff --name-only --diff-filter=ACMR HEAD -- '*.py' | xargs -r ruff check --fix
   git diff --name-only --diff-filter=ACMR HEAD -- '*.py' | xargs -r ruff format
   ```

2. **Run TypeScript/ESLint checks if frontend files changed:**
   ```bash
   # Check if any frontend files are modified
   if git diff --name-only HEAD -- 'frontend/' | grep -q .; then
     cd frontend && npm run lint
   fi
   ```

3. **Show git status and diff for review:**
   ```bash
   git status
   git diff --stat
   ```

4. **Stage all changes and create commit:**
   - Ask user for commit message if not provided as argument: $ARGUMENTS
   - Use conventional commit format (feat:, fix:, docs:, style:, refactor:, test:, chore:)
   - Add Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>

## Usage

```
/commit fix: resolve null pointer in auth handler
```

Or just `/commit` to be prompted for a message.
