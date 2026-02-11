"""Tests for package installer security."""

from unittest.mock import AsyncMock, patch

import pytest

from app.package_installer import install_package


class TestPipCommandSecurity:
    """Verify that pip install commands include security flags."""

    @pytest.mark.asyncio
    async def test_only_binary_flag_present(self):
        """pip install must use --only-binary :all: to prevent setup.py execution.

        Without this flag, malicious packages can run arbitrary code via
        setup.py during installation, bypassing all sandbox restrictions.
        """
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("app.package_installer.is_stdlib_module", return_value=False),
            patch(
                "app.package_installer.get_package_name_for_module",
                return_value="some-package",
            ),
            patch(
                "app.package_installer.is_package_installed",
                return_value=(False, None),
            ),
            patch(
                "asyncio.create_subprocess_exec", return_value=mock_process
            ) as mock_exec,
        ):
            await install_package("some_package")

            # Verify pip was called
            mock_exec.assert_called_once()
            cmd_args = mock_exec.call_args[0]

            # Verify --only-binary :all: is in the command
            cmd_list = list(cmd_args)
            assert "--only-binary" in cmd_list, (
                "pip install must include --only-binary flag"
            )
            only_binary_idx = cmd_list.index("--only-binary")
            assert cmd_list[only_binary_idx + 1] == ":all:", (
                "pip install must use --only-binary :all:"
            )
