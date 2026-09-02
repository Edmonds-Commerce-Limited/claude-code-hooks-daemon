"""Tests for the config_optimisation_reminder SessionStart handler (Plan 00308).

The handler does file-stat work only: it compares the installed daemon
version against the version recorded the last time the config-optimisation
review (``/optimise``) ran, and reminds the agent when they differ (or when
no run was ever recorded). Advisory, non-terminal, never blocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config_optimisation.state import STATE_FILE_NAME, record_run
from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.config_optimisation_reminder import (
    ConfigOptimisationReminderHandler,
)

_STATE_DIR_TARGET = (
    "claude_code_hooks_daemon.handlers.session_start.config_optimisation_reminder."
    "ConfigOptimisationReminderHandler._state_dir"
)
_VERSION_TARGET = (
    "claude_code_hooks_daemon.handlers.session_start.config_optimisation_reminder.__version__"
)


def _hook_input(source: str = "startup") -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": source}


def _handler(enabled: bool = True) -> ConfigOptimisationReminderHandler:
    handler = ConfigOptimisationReminderHandler()
    handler.configure({"enabled": enabled})
    return handler


class TestInit:
    def test_identity(self) -> None:
        handler = ConfigOptimisationReminderHandler()
        assert handler.name == "config-optimisation-reminder"
        assert handler.priority == Priority.CONFIG_OPTIMISATION_REMINDER
        assert handler.terminal is False

    def test_acceptance_tests_present(self) -> None:
        assert ConfigOptimisationReminderHandler().get_acceptance_tests()


class TestMatches:
    def test_matches_new_session(self) -> None:
        assert _handler().matches(_hook_input()) is True

    def test_skips_resume_session(self) -> None:
        target = (
            "claude_code_hooks_daemon.handlers.session_start."
            "config_optimisation_reminder.is_resume_session"
        )
        with patch(target, return_value=True):
            assert _handler().matches(_hook_input()) is False

    def test_skips_when_disabled(self) -> None:
        assert _handler(enabled=False).matches(_hook_input()) is False

    def test_skips_wrong_event(self) -> None:
        assert _handler().matches({"hook_event_name": "Stop"}) is False

    def test_skips_none_and_non_dict(self) -> None:
        assert _handler().matches(None) is False


class TestHandle:
    def test_never_run_reminds(self, tmp_path: Path) -> None:
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert any("optimise" in line for line in result.context)

    def test_reminder_names_the_cli_escape_hatch(self, tmp_path: Path) -> None:
        """B2 fix (v3.59.0 release): the ``/optimise`` skill is not deployed
        to every install (it may be absent or ahead of the daemon's own
        vendored skill copy), so the reminder must also name the CLI
        subcommand that silences it directly — the same command
        ``/optimise``'s own Step 7 runs (`bin/hooks-daemon
        record-config-optimisation-run`) — so the advisory is actionable even
        without the skill."""
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert any("record-config-optimisation-run" in line for line in result.context)

    def test_reminder_binds_the_review_to_this_session(self, tmp_path: Path) -> None:
        """Plan 00322: the advisory must not read as an optional to-do.

        A client upgrade filed this reminder as "run /optimise at some point",
        which is exactly what the deferred mandatory step already was. The
        wording now claims the current session and says so explicitly.
        """
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        text = "\n".join(result.context)
        assert "this session" in text
        assert "not an optional" in text

    def test_reminder_names_the_hooks_daemon_subcommand(self, tmp_path: Path) -> None:
        """Plan 00322: the step lives in the daemon's own skill namespace.

        A bare `/optimise` was a generic top-level name that collides with any
        project or plugin skill called the same thing, so the advisory must
        name the namespaced invocation — and in Skill-tool form, which is what
        the `skill_refs` QA check requires of agent-facing strings.
        """
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        text = "\n".join(result.context)
        assert "skill=hooks-daemon, args=optimise" in text

    def test_escape_hatch_is_qualified_as_a_last_resort(self, tmp_path: Path) -> None:
        """The silence command must not read as an equal-cost alternative."""
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        hatch = next(line for line in result.context if "record-config-optimisation-run" in line)
        assert "Only if" in hatch

    def test_stale_version_reminds(self, tmp_path: Path) -> None:
        record_run(tmp_path / STATE_FILE_NAME, version="0.0.1", now=1000.0)
        with patch(_STATE_DIR_TARGET, return_value=tmp_path), patch(_VERSION_TARGET, "9.9.9"):
            result = _handler().handle(_hook_input())
        assert any("optimise" in line for line in result.context)
        assert any("0.0.1" in line and "9.9.9" in line for line in result.context)

    def test_current_version_is_silent(self, tmp_path: Path) -> None:
        record_run(tmp_path / STATE_FILE_NAME, version="9.9.9", now=1000.0)
        with patch(_STATE_DIR_TARGET, return_value=tmp_path), patch(_VERSION_TARGET, "9.9.9"):
            result = _handler().handle(_hook_input())
        assert result.context == []

    def test_corrupt_state_reminds(self, tmp_path: Path) -> None:
        (tmp_path / STATE_FILE_NAME).write_text("{corrupt")
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert any("optimise" in line for line in result.context)

    def test_state_dir_failure_never_raises(self) -> None:
        with patch(_STATE_DIR_TARGET, side_effect=OSError("boom")):
            result = _handler().handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []
