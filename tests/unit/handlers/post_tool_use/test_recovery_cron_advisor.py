"""Tests for RecoveryCronAdvisorHandler - lifecycle advisory for failsafe recovery crons.

Tests cover all three lifecycle phases (creation, progress-update, completion),
cooldown suppression, completion bypassing cooldown, non-plan writes ignored,
and Completed/ directory exclusion.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    _MAX_TRACKED_PLANS,
    _PROGRESS_ADVISE_INTERVAL,
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

    def test_default_enabled_is_true(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Handler is opt-out (advisory-only) — get_default_enabled() returns True."""
        assert handler.get_default_enabled() is True


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

    def test_completion_on_lowercase_status_complete_write(self) -> None:
        """Lowercase '**status**: complete' is detected (IGNORECASE consistency)."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**status**: complete\n",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.COMPLETION

    def test_completion_on_partial_line_value_edit(self) -> None:
        """Edit replacing only the status VALUE (no prefix in new_string) is COMPLETION.

        Regression: a partial-line completion edit whose new_string is just the
        bare value 'Complete' (old_string carries the '**Status**:' prefix) was
        mis-classified as PROGRESS, so the teardown advisory never showed.
        """
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="Complete",
            old_string="**Status**: In Progress",
        )
        assert _detect_lifecycle_phase(hook_input) == LifecyclePhase.COMPLETION

    def test_status_complete_in_prose_is_not_completion(self) -> None:
        """'**Status**: Complete the migration ...' must NOT be COMPLETION.

        Regression: the unanchored pattern matched prose continuing past the
        word 'Complete', firing the teardown advisory on an active plan.  Such
        an edit carries no progress markers either, so it should be ignored.
        """
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="**Status**: Complete the migration before merging",
            old_string="**Status**: planning",
        )
        assert _detect_lifecycle_phase(hook_input) != LifecyclePhase.COMPLETION

    def test_completion_pending_prose_is_not_completion(self) -> None:
        """'Completion pending' prose must NOT be classified as COMPLETION."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\nCompletion pending review.\n",
        )
        assert _detect_lifecycle_phase(hook_input) != LifecyclePhase.COMPLETION

    def test_warning_emoji_alone_is_not_progress(self) -> None:
        """A warning emoji (⚠️) is NOT a documented task icon — not PROGRESS."""
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="⚠️ Heads up: review the API change.",
            old_string="A plain note with no markers.",
        )
        assert _detect_lifecycle_phase(hook_input) is None

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


def _progress_edit(plan_folder_path: str) -> dict[str, Any]:
    """Build a PROGRESS-classified Edit hook input for the given PLAN.md path."""
    return _edit_input(
        plan_folder_path,
        new_string="- [x] ✅ Task done",
        old_string="- [ ] ⬜ Task not done",
    )


class TestHandleCreation:
    """handle() produces correct creation-phase guidance."""

    def test_creation_returns_allow(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Creation advisory always returns ALLOW decision."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
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
        result = handler.handle(hook_input)
        text = " ".join(result.context)
        assert "durable" in text.lower()

    def test_creation_context_says_do_not_wait(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Creation guidance instructs agent NOT to wait for the cron."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
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
        result = handler.handle(hook_input)
        text = " ".join(result.context).lower()
        assert "heartbeat" in text


class TestHandleProgress:
    """handle() produces correct progress-update phase guidance."""

    def test_progress_returns_allow(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress advisory returns ALLOW."""
        hook_input = _progress_edit("/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_progress_context_mentions_cronlist(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress guidance mentions CronList to verify cron is running."""
        hook_input = _progress_edit("/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md")
        result = handler.handle(hook_input)
        assert result.context
        text = " ".join(result.context)
        assert "CronList" in text

    def test_progress_context_mentions_recreate_if_missing(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Progress guidance says recreate cron if missing."""
        hook_input = _progress_edit("/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md")
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
        result = handler.handle(hook_input)
        assert result.context
        text = " ".join(result.context)
        assert "CronDelete" in text


# ─── Progress-interval logic ───────────────────────────────────────────────────


class TestProgressInterval:
    """Per-plan progress-edit counter advises only every Nth progress edit.

    The cadence is owned by the handler and independent of global daemon
    traffic (regression for the total_count unit mismatch that re-fired the
    progress reminder on practically every PLAN.md edit).
    """

    def test_progress_fires_on_first_edit(self, handler: RecoveryCronAdvisorHandler) -> None:
        """First progress-update for a plan produces advisory context."""
        result = handler.handle(_progress_edit("/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"))
        assert result.context

    def test_progress_suppressed_within_interval(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress edits between advisories return no context (no per-edit spam)."""
        path = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        handler.handle(_progress_edit(path))  # 1st edit advises
        # The next (_PROGRESS_ADVISE_INTERVAL - 1) edits stay silent.
        for _ in range(_PROGRESS_ADVISE_INTERVAL - 1):
            result = handler.handle(_progress_edit(path))
            assert not result.context

    def test_progress_fires_again_after_interval(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Progress advisory fires again once the interval elapses."""
        path = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        # 1st edit advises; the following interval-worth of edits land us back
        # on an advise boundary.
        for _ in range(_PROGRESS_ADVISE_INTERVAL):
            handler.handle(_progress_edit(path))
        # This is the (1 + _PROGRESS_ADVISE_INTERVAL)-th edit — advises again.
        result = handler.handle(_progress_edit(path))
        assert result.context

    def test_progress_independent_of_global_traffic(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Edits to OTHER plans between two edits of one plan don't reset its cadence.

        Interleaving unrelated plan edits must not push the tracked plan past
        its interval — the count is strictly per-plan progress edits.
        """
        tracked = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        other = "/workspace/CLAUDE/Plan/00099-other/PLAN.md"
        handler.handle(_progress_edit(tracked))  # 1st tracked edit advises
        # Many unrelated edits to a different plan.
        for _ in range(_PROGRESS_ADVISE_INTERVAL * 3):
            handler.handle(_progress_edit(other))
        # The 2nd tracked edit is still inside the tracked plan's interval.
        result = handler.handle(_progress_edit(tracked))
        assert not result.context

    def test_completion_bypasses_interval(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Completion phase always fires even immediately after a progress advisory."""
        path = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        handler.handle(_progress_edit(path))  # 1st progress edit advises
        completion_input = _write_input(path, "**Status**: Complete\n")
        result = handler.handle(completion_input)
        assert result.context
        assert "CronDelete" in " ".join(result.context)

    def test_interval_is_per_plan(self, handler: RecoveryCronAdvisorHandler) -> None:
        """Each plan folder gets its own first-edit advisory."""
        result_a = handler.handle(_progress_edit("/workspace/CLAUDE/Plan/00042-plan-a/PLAN.md"))
        result_b = handler.handle(_progress_edit("/workspace/CLAUDE/Plan/00043-plan-b/PLAN.md"))
        assert result_a.context
        assert result_b.context

    def test_progress_count_map_is_bounded(self, handler: RecoveryCronAdvisorHandler) -> None:
        """The per-plan progress-count map never exceeds _MAX_TRACKED_PLANS entries."""
        for i in range(_MAX_TRACKED_PLANS + 50):
            handler.handle(_progress_edit(f"/workspace/CLAUDE/Plan/{i:05d}-plan/PLAN.md"))
        # Access the bounded map via the public behaviour: it must be capped.
        assert len(handler._progress_counts) <= _MAX_TRACKED_PLANS


class TestPhaseCacheContract:
    """matches() caches the phase; handle() reuses it without re-detecting."""

    def test_matches_then_handle_uses_cached_phase(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """A matches()->handle() pair on a creation event advises correctly."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.context
        assert "CronCreate" in " ".join(result.context)

    def test_handle_without_matches_still_detects(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """handle() called directly (no prior matches) re-detects the phase."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        result = handler.handle(hook_input)
        assert "CronDelete" in " ".join(result.context)

    def test_stale_cache_not_reused_across_events(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """A non-matching event after a matching one is not mis-handled via stale cache."""
        completion = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        non_plan = _write_input("/workspace/src/main.py", "code")
        assert handler.matches(completion) is True
        # matches() returned False for the non-plan event -> cache cleared.
        assert handler.matches(non_plan) is False
        result = handler.handle(non_plan)
        assert not result.context


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
