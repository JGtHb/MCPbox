"""Tests for gateway-level email policy enforcement (defense-in-depth).

If Cloudflare Access is misconfigured (e.g. set to "allow everyone" instead
of specific emails), the gateway must still enforce the admin's intended
email allowlist stored in CloudflareConfig.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.auth_simple import verify_mcp_auth
from app.services.email_policy_cache import EmailPolicyCache
from app.services.service_token_cache import ServiceTokenCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_request(
    client_host: str = "127.0.0.1",
    email: str | None = None,
) -> MagicMock:
    """Create a mock FastAPI Request with optional email header."""
    mock_request = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = client_host
    mock_request.headers = MagicMock()
    mock_request.headers.get = MagicMock(
        side_effect=lambda key, default=None: {
            "X-MCPbox-User-Email": email,
        }.get(key, default)
    )
    return mock_request


def _make_service_token_cache(token: str = "a" * 32) -> MagicMock:
    mock_cache = MagicMock()
    mock_cache.is_auth_enabled = AsyncMock(return_value=True)
    mock_cache.get_token = AsyncMock(return_value=token)
    return mock_cache


def _make_email_policy_cache(
    policy_type: str | None = None,
    allowed_emails: set[str] | None = None,
    allowed_domain: str | None = None,
    db_error: bool = False,
) -> EmailPolicyCache:
    """Create an EmailPolicyCache with pre-set state (no DB needed)."""
    cache = EmailPolicyCache()
    cache._policy_type = policy_type
    cache._allowed_emails = allowed_emails
    cache._allowed_domain = allowed_domain
    cache._db_error = db_error
    cache._last_loaded = time.monotonic()
    return cache


# ===========================================================================
# EmailPolicyCache unit tests
# ===========================================================================


class TestEmailPolicyCacheCheckEmail:
    """Unit tests for EmailPolicyCache.check_email()."""

    @pytest.mark.asyncio
    async def test_no_policy_allows_all(self):
        """No policy configured (local mode) — allow any email."""
        cache = _make_email_policy_cache(policy_type=None)
        allowed, _ = await cache.check_email("anyone@example.com")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_no_policy_allows_none_email(self):
        """No policy configured — allow even without an email."""
        cache = _make_email_policy_cache(policy_type=None)
        allowed, _ = await cache.check_email(None)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_everyone_policy_allows_all(self):
        """'everyone' policy — allow any authenticated user."""
        cache = _make_email_policy_cache(policy_type="everyone")
        allowed, _ = await cache.check_email("anyone@anywhere.com")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_everyone_policy_allows_no_email(self):
        """'everyone' policy — allow even without email."""
        cache = _make_email_policy_cache(policy_type="everyone")
        allowed, _ = await cache.check_email(None)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_emails_policy_allows_listed_email(self):
        """'emails' policy — listed email is allowed."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com", "bob@example.com"},
        )
        allowed, _ = await cache.check_email("alice@example.com")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_emails_policy_case_insensitive(self):
        """'emails' policy — comparison is case-insensitive."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )
        allowed, _ = await cache.check_email("Alice@Example.COM")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_emails_policy_blocks_unlisted_email(self):
        """'emails' policy — unlisted email is denied."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )
        allowed, reason = await cache.check_email("eve@attacker.com")
        assert allowed is False
        assert "not in gateway allowlist" in reason

    @pytest.mark.asyncio
    async def test_emails_policy_blocks_none_email(self):
        """'emails' policy — missing email is denied."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )
        allowed, reason = await cache.check_email(None)
        assert allowed is False
        assert "required" in reason

    @pytest.mark.asyncio
    async def test_email_domain_policy_allows_matching(self):
        """'email_domain' policy — matching domain is allowed."""
        cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="example.com",
        )
        allowed, _ = await cache.check_email("anyone@example.com")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_email_domain_policy_case_insensitive(self):
        """'email_domain' policy — domain comparison is case-insensitive."""
        cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="example.com",
        )
        allowed, _ = await cache.check_email("User@EXAMPLE.COM")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_email_domain_policy_blocks_wrong_domain(self):
        """'email_domain' policy — wrong domain is denied."""
        cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="example.com",
        )
        allowed, reason = await cache.check_email("eve@attacker.com")
        assert allowed is False
        assert "does not match" in reason

    @pytest.mark.asyncio
    async def test_email_domain_policy_blocks_subdomain(self):
        """'email_domain' policy — subdomain does NOT match (no wildcard)."""
        cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="example.com",
        )
        allowed, _ = await cache.check_email("user@sub.example.com")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_email_domain_policy_blocks_none_email(self):
        """'email_domain' policy — missing email is denied."""
        cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="example.com",
        )
        allowed, reason = await cache.check_email(None)
        assert allowed is False
        assert "required" in reason

    @pytest.mark.asyncio
    async def test_db_error_fails_closed(self):
        """DB unreachable — fail closed (deny all)."""
        cache = _make_email_policy_cache(db_error=True)
        allowed, reason = await cache.check_email("alice@example.com")
        assert allowed is False
        assert "unavailable" in reason

    @pytest.mark.asyncio
    async def test_unknown_policy_type_fails_closed(self):
        """Unknown policy type — fail closed."""
        cache = _make_email_policy_cache(policy_type="something_new")
        allowed, reason = await cache.check_email("user@example.com")
        assert allowed is False
        assert "unknown" in reason

    @pytest.mark.asyncio
    async def test_empty_emails_set_fails_closed(self):
        """'emails' policy with empty set (parse error fallback) — deny all."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails=set(),
        )
        allowed, _ = await cache.check_email("alice@example.com")
        assert allowed is False

    def test_invalidate_clears_state(self):
        """invalidate() resets all cached state."""
        cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )
        cache.invalidate()
        assert cache._policy_type is None
        assert cache._allowed_emails is None
        assert cache._allowed_domain is None
        assert cache._last_loaded == 0.0


# ===========================================================================
# Integration: verify_mcp_auth + EmailPolicyCache
# ===========================================================================


class TestVerifyMcpAuthEmailPolicy:
    """Tests that verify_mcp_auth enforces the email policy."""

    @pytest.mark.asyncio
    async def test_allowed_email_passes(self):
        """Email on the allowlist passes authentication."""
        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            user = await verify_mcp_auth(
                request=_make_mock_request(email="alice@example.com"),
                x_mcpbox_service_token=test_token,
            )

        assert user.email == "alice@example.com"
        assert user.source == "worker"

    @pytest.mark.asyncio
    async def test_disallowed_email_blocked(self):
        """Email NOT on the allowlist is rejected with 403."""
        from fastapi import HTTPException

        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=_make_mock_request(email="eve@attacker.com"),
                    x_mcpbox_service_token=test_token,
                )
            assert exc_info.value.status_code == 403
            assert "authentication failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_domain_policy_allowed(self):
        """Email matching domain policy passes."""
        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="corp.example.com",
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            user = await verify_mcp_auth(
                request=_make_mock_request(email="bob@corp.example.com"),
                x_mcpbox_service_token=test_token,
            )

        assert user.email == "bob@corp.example.com"

    @pytest.mark.asyncio
    async def test_domain_policy_blocked(self):
        """Email from wrong domain is rejected."""
        from fastapi import HTTPException

        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(
            policy_type="email_domain",
            allowed_domain="corp.example.com",
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=_make_mock_request(email="eve@evil.com"),
                    x_mcpbox_service_token=test_token,
                )
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_everyone_policy_allows_any(self):
        """'everyone' policy allows any email through."""
        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(policy_type="everyone")

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            user = await verify_mcp_auth(
                request=_make_mock_request(email="anyone@anywhere.com"),
                x_mcpbox_service_token=test_token,
            )

        assert user.email == "anyone@anywhere.com"

    @pytest.mark.asyncio
    async def test_no_policy_allows_all(self):
        """No policy configured (fresh setup) — no enforcement."""
        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(policy_type=None)

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            user = await verify_mcp_auth(
                request=_make_mock_request(email="user@example.com"),
                x_mcpbox_service_token=test_token,
            )

        assert user.email == "user@example.com"

    @pytest.mark.asyncio
    async def test_db_error_denies_all(self):
        """DB unreachable on first load — fail closed, deny all."""
        from fastapi import HTTPException

        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(db_error=True)

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=_make_mock_request(email="alice@example.com"),
                    x_mcpbox_service_token=test_token,
                )
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_error_detail_is_generic(self):
        """Denial reason is NOT leaked in the HTTP response detail."""
        from fastapi import HTTPException

        test_token = "a" * 32
        svc_cache = _make_service_token_cache(test_token)
        policy_cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_mcp_auth(
                    request=_make_mock_request(email="eve@attacker.com"),
                    x_mcpbox_service_token=test_token,
                )
            # Must use the same generic detail as other auth failures
            assert exc_info.value.detail == "Authentication failed"
            # Must NOT reveal the specific denial reason
            assert "allowlist" not in exc_info.value.detail
            assert "eve" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_local_mode_skips_policy_check(self):
        """Local mode (no service token) does not check email policy."""
        svc_cache = MagicMock()
        svc_cache.is_auth_enabled = AsyncMock(return_value=False)

        # Even a restrictive policy should not block local mode
        policy_cache = _make_email_policy_cache(
            policy_type="emails",
            allowed_emails={"alice@example.com"},
        )

        with (
            patch.object(ServiceTokenCache, "get_instance", return_value=svc_cache),
            patch.object(EmailPolicyCache, "get_instance", return_value=policy_cache),
        ):
            user = await verify_mcp_auth(
                request=_make_mock_request(),
                x_mcpbox_service_token=None,
            )

        assert user.source == "local"
