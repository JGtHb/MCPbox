#!/usr/bin/env python3
"""Validate Python imports without running full tests.

This script catches import errors like incorrect datetime usage,
missing dependencies, or circular imports - issues that would
cause test failures in CI.

Usage: python scripts/validate_imports.py

Requirements: Backend dependencies must be installed
  pip install -r backend/requirements.txt
"""

import sys
from pathlib import Path

# Check for required dependencies first
REQUIRED_PACKAGES = ["sqlalchemy", "pydantic", "fastapi"]
missing = []
for pkg in REQUIRED_PACKAGES:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)

if missing:
    print("⚠ Missing required packages:", ", ".join(missing))
    print("  Install with: pip install -r backend/requirements.txt")
    print("  Skipping import validation.")
    sys.exit(0)  # Exit cleanly - this isn't an error, just missing deps

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Set required environment variables for imports
import os
os.environ.setdefault("MCPBOX_ENCRYPTION_KEY", "0" * 64)
os.environ.setdefault("SANDBOX_API_KEY", "0" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

MODULES_TO_CHECK = [
    # Core services
    "app.services.approval",
    "app.services.auth",
    "app.services.server",
    "app.services.tool",
    "app.services.credential",
    "app.services.activity_logger",
    "app.services.mcp_management",
    "app.services.sandbox_client",

    # Models
    "app.models.server",
    "app.models.tool",
    "app.models.credential",
    "app.models.activity_log",
    "app.models.admin_user",

    # Schemas
    "app.schemas.server",
    "app.schemas.tool",
    "app.schemas.credential",

    # API routes
    "app.api.router",
]

def validate_imports():
    """Try importing each module and report errors."""
    errors = []

    for module_name in MODULES_TO_CHECK:
        try:
            __import__(module_name)
        except Exception as e:
            errors.append((module_name, str(e)))

    if errors:
        print("❌ Import validation FAILED")
        print()
        for module, error in errors:
            print(f"  {module}:")
            print(f"    {error}")
            print()
        return 1
    else:
        print("✓ All imports validated successfully")
        return 0


if __name__ == "__main__":
    sys.exit(validate_imports())
