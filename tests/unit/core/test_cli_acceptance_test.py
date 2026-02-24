"""Tests for CliAcceptanceTest dataclass."""

import pytest

from claude_code_hooks_daemon.core.cli_acceptance_test import CliAcceptanceTest


class TestCliAcceptanceTest:
    """Tests for CliAcceptanceTest dataclass."""

    def test_basic_creation(self) -> None:
        """Creates a valid CliAcceptanceTest."""
        test = CliAcceptanceTest(
            title="Test restart advisory",
            description="Verify restart prints mode advisory",
            command="$PYTHON -m claude_code_hooks_daemon.daemon.cli restart",
            expected_stdout_patterns=["Mode before restart"],
            expected_exit_code=0,
        )

        assert test.title == "Test restart advisory"
        assert test.expected_exit_code == 0
        assert test.expected_stdout_patterns == ["Mode before restart"]
        assert test.setup_commands is None
        assert test.cleanup_commands is None
        assert test.safety_notes is None

    def test_with_setup_and_cleanup(self) -> None:
        """Creates test with setup and cleanup commands."""
        test = CliAcceptanceTest(
            title="Test with setup",
            description="Has setup and cleanup",
            command="some-command",
            expected_stdout_patterns=["expected"],
            expected_exit_code=0,
            setup_commands=["set-mode unattended"],
            cleanup_commands=["set-mode default"],
        )

        assert test.setup_commands == ["set-mode unattended"]
        assert test.cleanup_commands == ["set-mode default"]

    def test_empty_title_raises(self) -> None:
        """Empty title raises ValueError."""
        with pytest.raises(ValueError, match="title"):
            CliAcceptanceTest(
                title="",
                description="desc",
                command="cmd",
                expected_stdout_patterns=["pat"],
                expected_exit_code=0,
            )

    def test_empty_command_raises(self) -> None:
        """Empty command raises ValueError."""
        with pytest.raises(ValueError, match="command"):
            CliAcceptanceTest(
                title="title",
                description="desc",
                command="  ",
                expected_stdout_patterns=["pat"],
                expected_exit_code=0,
            )

    def test_empty_description_raises(self) -> None:
        """Empty description raises ValueError."""
        with pytest.raises(ValueError, match="description"):
            CliAcceptanceTest(
                title="title",
                description="",
                command="cmd",
                expected_stdout_patterns=["pat"],
                expected_exit_code=0,
            )

    def test_default_exit_code_is_zero(self) -> None:
        """Default expected_exit_code is 0."""
        test = CliAcceptanceTest(
            title="title",
            description="desc",
            command="cmd",
            expected_stdout_patterns=["pat"],
        )
        assert test.expected_exit_code == 0
