"""Tests for ModeManager."""

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.mode import ModeManager


class TestModeManagerInit:
    """Tests for ModeManager initialization."""

    def test_default_init(self) -> None:
        manager = ModeManager()
        assert manager.current_mode == DaemonMode.DEFAULT
        assert manager.custom_message is None

    def test_init_with_mode(self) -> None:
        manager = ModeManager(initial_mode=DaemonMode.UNATTENDED)
        assert manager.current_mode == DaemonMode.UNATTENDED

    def test_init_with_custom_message(self) -> None:
        manager = ModeManager(
            initial_mode=DaemonMode.UNATTENDED,
            custom_message="finish the release",
        )
        assert manager.current_mode == DaemonMode.UNATTENDED
        assert manager.custom_message == "finish the release"


class TestModeManagerSetMode:
    """Tests for ModeManager.set_mode()."""

    def test_set_mode_returns_true_on_change(self) -> None:
        manager = ModeManager()
        result = manager.set_mode(DaemonMode.UNATTENDED)
        assert result is True
        assert manager.current_mode == DaemonMode.UNATTENDED

    def test_set_mode_returns_false_when_unchanged(self) -> None:
        manager = ModeManager()
        result = manager.set_mode(DaemonMode.DEFAULT)
        assert result is False

    def test_set_mode_with_custom_message(self) -> None:
        manager = ModeManager()
        manager.set_mode(DaemonMode.UNATTENDED, custom_message="do the thing")
        assert manager.current_mode == DaemonMode.UNATTENDED
        assert manager.custom_message == "do the thing"

    def test_set_mode_clears_custom_message(self) -> None:
        manager = ModeManager(
            initial_mode=DaemonMode.UNATTENDED,
            custom_message="old message",
        )
        manager.set_mode(DaemonMode.DEFAULT)
        assert manager.custom_message is None

    def test_same_mode_different_message_returns_true(self) -> None:
        manager = ModeManager(
            initial_mode=DaemonMode.UNATTENDED,
            custom_message="old",
        )
        result = manager.set_mode(DaemonMode.UNATTENDED, custom_message="new")
        assert result is True
        assert manager.custom_message == "new"

    def test_same_mode_same_message_returns_false(self) -> None:
        manager = ModeManager(
            initial_mode=DaemonMode.UNATTENDED,
            custom_message="same",
        )
        result = manager.set_mode(DaemonMode.UNATTENDED, custom_message="same")
        assert result is False

    def test_round_trip_default_unattended_default(self) -> None:
        manager = ModeManager()
        assert manager.current_mode == DaemonMode.DEFAULT

        manager.set_mode(DaemonMode.UNATTENDED)
        assert manager.current_mode == DaemonMode.UNATTENDED

        manager.set_mode(DaemonMode.DEFAULT)
        assert manager.current_mode == DaemonMode.DEFAULT
        assert manager.custom_message is None


class TestModeManagerToDict:
    """Tests for ModeManager.to_dict()."""

    def test_default_to_dict(self) -> None:
        manager = ModeManager()
        result = manager.to_dict()
        assert result == {
            ModeConstant.KEY_MODE: "default",
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

    def test_unattended_to_dict(self) -> None:
        manager = ModeManager(
            initial_mode=DaemonMode.UNATTENDED,
            custom_message="finish tasks",
        )
        result = manager.to_dict()
        assert result == {
            ModeConstant.KEY_MODE: "unattended",
            ModeConstant.KEY_CUSTOM_MESSAGE: "finish tasks",
        }

    def test_to_dict_uses_mode_constant_keys(self) -> None:
        """Keys should come from ModeConstant, not magic strings."""
        manager = ModeManager()
        result = manager.to_dict()
        assert "mode" in result
        assert "custom_message" in result
