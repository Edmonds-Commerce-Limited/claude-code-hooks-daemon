"""Tests for DaemonSyncAfterMergeHandler (Plan 00389).

A `git pull` can bring in someone else's daemon config or handler code, and the
running daemon never notices: config is cached at startup and handler modules
are imported once at ``initialise()``, never hot-reloaded. The committed config
is then not the config in force, and nothing says so.

ADVISORY ONLY, by the owner's ruling (Plan 00386 Task 1.1) and because it is
technically necessary: the daemon serves this hook in-process, so a daemon that
restarted itself here would kill the process still owing a response.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.daemon_sync_after_merge import (
    DaemonSyncAfterMergeHandler,
)

_CHANGED_PATHS_TARGET = (
    "claude_code_hooks_daemon.handlers.post_tool_use.daemon_sync_after_merge.changed_paths"
)
_PROJECT_ROOT_TARGET = (
    "claude_code_hooks_daemon.handlers.post_tool_use."
    "daemon_sync_after_merge.ProjectContext.project_root"
)
_CONFIG_PATH_TARGET = (
    "claude_code_hooks_daemon.handlers.post_tool_use."
    "daemon_sync_after_merge.ProjectContext.config_path"
)

_ROOT = Path("/project")
_CONFIG = _ROOT / ".claude" / "hooks-daemon.yaml"


def _pull(command: str = "git pull") -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _handler() -> DaemonSyncAfterMergeHandler:
    return DaemonSyncAfterMergeHandler()


def _handle(handler: DaemonSyncAfterMergeHandler, changed: set[str]) -> Any:
    with (
        patch(_PROJECT_ROOT_TARGET, return_value=_ROOT),
        patch(_CONFIG_PATH_TARGET, return_value=_CONFIG),
        patch(_CHANGED_PATHS_TARGET, return_value=frozenset(changed)),
    ):
        return handler.handle(_pull())


class TestInit:
    def test_identity_and_priority(self) -> None:
        handler = _handler()
        assert handler.name == HandlerID.DAEMON_SYNC_AFTER_MERGE.display_name
        assert handler.priority == Priority.DAEMON_SYNC_AFTER_MERGE

    def test_is_advisory_and_not_terminal(self) -> None:
        """Never blocks: a stale daemon is a reporting problem, not a reason to
        deny the user's next tool call."""
        assert _handler().terminal is False


class TestMatches:
    def test_matches_a_pull(self) -> None:
        assert _handler().matches(_pull("git pull")) is True

    def test_matches_merge_and_rebase(self) -> None:
        assert _handler().matches(_pull("git merge feature")) is True
        assert _handler().matches(_pull("git rebase main")) is True

    def test_does_not_match_an_unrelated_git_command(self) -> None:
        assert _handler().matches(_pull("git status")) is False

    def test_does_not_match_a_non_bash_tool(self) -> None:
        assert _handler().matches({"tool_name": "Write", "tool_input": {}}) is False


class TestConfigDrift:
    def test_a_changed_config_file_advises_a_restart(self) -> None:
        result = _handle(_handler(), {".claude/hooks-daemon.yaml"})
        assert result.decision == Decision.ALLOW
        context = "\n".join(result.context or [])
        assert ".claude/hooks-daemon.yaml" in context, "must name WHICH path changed"
        assert "restart" in context.lower()

    def test_changed_project_handler_code_advises_a_restart(self) -> None:
        result = _handle(_handler(), {".claude/project-handlers/pre_tool_use/thing.py"})
        context = "\n".join(result.context or [])
        assert ".claude/project-handlers" in context
        assert "restart" in context.lower()

    def test_says_the_running_daemon_still_holds_the_old_config(self) -> None:
        """The WHY is the point: without it this reads as a chore to skip."""
        result = _handle(_handler(), {".claude/hooks-daemon.yaml"})
        context = "\n".join(result.context or []).lower()
        assert "not in force" in context or "still" in context


class TestSilence:
    def test_silent_when_the_operation_changed_nothing_relevant(self) -> None:
        """This runs on EVERY pull, so the quiet path is the common one."""
        result = _handle(_handler(), {"README.md", "src/app/thing.py"})
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_silent_when_nothing_changed_at_all(self) -> None:
        result = _handle(_handler(), set())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_sibling_path_sharing_a_prefix_is_not_a_match(self) -> None:
        """`.claude/project-handlers-old/` is a different directory."""
        result = _handle(_handler(), {".claude/project-handlers-old/x.py"})
        assert not result.context


class TestNeverActsOnItsOwn:
    def test_the_advisory_does_not_run_any_command(self) -> None:
        """Pins the owner's ruling by test rather than by prose: this handler
        names a command for a human, and never executes one."""
        with patch("subprocess.run") as run:
            _handle(_handler(), {".claude/hooks-daemon.yaml"})
        run.assert_not_called()
