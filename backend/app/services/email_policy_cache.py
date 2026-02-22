"""Email policy cache — defense-in-depth allowlist for remote access.

The Cloudflare Access policy (email allowlist) is the primary enforcement
point for which users can authenticate.  This cache provides a secondary
check at the gateway level so that a Cloudflare Access misconfiguration
(e.g. "allow everyone") does not silently grant access to unauthorized
emails.

The policy (access_policy_type, access_policy_emails, access_policy_email_domain)
is stored in CloudflareConfig by the setup wizard and synced to Cloudflare
Access.  This cache reads it from the database and makes it available for
per-request checks without a DB round-trip on every request.

Follows the same singleton + TTL pattern as ServiceTokenCache.
"""

import json
import logging
import time

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.cloudflare_config import CloudflareConfig

logger = logging.getLogger(__name__)

# How often to re-check the database for policy changes (seconds).
# Matches ServiceTokenCache TTL so admin changes propagate at the same rate.
TTL_SECONDS = 30


class EmailPolicyCache:
    _instance: "EmailPolicyCache | None" = None

    _policy_type: str | None = None  # "emails", "email_domain", "everyone", or None
    _allowed_emails: set[str] | None = None  # normalised to lowercase
    _allowed_domain: str | None = None  # normalised to lowercase
    _last_loaded: float = 0.0
    _db_error: bool = False

    @classmethod
    def get_instance(cls) -> "EmailPolicyCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load access policy from the active CloudflareConfig."""
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(CloudflareConfig).where(CloudflareConfig.status == "active")
                )
                config = result.scalar_one_or_none()
        except Exception:
            if self._policy_type is not None:
                logger.warning("Database unreachable, retaining last known email policy")
            else:
                logger.warning(
                    "Database unreachable on first email policy load, "
                    "failing closed (all remote emails denied)"
                )
                self._db_error = True
            # Don't update _last_loaded — force retry on next access
            return

        self._db_error = False

        if not config or not config.access_policy_type:
            # No active config or no policy set — no enforcement
            self._policy_type = None
            self._allowed_emails = None
            self._allowed_domain = None
            logger.debug("Email policy cache: no policy configured")
        else:
            self._policy_type = config.access_policy_type

            if self._policy_type == "emails" and config.access_policy_emails:
                try:
                    raw: list[str] = json.loads(config.access_policy_emails)
                    self._allowed_emails = {e.lower() for e in raw}
                except (json.JSONDecodeError, TypeError):
                    logger.error(
                        "Failed to parse access_policy_emails JSON, "
                        "failing closed (all emails denied)"
                    )
                    self._allowed_emails = set()
            else:
                self._allowed_emails = None

            if self._policy_type == "email_domain" and config.access_policy_email_domain:
                self._allowed_domain = config.access_policy_email_domain.lower()
            else:
                self._allowed_domain = None

            logger.info(
                "Email policy cache loaded: type=%s, emails=%s, domain=%s",
                self._policy_type,
                len(self._allowed_emails) if self._allowed_emails is not None else "n/a",
                self._allowed_domain or "n/a",
            )

        self._last_loaded = time.monotonic()

    async def _refresh_if_stale(self) -> None:
        if time.monotonic() - self._last_loaded >= TTL_SECONDS:
            await self.load()

    def invalidate(self) -> None:
        """Clear cached policy so the next access triggers a reload."""
        self._policy_type = None
        self._allowed_emails = None
        self._allowed_domain = None
        self._db_error = False
        self._last_loaded = 0.0

    # ------------------------------------------------------------------
    # Policy check
    # ------------------------------------------------------------------

    async def check_email(self, email: str | None) -> tuple[bool, str]:
        """Check whether *email* is allowed by the stored access policy.

        Returns ``(allowed, reason)`` where *reason* explains denials
        (for logging — never expose to the client).

        Semantics:
        - No policy configured → allow (no enforcement, local-only setups).
        - DB unreachable on first load → deny all (fail-closed).
        - policy_type == "everyone" → allow.
        - policy_type == "emails" → email must be in the set.
        - policy_type == "email_domain" → email domain must match.
        - Missing email when a restrictive policy is set → deny.
        """
        await self._refresh_if_stale()

        # No policy configured — nothing to enforce
        if self._policy_type is None and not self._db_error:
            return True, ""

        # DB was unreachable on first load — fail closed
        if self._db_error:
            return False, "email policy unavailable (database unreachable)"

        # "everyone" policy — allow any authenticated user
        if self._policy_type == "everyone":
            return True, ""

        # Restrictive policy but no email provided
        if not email:
            return False, "email required by access policy but not provided"

        normalised = email.lower()

        if self._policy_type == "emails":
            if self._allowed_emails is not None and normalised in self._allowed_emails:
                return True, ""
            return (
                False,
                f"email {email} not in gateway allowlist "
                f"({len(self._allowed_emails or [])} allowed)",
            )

        if self._policy_type == "email_domain":
            if self._allowed_domain and normalised.endswith("@" + self._allowed_domain):
                return True, ""
            return (
                False,
                f"email domain of {email} does not match allowed domain {self._allowed_domain}",
            )

        # Unknown policy type — fail closed
        return False, f"unknown access policy type: {self._policy_type}"
