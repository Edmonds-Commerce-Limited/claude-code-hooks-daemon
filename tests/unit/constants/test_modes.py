"""Tests for daemon mode constants."""

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant


class TestDaemonMode:
    """Tests for DaemonMode StrEnum."""

    def test_default_mode_value(self) -> None:
        assert DaemonMode.DEFAULT == "default"
        assert DaemonMode.DEFAULT.value == "default"

    def test_unattended_mode_value(self) -> None:
        assert DaemonMode.UNATTENDED == "unattended"
        assert DaemonMode.UNATTENDED.value == "unattended"

    def test_is_str_enum(self) -> None:
        """DaemonMode values should be usable as strings."""
        assert isinstance(DaemonMode.DEFAULT, str)
        assert isinstance(DaemonMode.UNATTENDED, str)

    def test_from_string(self) -> None:
        """Can construct DaemonMode from string value."""
        assert DaemonMode("default") == DaemonMode.DEFAULT
        assert DaemonMode("unattended") == DaemonMode.UNATTENDED

    def test_invalid_mode_raises(self) -> None:
        """Invalid mode string should raise ValueError."""
        import pytest

        with pytest.raises(ValueError):
            DaemonMode("invalid_mode")

    def test_all_modes(self) -> None:
        """Verify expected number of modes."""
        all_modes = list(DaemonMode)
        assert len(all_modes) == 2
        assert DaemonMode.DEFAULT in all_modes
        assert DaemonMode.UNATTENDED in all_modes


class TestModeConstant:
    """Tests for ModeConstant values."""

    def test_action_names(self) -> None:
        assert ModeConstant.ACTION_GET_MODE == "get_mode"
        assert ModeConstant.ACTION_SET_MODE == "set_mode"

    def test_config_keys(self) -> None:
        assert ModeConstant.CONFIG_DEFAULT_MODE == "default_mode"

    def test_ipc_keys(self) -> None:
        assert ModeConstant.KEY_MODE == "mode"
        assert ModeConstant.KEY_CUSTOM_MESSAGE == "custom_message"
        assert ModeConstant.KEY_STATUS == "status"

    def test_status_values(self) -> None:
        assert ModeConstant.STATUS_CHANGED == "changed"
        assert ModeConstant.STATUS_UNCHANGED == "unchanged"

    def test_unattended_block_reason_is_nonempty(self) -> None:
        assert len(ModeConstant.UNATTENDED_BLOCK_REASON) > 0
        assert "UNATTENDED" in ModeConstant.UNATTENDED_BLOCK_REASON
