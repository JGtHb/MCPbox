#!/bin/bash
# Pre-PR checks - run this before creating a pull request
# Usage: ./scripts/pre-pr-check.sh

set -e

echo "=== MCPbox Pre-PR Checks ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=0

# 1. Format check
echo "1. Checking Python formatting..."
if ruff format --check backend/app sandbox/app 2>/dev/null; then
    echo -e "   ${GREEN}✓ Formatting OK${NC}"
else
    echo -e "   ${RED}✗ Formatting issues found${NC}"
    echo "   Run: ruff format backend/app sandbox/app"
    FAILED=1
fi
echo ""

# 2. Lint check
echo "2. Checking Python linting..."
if ruff check backend/app sandbox/app 2>/dev/null; then
    echo -e "   ${GREEN}✓ Linting OK${NC}"
else
    echo -e "   ${RED}✗ Linting issues found${NC}"
    echo "   Run: ruff check --fix backend/app sandbox/app"
    FAILED=1
fi
echo ""

# 3. Python import validation (catches issues like wrong datetime imports)
echo "3. Validating Python imports..."
if python scripts/validate_imports.py 2>/dev/null; then
    echo -e "   ${GREEN}✓ Import validation OK${NC}"
elif [ $? -eq 0 ]; then
    # Script exited cleanly but skipped (missing deps)
    echo -e "   ${YELLOW}⚠ Skipped (missing dependencies)${NC}"
else
    echo -e "   ${RED}✗ Import validation failed${NC}"
    python scripts/validate_imports.py 2>&1 | sed 's/^/   /'
    FAILED=1
fi
echo ""

# 4. Backend tests (if PostgreSQL available)
echo "4. Running backend tests..."
if command -v docker &> /dev/null; then
    echo "   (Using testcontainers for PostgreSQL)"
    cd backend
    if python -m pytest tests -v --tb=short -q 2>/dev/null; then
        echo -e "   ${GREEN}✓ Backend tests passed${NC}"
    else
        echo -e "   ${RED}✗ Backend tests failed${NC}"
        FAILED=1
    fi
    cd ..
else
    echo -e "   ${YELLOW}⚠ Skipped (Docker not available for testcontainers)${NC}"
    echo "   Set TEST_DATABASE_URL to run tests manually"
fi
echo ""

# 5. Sandbox tests
echo "5. Running sandbox tests..."
cd sandbox
if python -m pytest tests -v --tb=short -q 2>/dev/null; then
    echo -e "   ${GREEN}✓ Sandbox tests passed${NC}"
else
    echo -e "   ${RED}✗ Sandbox tests failed${NC}"
    FAILED=1
fi
cd ..
echo ""

# Summary
echo "=== Summary ==="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All checks passed! Ready to create PR.${NC}"
    exit 0
else
    echo -e "${RED}Some checks failed. Please fix before creating PR.${NC}"
    exit 1
fi
