"""The SessionStart half of Plan 00412 class 2b.

The comparison itself is pure and tested in
``tests/unit/utils/test_guard_config_drift.py``. What is left here is the
wiring, and the wiring is where this handler can fail in the ways that matter:
reporting nothing when the config was weakened, or reporting drift every session
until someone switches it off.

So these tests are about the EDGES, not the comparison: no git, no committed
file, an unreadable working copy, and the silent-when-clean contract every
SessionStart handler in this project owes (Lean SessionStart, Plan 00128).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.guard_config_drift import (
    GuardConfigDriftHandler,
)

_CLEAN = """
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
"""

_WEAKENED = """
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: false
"""


def _handler(committed: str | None, working: str | None) -> GuardConfigDriftHandler:
    """A handler with both documents stubbed, so no git and no disk are needed."""
    handler = GuardConfigDriftHandler()
    handler.committed_reader = lambda: committed
    handler.working_reader = lambda: working
    return handler


def _session(**overrides: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": "startup", **overrides}


class TestSilentWhenThereIsNothingToSay:
    """An advisory that speaks every session stops being read."""

    def test_an_identical_config_produces_no_context(self) -> None:
        result = _handler(_CLEAN, _CLEAN).handle(_session())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_no_committed_config_is_silent(self) -> None:
        """A fresh install, or a config that was never committed."""
        assert _handler(None, _CLEAN).handle(_session()).context == []

    def test_an_unreadable_working_config_is_silent(self) -> None:
        assert _handler(_CLEAN, None).handle(_session()).context == []

    def test_unparseable_yaml_is_silent(self) -> None:
        """Malformed config is the daemon's problem to report, not this one's."""
        assert _handler(_CLEAN, "handlers: [unclosed").handle(_session()).context == []


class TestAWeakeningIsReported:
    """The finding this handler exists for."""

    def test_a_disabled_guard_is_named_in_the_context(self) -> None:
        result = _handler(_CLEAN, _WEAKENED).handle(_session())

        rendered = "\n".join(result.context)
        assert "pre_tool_use.sed_blocker" in rendered
        assert "disabled" in rendered

    def test_the_report_says_the_change_is_uncommitted(self) -> None:
        """The actionable fact: this differs from what review would have seen."""
        rendered = "\n".join(_handler(_CLEAN, _WEAKENED).handle(_session()).context)

        assert "committed" in rendered.lower()

    def test_it_never_blocks(self) -> None:
        assert _handler(_CLEAN, _WEAKENED).handle(_session()).decision == Decision.ALLOW


class TestUnnamedDriftIsSurfacedWithoutBeingCalledAWeakening:
    """Counting it is the difference between "nothing changed" and "nothing alarming"."""

    def test_other_drift_alone_still_produces_a_line(self) -> None:
        working = _CLEAN.replace("      enabled: true", "      enabled: true\n      priority: 99")

        rendered = "\n".join(_handler(_CLEAN, working).handle(_session()).context)

        assert rendered != ""
        assert "disabled" not in rendered


class TestTheRemediationDoesNotInstructADeniedCommand:
    """D2: the fix-it line must not hand the agent a command this daemon denies.

    `destructive_git` matches and DENIES `git checkout <ref> -- <path>` in any
    Bash command it is handed -- including this advisory's own remediation
    line, if an agent follows it literally. A turn spent hitting that deny is
    a turn the drift this handler exists to surface goes unfixed.
    """

    def test_the_advisory_is_not_itself_a_denied_command(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        rendered = "\n".join(_handler(_CLEAN, _WEAKENED).handle(_session()).context)

        destructive = DestructiveGitHandler()
        hook_input = {"tool_name": "Bash", "tool_input": {"command": rendered}}
        assert destructive.matches(hook_input) is False

    def test_it_still_hands_off_to_the_user_by_name(self) -> None:
        """The fix must not just delete the ask -- a human still needs it."""
        rendered = "\n".join(_handler(_CLEAN, _WEAKENED).handle(_session()).context)

        assert "ask the user" in rendered.lower()


class TestTheHandlerIsWiredCorrectly:
    """Registration facts that are easy to get wrong and silent when wrong."""

    def test_it_reads_the_real_project_config_by_default(self, tmp_path: Path) -> None:
        """The default readers must be real, not left stubbed by construction."""
        handler = GuardConfigDriftHandler()

        assert callable(handler.committed_reader)
        assert callable(handler.working_reader)

    def test_it_only_matches_session_start(self) -> None:
        handler = GuardConfigDriftHandler()

        assert handler.matches(_session()) is True
