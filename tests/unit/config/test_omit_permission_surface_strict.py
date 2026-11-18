"""``daemon.omit_permission_surface`` is a real boolean (Plan 00618 N-15).

The reader in ``utils/permission_surface`` accepts only a real bool, so a
config value that pydantic's lax coercion would take ("true", "yes", 1) must
fail validation instead of validating and then silently switching nothing on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import DaemonConfig


class TestOmitPermissionSurfaceIsStrictBool:
    @pytest.mark.parametrize("value", ["true", "false", "yes", "on", 1, 0])
    def test_non_boolean_values_are_rejected(self, value: object) -> None:
        with pytest.raises(ValidationError, match="omit_permission_surface"):
            DaemonConfig.model_validate({"omit_permission_surface": value})

    @pytest.mark.parametrize("value", [True, False])
    def test_real_booleans_are_accepted(self, value: bool) -> None:
        config = DaemonConfig.model_validate({"omit_permission_surface": value})
        assert config.omit_permission_surface is value

    def test_default_is_off(self) -> None:
        assert DaemonConfig().omit_permission_surface is False
