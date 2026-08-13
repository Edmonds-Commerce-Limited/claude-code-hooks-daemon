"""Unit tests for ReleaseBlockerHandler (project-specific handler).

Tests the Stop event handler that blocks session ending during releases
until acceptance tests are complete.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision

from .release_blocker import ReleaseBlockerHandler


class TestReleaseBlockerHandlerInitialization:
    """Test handler initialization and configuration."""

    def test_handler_name(self) -> None:
        """Handler should have correct name."""
        handler = ReleaseBlockerHandler()
        assert handler.name == "release-blocker"

    def test_priority(self) -> None:
        """Handler should have priority 12 (before AutoContinueStop at 15)."""
        handler = ReleaseBlockerHandler()
        assert handler.priority == 12

    def test_terminal_flag(self) -> None:
        """Handler should be terminal to prevent session ending."""
        handler = ReleaseBlockerHandler()
        assert handler.terminal is True


class TestReleaseBlockerHandlerMatches:
    """Test handler matching logic."""

    def test_matches_returns_false_when_stop_hook_active_snake_case(self) -> None:
        """Handler should not match when stop_hook_active=True (prevent infinite loops)."""
        handler = ReleaseBlockerHandler()
        hook_input = {"stop_hook_active": True}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_when_stop_hook_active_camel_case(self) -> None:
        """Handler should not match when stopHookActive=True (prevent infinite loops)."""
        handler = ReleaseBlockerHandler()
        hook_input = {"stopHookActive": True}
        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_matches_returns_false_when_no_release_files_modified(
        self, mock_run: MagicMock
    ) -> None:
        """Handler should not match when no release files are modified."""
        handler = ReleaseBlockerHandler()

        # Mock git status output with no release files
        mock_run.return_value = MagicMock(
            returncode=0, stdout="M  some/random/file.py\nM  tests/test_something.py\n"
        )

        hook_input = {}
        assert handler.matches(hook_input) is False

        # Verify git command was called
        mock_run.assert_called_once_with(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            timeout=Timeout.GIT_CONTEXT,
            check=False,
        )

    @patch("subprocess.run")
    def test_matches_returns_true_when_pyproject_toml_modified(self, mock_run: MagicMock) -> None:
        """Handler should match when pyproject.toml is modified."""
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="M  pyproject.toml\n")

        hook_input = {}
        assert handler.matches(hook_input) is True

    @patch("subprocess.run")
    def test_matches_returns_true_when_version_py_modified(self, mock_run: MagicMock) -> None:
        """Handler should match when version.py is modified."""
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(
            returncode=0, stdout="M  src/claude_code_hooks_daemon/version.py\n"
        )

        hook_input = {}
        assert handler.matches(hook_input) is True

    @patch("subprocess.run")
    def test_does_NOT_match_when_only_readme_modified(self, mock_run: MagicMock) -> None:
        """README.md is edited constantly for reasons that are not releases.

        Plan 00234 finding H-1. This handler is `terminal=True` and DENIES the
        Stop event, so treating an ordinary docs edit as "RELEASE IN PROGRESS"
        traps the session until the file is committed or the handler is turned
        off. A release always touches a version file; README alone never means
        one is under way.
        """
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="M  README.md\n")

        hook_input = {}
        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_does_NOT_match_when_only_claude_md_modified(self, mock_run: MagicMock) -> None:
        """CLAUDE.md is REGENERATED AND AUTO-COMMITTED by the daemon itself.

        Every daemon restart can leave it dirty, so keeping it in the trigger
        set means the daemon could trap the session by its own routine action.
        """
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="M  CLAUDE.md\n")

        hook_input = {}
        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_still_matches_when_a_version_file_accompanies_the_readme(
        self, mock_run: MagicMock
    ) -> None:
        """Narrowing the trigger must not blind the guard.

        A real release edits README.md AND a version file. The version file is
        what proves it, and it must still fire.
        """
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="M  README.md\nM  pyproject.toml\n")

        hook_input = {}
        assert handler.matches(hook_input) is True

    @patch("subprocess.run")
    def test_matches_returns_true_when_changelog_modified(self, mock_run: MagicMock) -> None:
        """Handler should match when CHANGELOG.md is modified."""
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="M  CHANGELOG.md\n")

        hook_input = {}
        assert handler.matches(hook_input) is True

    @patch("subprocess.run")
    def test_matches_returns_true_when_releases_file_added(self, mock_run: MagicMock) -> None:
        """Handler should match when RELEASES/vX.Y.Z.md is added."""
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=0, stdout="A  RELEASES/v2.13.0.md\n")

        hook_input = {}
        assert handler.matches(hook_input) is True

    @patch("subprocess.run")
    def test_matches_returns_false_when_git_status_fails(self, mock_run: MagicMock) -> None:
        """Handler should silently allow when git status fails."""
        handler = ReleaseBlockerHandler()

        mock_run.return_value = MagicMock(returncode=1, stdout="")

        hook_input = {}
        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_matches_returns_false_when_git_times_out(self, mock_run: MagicMock) -> None:
        """Handler should silently allow when git command times out."""
        handler = ReleaseBlockerHandler()

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=Timeout.GIT_CONTEXT)

        hook_input = {}
        assert handler.matches(hook_input) is False

    @patch("subprocess.run")
    def test_matches_returns_false_when_os_error(self, mock_run: MagicMock) -> None:
        """Handler should silently allow when OS error occurs."""
        handler = ReleaseBlockerHandler()

        mock_run.side_effect = OSError("Git not found")

        hook_input = {}
        assert handler.matches(hook_input) is False


class TestReleaseBlockerHandlerHandle:
    """Test handler execution behavior."""

    def test_handle_returns_deny_decision(self) -> None:
        """Handler should return DENY decision to block session ending."""
        handler = ReleaseBlockerHandler()
        hook_input = {}

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY

    def test_handle_returns_clear_reason_message(self) -> None:
        """Handler should return clear reason explaining why session is blocked."""
        handler = ReleaseBlockerHandler()
        hook_input = {}

        result = handler.handle(hook_input)

        # Check for key message components
        assert "RELEASE IN PROGRESS" in result.reason
        assert "acceptance tests" in result.reason
        assert "RELEASING.md Step 8" in result.reason
        assert "handlers.stop.release_blocker" in result.reason
        assert "enabled: false" in result.reason

    def test_handle_does_not_assert_a_hardcoded_test_count(self) -> None:
        """A count copied into a block message drifts and then misleads.

        This message asserted "89 EXECUTABLE acceptance tests". The suite is
        described in RELEASING.md, which is the source of truth and moves
        without this file noticing — the same drift CLAUDE.md already records
        for the QA check count ("it drifted to '10' while the suite ran 13").
        Point at the document instead of restating its contents.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        assert "89" not in result.reason

    def test_handle_references_a_path_that_exists(self) -> None:
        """A block message must not send the reader to a moved file.

        The plan folder it cited was archived into `Completed/`, so the path
        in the message stopped resolving. A block is only as useful as the
        next step it points at.
        """
        handler = ReleaseBlockerHandler()

        result = handler.handle({})

        cited = Path("/workspace/CLAUDE/Plan/Completed/00060-release-blocker-handler")
        assert (
            cited.is_dir()
        ), "the cited plan folder must exist for this assertion to mean anything"
        assert "CLAUDE/Plan/Completed/00060-release-blocker-handler" in result.reason
