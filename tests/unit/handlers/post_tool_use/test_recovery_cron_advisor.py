"""Tests for RecoveryCronAdvisorHandler - lifecycle advisory for failsafe recovery crons.

Tests cover all three lifecycle phases (creation, progress-update, completion),
cooldown suppression, completion bypassing cooldown, non-plan writes ignored,
and Completed/ directory exclusion.
"""

from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    LifecyclePhase,
    RecoveryCronAdvisorHandler,
    _detect_lifecycle_phase,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def handler() -> RecoveryCronAdvisorHandler:
    """Create a fresh handler instance for each test."""
    return RecoveryCronAdvisorHandler()


def _write_input(file_path: str, content: str) -> dict[str, Any]:
    """Build a PostToolUse Write hook input."""
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
        "tool_output": {},
    }


def _edit_input(file_path: str, new_string: str, old_string: str = "old") -> dict[str, Any]:
    """Build a PostToolUse Edit hook input."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "new_string": new_string,
            "old_string": old_string,
        },
        "tool_output": {},
    }


def _bash_mkplan_input(command: str) -> dict[str, Any]:
    """Build a PostToolUse Bash hook input for mkplan.bash."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_output": {"stdout": "/workspace/CLAUDE/Plan/00042-my-plan\n", "stderr": ""},
    }


# ─── Initialization ───────────────────────────────────────────────────────────


class TestInit:
    """Handler initialization tests."""

    def test_name_is_recovery_cron_advisor(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Handler name should be 'recovery-cron-advisor'."""
        assert handler.name == "recovery-cron-advisor"

    def test_priority_is_30(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Handler priority should be 30 (free PostToolUse slot)."""
        assert handler.priority == 30

    def test_is_non_terminal(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Handler should be non-terminal (advisory)."""
        assert handler.terminal is False

    def test_default_enabled_is_false(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Handler is opt-in — get_default_enabled() must return False."""
        assert handler.get_default_enabled() is False


# ─── _detect_lifecycle_phase helper ─────────────────────────────────────────


class TestDetectLifecyclePhase:
    """Tests for the phase-detection helper function."""

    # --- Creation phase ---

    def test_creation_on_new_plan_write(self) -> None:
        """Writing a new PLAN.md returns CREATION phase."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan 00042\n\n**Status**: Not Started\n",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.CREATION

    def test_creation_on_mkplan_bash(self) -> None:
        """Running mkplan.bash returns CREATION phase."""
        hook_input = _bash_mkplan_input("CLAUDE/Plan/mkplan.bash 'my-feature'")
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.CREATION

    def test_creation_on_mkplan_bash_absolute_path(self) -> None:
        """mkplan.bash with absolute path returns CREATION phase."""
        hook_input = _bash_mkplan_input("bash /workspace/CLAUDE/Plan/mkplan.bash 'my-feature'")
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.CREATION

    # --- Completion phase ---

    def test_completion_on_status_complete_write(self) -> None:
        """Writing PLAN.md with **Status**: Complete returns COMPLETION phase."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan 00042\n\n**Status**: Complete\n\nAll done.",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.COMPLETION

    def test_completion_on_status_completed_write(self) -> None:
        """Writing PLAN.md with **Status**: Completed returns COMPLETION phase."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Completed\n",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.COMPLETION

    def test_completion_on_status_complete_edit(self) -> None:
        """Editing PLAN.md to set **Status**: Complete returns COMPLETION phase."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="**Status**: Complete",
            old_string="**Status**: In Progress",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.COMPLETION

    # --- Progress-update phase ---

    def test_progress_on_task_status_icon_edit(self) -> None:
        """Editing PLAN.md touching task status icons returns PROGRESS phase."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ **Task 1.1**: Done",
            old_string="- [ ] ⬜ **Task 1.1**: Done",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.PROGRESS

    def test_progress_on_notes_section_edit(self) -> None:
        """Editing PLAN.md touching ## Notes & Updates returns PROGRESS phase."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="## Notes & Updates\n\n### 2026-06-23\n\n- Progress made.",
            old_string="## Notes & Updates\n",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.PROGRESS

    def test_progress_on_in_progress_icon_write(self) -> None:
        """Writing PLAN.md with 🔄 icon (but not Status Complete) returns PROGRESS."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n- [ ] \U0001f504 **Task**: In flight\n",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.PROGRESS

    # --- None (no match) ---

    def test_none_on_non_plan_file(self) -> None:
        """Non-plan file returns None."""
        hook_input = _write_input(
            "/workspace/src/main.py",
            "print('hello')",
        )
        assert _detect_lifecycle_phase(hook_input) is None

    def test_none_on_completed_directory(self) -> None:
        """PLAN.md inside Completed/ returns None."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/Completed/00042-my-plan/PLAN.md",
            "# Plan 00042\n\n**Status**: Complete\n",
        )
        assert _detect_lifecycle_phase(hook_input) is None

    def test_none_on_readme_write(self) -> None:
        """Writing CLAUDE/Plan/README.md (not a PLAN.md) returns None."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/README.md",
            "# Plans Index\n",
        )
        assert _detect_lifecycle_phase(hook_input) is None

    def test_none_on_bash_non_mkplan(self) -> None:
        """Bash command that is not mkplan.bash returns None."""
        hook_input = _bash_mkplan_input("git status")
        assert _detect_lifecycle_phase(hook_input) is None

    def test_none_on_read_tool(self) -> None:
        """Read tool event returns None (only Write/Edit/Bash matter)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"},
            "tool_output": {},
        }
        assert _detect_lifecycle_phase(hook_input) is None


# ─── matches() ───────────────────────────────────────────────────────────────


class TestMatches:
    """Tests for handler.matches()."""

    def test_matches_plan_creation_write(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns True for a new PLAN.md write."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        assert handler.matches(hook_input) is True

    def test_matches_plan_progress_edit(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns True for a progress-update edit."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Done",
            old_string="- [ ] ⬜ Not done",
        )
        assert handler.matches(hook_input) is True

    def test_matches_plan_completion_write(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns True for a completion write."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        assert handler.matches(hook_input) is True

    def test_matches_mkplan_bash(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns True for mkplan.bash invocation."""
        hook_input = _bash_mkplan_input("CLAUDE/Plan/mkplan.bash 'feature'")
        assert handler.matches(hook_input) is True

    def test_does_not_match_non_plan_write(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns False for a non-plan file write."""
        hook_input = _write_input("/workspace/src/main.py", "code")
        assert handler.matches(hook_input) is False

    def test_does_not_match_completed_directory(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns False for PLAN.md inside Completed/."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/Completed/00042-done/PLAN.md",
            "**Status**: Complete\n",
        )
        assert handler.matches(hook_input) is False

    def test_does_not_match_read_tool(self, handler: RecoveryCronAdvisorHandler) -> None:
        """matches() returns False for Read tool."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/00042/PLAN.md"},
            "tool_output": {},
        }
        assert handler.matches(hook_input) is False


# ─── handle() — per-phase guidance ───────────────────────────────────────────

_GDL_PATH = "claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor.get_data_layer"


class TestHandleCreation:
    """handle() produces correct creation-phase guidance."""

    def test_creation_returns_allow(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Creation advisory always returns ALLOW decision."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_creation_context_mentions_cron_create(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Creation guidance mentions CronCreate."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        assert result.context
        text = " ".join(result.context)
        assert "CronCreate" in text

    def test_creation_context_mentions_durable_false(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Creation guidance specifies durable:false."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        text = " ".join(result.context)
        assert "durable" in text.lower()

    def test_creation_context_says_do_not_wait(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Creation guidance instructs agent NOT to wait for the cron."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        text = " ".join(result.context).lower()
        # Must say something about not waiting
        assert "not wait" in text or "do not wait" in text or "never wait" in text

    def test_creation_context_includes_canonical_cron_prompt(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Creation guidance includes the canonical recovery-cron prompt text."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        text = " ".join(result.context)
        # The canonical prompt contains "FAILSAFE RECOVERY"
        assert "FAILSAFE RECOVERY" in text

    def test_creation_context_includes_not_heartbeat_rule(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Creation guidance reinforces the recover-not-heartbeat rule."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 0
            result = handler.handle(hook_input)
        text = " ".join(result.context).lower()
        assert "heartbeat" in text


class TestHandleProgress:
    """handle() produces correct progress-update phase guidance."""

    def test_progress_returns_allow(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress advisory returns ALLOW."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Done",
            old_string="- [ ] ⬜ Not done",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 100
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_progress_context_mentions_cronlist(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress guidance mentions CronList to verify cron is running."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Done",
            old_string="- [ ] ⬜ Not done",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 100
            result = handler.handle(hook_input)
        assert result.context
        text = " ".join(result.context)
        assert "CronList" in text

    def test_progress_context_mentions_recreate_if_missing(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Progress guidance says recreate cron if missing."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Done",
            old_string="- [ ] ⬜ Not done",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 100
            result = handler.handle(hook_input)
        text = " ".join(result.context).lower()
        assert "recreat" in text or "create" in text


class TestHandleCompletion:
    """handle() produces correct completion-phase guidance."""

    def test_completion_returns_allow(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Completion advisory returns ALLOW."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 100
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_completion_context_mentions_cron_delete(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Completion guidance mentions CronDelete."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 100
            result = handler.handle(hook_input)
        assert result.context
        text = " ".join(result.context)
        assert "CronDelete" in text


# ─── Cooldown logic ───────────────────────────────────────────────────────────


class TestCooldown:
    """Cooldown suppresses repeated progress reminders per plan."""

    def test_progress_fires_on_first_event(self, handler: RecoveryCronAdvisorHandler) -> None:
        """First progress-update for a plan produces advisory context."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Task done",
            old_string="- [ ] ⬜ Task not done",
        )
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 10
            result = handler.handle(hook_input)
        # First fire: should have context
        assert result.context

    def test_progress_suppressed_within_cooldown(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Repeated progress-updates within cooldown window return no context."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Task done",
            old_string="- [ ] ⬜ Task not done",
        )

        # First invocation — fires and records the event count
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 10
            handler.handle(hook_input)

        # Second invocation inside cooldown (count barely moved)
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 11
            result = handler.handle(hook_input)
        assert not result.context

    def test_progress_fires_again_after_cooldown_expires(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Progress-update fires again after enough events have passed."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Task done",
            old_string="- [ ] ⬜ Task not done",
        )

        # Fire at count=10
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 10
            handler.handle(hook_input)

        # Well past cooldown
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 200
            result = handler.handle(hook_input)
        assert result.context

    def test_completion_bypasses_cooldown(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Completion phase always fires even immediately after a progress advisory."""
        progress_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="- [x] ✅ Task done",
            old_string="- [ ] ⬜ Task not done",
        )
        completion_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )

        # First fire progress at count=10
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 10
            handler.handle(progress_input)

        # Immediately after (count=11), completion should still fire
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 11
            result = handler.handle(completion_input)
        assert result.context
        assert "CronDelete" in " ".join(result.context)

    def test_cooldown_is_per_plan(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Cooldown is tracked per plan folder, not globally."""
        plan_a = _edit_input(
            "/workspace/CLAUDE/Plan/00042-plan-a/PLAN.md",
            new_string="- [x] ✅ A done",
            old_string="- [ ] ⬜ A not done",
        )
        plan_b = _edit_input(
            "/workspace/CLAUDE/Plan/00043-plan-b/PLAN.md",
            new_string="- [x] ✅ B done",
            old_string="- [ ] ⬜ B not done",
        )

        # Fire plan_a at count=10 — uses cooldown for plan_a
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 10
            handler.handle(plan_a)

        # plan_b should still fire (different plan key)
        with patch(_GDL_PATH) as mock_gdl:
            mock_gdl.return_value.history.total_count = 11
            result = handler.handle(plan_b)
        assert result.context


# ─── get_claude_md() ─────────────────────────────────────────────────────────


class TestGetClaudeMd:
    """get_claude_md() documents the handler fully."""

    def test_returns_string(self, handler: RecoveryCronAdvisorHandler) -> None:
        """get_claude_md() returns a non-empty string."""
        md = handler.get_claude_md()
        assert isinstance(md, str)
        assert len(md) > 100

    def test_mentions_failsafe_recovery(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Documentation mentions FAILSAFE RECOVERY concept."""
        md = handler.get_claude_md()
        assert md is not None
        assert "failsafe" in md.lower() or "FAILSAFE" in md

    def test_mentions_not_heartbeat(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Documentation distinguishes recovery cron from heartbeat."""
        md = handler.get_claude_md()
        assert md is not None
        assert "heartbeat" in md.lower()

    def test_includes_canonical_prompt(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Documentation includes the canonical cron prompt."""
        md = handler.get_claude_md()
        assert md is not None
        assert "FAILSAFE RECOVERY CHECK" in md


# ─── get_acceptance_tests() ──────────────────────────────────────────────────


class TestGetAcceptanceTests:
    """get_acceptance_tests() covers the three lifecycle phases."""

    def test_returns_list(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Returns a non-empty list of AcceptanceTest objects."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) >= 3

    def test_covers_creation_phase(self, handler: RecoveryCronAdvisorHandler) -> None:
        """At least one test covers the creation phase."""
        tests = handler.get_acceptance_tests()
        titles = [t.title.lower() for t in tests]
        assert any("creat" in t for t in titles)

    def test_covers_progress_phase(self, handler: RecoveryCronAdvisorHandler) -> None:
        """At least one test covers the progress-update phase."""
        tests = handler.get_acceptance_tests()
        titles = [t.title.lower() for t in tests]
        assert any("progress" in t or "update" in t for t in titles)

    def test_covers_completion_phase(self, handler: RecoveryCronAdvisorHandler) -> None:
        """At least one test covers the completion phase."""
        tests = handler.get_acceptance_tests()
        titles = [t.title.lower() for t in tests]
        assert any("complet" in t for t in titles)
