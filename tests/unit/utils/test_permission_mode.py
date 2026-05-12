"""Tests for utils/permission_mode.py — bypass-mode detection helper."""

from __future__ import annotations

from typing import Any, cast

import pytest

from claude_code_hooks_daemon.utils.permission_mode import (
    BYPASS_PERMISSIONS_MODE,
    is_bypass_mode,
)


class TestIsBypassMode:
    """Tests for is_bypass_mode(hook_input)."""

    def test_returns_true_for_bypass_permissions(self) -> None:
        assert is_bypass_mode({"permission_mode": "bypassPermissions"}) is True

    def test_returns_false_for_default(self) -> None:
        assert is_bypass_mode({"permission_mode": "default"}) is False

    def test_returns_false_for_plan(self) -> None:
        assert is_bypass_mode({"permission_mode": "plan"}) is False

    def test_returns_false_for_accept_edits(self) -> None:
        assert is_bypass_mode({"permission_mode": "acceptEdits"}) is False

    def test_returns_false_for_dont_ask(self) -> None:
        assert is_bypass_mode({"permission_mode": "dontAsk"}) is False

    def test_returns_false_when_key_missing(self) -> None:
        assert is_bypass_mode({"tool_name": "Read"}) is False

    def test_returns_false_for_none_value(self) -> None:
        assert is_bypass_mode({"permission_mode": None}) is False

    def test_returns_false_for_empty_string(self) -> None:
        assert is_bypass_mode({"permission_mode": ""}) is False

    def test_returns_false_for_unknown_mode_value(self) -> None:
        assert is_bypass_mode({"permission_mode": "someFutureMode"}) is False

    def test_returns_false_for_none_input(self) -> None:
        assert is_bypass_mode(None) is False

    def test_returns_false_for_non_dict_input(self) -> None:
        assert is_bypass_mode(cast("Any", "bypassPermissions")) is False
        assert is_bypass_mode(cast("Any", 42)) is False
        assert is_bypass_mode(cast("Any", [])) is False

    def test_returns_false_for_empty_dict(self) -> None:
        assert is_bypass_mode({}) is False

    @pytest.mark.parametrize(
        "case_variant",
        ["BypassPermissions", "BYPASSPERMISSIONS", "bypasspermissions"],
    )
    def test_case_sensitive_match_only(self, case_variant: str) -> None:
        """Only the exact `bypassPermissions` value (camelCase) is a bypass."""
        assert is_bypass_mode({"permission_mode": case_variant}) is False


class TestBypassPermissionsConstant:
    """Module-level constant smoke test."""

    def test_constant_value_is_camelcase_exact(self) -> None:
        assert BYPASS_PERMISSIONS_MODE == "bypassPermissions"
