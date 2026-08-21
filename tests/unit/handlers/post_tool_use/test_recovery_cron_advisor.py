"""Tests for RecoveryCronAdvisorHandler - lifecycle advisory for failsafe recovery crons.

Tests cover all three lifecycle phases (creation, progress-update, completion),
cooldown suppression, completion bypassing cooldown, non-plan writes ignored,
and Completed/ directory exclusion.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    _CREATION_GUIDANCE,
    _MAX_TRACKED_PLANS,
    _PROGRESS_ADVISE_INTERVAL,
    _PROGRESS_GUIDANCE,
    LifecyclePhase,
    RecoveryCronAdvisorHandler,
    _detect_lifecycle_phase,
)

_RETIRED_SECTION = "Notes & Updates"


class TestCronIdDestinationIsJournal:
    """The cron ID belongs in JOURNAL/, never in PLAN.md (Plan 00190).

    This handler was the ONLY injected instruction in the daemon telling an
    agent to write into ``## Notes & Updates`` -- a section retired in favour
    of ``JOURNAL/``. It directly contradicted CLAUDE/PlanWorkflow.md, which
    says record the cron ID in the plan's JOURNAL. An injected instruction
    beats a doc an agent may never open, so this was actively teaching the
    anti-pattern.
    """

    def test_creation_guidance_names_the_journal(self) -> None:
        """Runtime creation guidance directs the cron ID to the journal."""
        assert "JOURNAL" in _CREATION_GUIDANCE

    def test_creation_guidance_does_not_name_retired_section(self) -> None:
        """Runtime creation guidance must not resurrect the retired section."""
        assert _RETIRED_SECTION not in _CREATION_GUIDANCE

    def test_claude_md_does_not_advertise_retired_section(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Injected CLAUDE.md guidance must not name the retired section.

        ``get_claude_md()`` is rendered into CLAUDE.md's generated block, so
        any mention there is resident in every session.
        """
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert _RETIRED_SECTION not in guidance

    def test_claude_md_directs_cron_id_to_journal(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Injected guidance names JOURNAL/ as the cron ID's destination."""
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "JOURNAL" in guidance


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

    def test_notes_section_edit_alone_is_not_progress(self) -> None:
        """A dated note appended to PLAN.md is NOT a progress signal (Plan 00190).

        ``## Notes & Updates`` is the RETIRED location for the blow-by-blow
        stream, subsumed into ``JOURNAL/``. Treating an edit to it as
        first-class "legitimate progress" rewarded the exact anti-pattern the
        plan/journal separation exists to remove. Real progress edits touch a
        task-status icon by the plan template's own grammar, so nothing of
        value is lost.
        """
        hook_input = _edit_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            new_string="## Notes & Updates\n\n### 2026-06-23\n\n- Progress made.",
            old_string="## Notes & Updates\n",
        )
        assert _detect_lifecycle_phase(hook_input) != LifecyclePhase.PROGRESS

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


class TestExactlyOneCronEverExists:
    """The advisory must never produce a SECOND recovery cron.

    Dogfooding report: a session that created two plans ended up with two
    identical hourly crons on the same minute, both firing on the same session.
    The creation guidance said "create a cron NOW" with no instruction to look
    first, even though the module docstring (Decision D2) already claimed "the
    agent uses CronList to avoid duplicate creates" — the claim was never
    implemented in the text the agent actually reads.

    One cron is sufficient by construction: the canonical prompt is
    plan-agnostic ("your most recent work on the active plan/task"), so it
    covers every plan in the session. A second one only doubles the wake-ups.
    """

    def test_creation_guidance_says_to_list_before_creating(self) -> None:
        """CronList must be step one, not an afterthought in a later phase."""
        assert "CronList" in _CREATION_GUIDANCE, (
            "Creation guidance must tell the agent to CHECK for an existing cron "
            "before creating one, or a second plan in the same session stacks a "
            "duplicate."
        )

    def test_creation_guidance_makes_creation_conditional(self) -> None:
        """The create step must be gated, not unconditional."""
        lowered = _CREATION_GUIDANCE.lower()
        assert "only if" in lowered or "if none" in lowered or "if no " in lowered, (
            "Creation guidance must make CronCreate conditional on none existing. "
            f"Guidance was:\n{_CREATION_GUIDANCE}"
        )

    def test_creation_guidance_says_reuse_an_existing_cron(self) -> None:
        """An existing cron is the answer, not something to work around."""
        lowered = _CREATION_GUIDANCE.lower()
        assert "reuse" in lowered or "keep" in lowered, (
            "Creation guidance must say to REUSE the cron already running "
            "(recording its id for this plan) rather than create another."
        )

    def test_creation_guidance_states_the_one_cron_invariant(self) -> None:
        """State the invariant, so it survives future edits to the wording."""
        lowered = _CREATION_GUIDANCE.lower()
        assert "exactly one" in lowered or "only one" in lowered, (
            "Creation guidance must state the invariant — exactly ONE recovery "
            "cron per session — so a later reword cannot quietly drop it."
        )

    def test_progress_guidance_says_to_remove_duplicates(self) -> None:
        """Verifying the cron must also mean collapsing extras to one.

        The progress phase is the only place that runs repeatedly, so it is
        where an already-stacked session gets repaired. Without this it would
        report "still running" and leave both crons in place.
        """
        lowered = _PROGRESS_GUIDANCE.lower()
        assert "CronDelete" in _PROGRESS_GUIDANCE, (
            "Progress guidance must tell the agent to CronDelete extras when "
            f"more than one recovery cron is listed. Guidance was:\n{_PROGRESS_GUIDANCE}"
        )
        assert (
            "more than one" in lowered or "duplicate" in lowered
        ), "Progress guidance must name the duplicate case explicitly."

    def test_claude_md_table_matches_the_guidance(self) -> None:
        """Resident guidance must not contradict the injected advisory.

        `get_claude_md()` renders the same lifecycle table into CLAUDE.md, where
        an agent reads it every session. If it still says "create a cron now"
        while the advisory says "check first", the resident copy wins by being
        read earlier.
        """
        claude_md = RecoveryCronAdvisorHandler().get_claude_md()
        assert claude_md is not None
        assert "CronList" in claude_md, (
            "The CLAUDE.md lifecycle table must carry the same check-first "
            "instruction as the creation advisory."
        )
        lowered = claude_md.lower()
        assert (
            "exactly one" in lowered or "only one" in lowered
        ), "The CLAUDE.md table must state the one-cron-per-session invariant."


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

    def test_completion_warns_about_protection_gap_before_delete(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Completion guidance must WARN that deleting leaves the live session
        unprotected, and condition deletion on no further session work.

        Regression (Plan 00142 dogfooding): unconditionally advising CronDelete on
        plan completion left a still-live, rate-limit-exposed session with zero
        recovery coverage. Completion must warn first and require certainty that
        no further work remains before deleting.
        """
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        result = handler.handle(hook_input)
        text = " ".join(result.context)
        lowered = text.lower()
        # Warns about the unprotected gap …
        assert "keep" in lowered
        assert "session" in lowered
        assert ("no recovery" in lowered) or ("unprotected" in lowered) or ("coverage" in lowered)
        # … and conditions the delete (does not advise it unconditionally).
        assert ("only" in lowered) or ("certain" in lowered)


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


class TestCreationAndCompletionFireOncePerPlan:
    """CREATION and COMPLETION are one-shot per plan, unlike PROGRESS's interval.

    Regression: prior to this fix, both phases fired unconditionally on EVERY
    matching event -- a repeated Write to a PLAN.md still lacking progress
    icons re-injected the full ``_CREATION_GUIDANCE`` (embedding the entire
    canonical cron prompt) every time, and re-saving an already-Complete plan
    re-injected ``_COMPLETION_GUIDANCE`` every time. Both are state
    TRANSITIONS: the meaningful event is the first one for a given plan
    folder -- a second creation, or a re-save of an already-complete plan,
    carries no new information. This is deliberately NOT the PROGRESS rule
    (every Nth edit), which tracks ongoing activity rather than a transition.
    """

    def test_creation_fires_on_first_write(self, handler: RecoveryCronAdvisorHandler) -> None:
        """First CREATION event for a plan folder produces advisory context."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "# Plan\n\n**Status**: Not Started\n",
        )
        result = handler.handle(hook_input)
        assert result.context

    def test_creation_suppressed_on_second_write_same_plan(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """A second CREATION-classified write to the SAME plan is silent."""
        path = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        content = "# Plan\n\n**Status**: Not Started\n"
        handler.handle(_write_input(path, content))  # 1st write advises
        result = handler.handle(_write_input(path, content))  # 2nd write silent
        assert not result.context

    def test_creation_fires_independently_per_plan(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """A DIFFERENT plan folder still gets its own first creation advisory."""
        content = "# Plan\n\n**Status**: Not Started\n"
        handler.handle(_write_input("/workspace/CLAUDE/Plan/00042-plan-a/PLAN.md", content))
        result = handler.handle(
            _write_input("/workspace/CLAUDE/Plan/00043-plan-b/PLAN.md", content)
        )
        assert result.context

    def test_completion_fires_on_first_write(self, handler: RecoveryCronAdvisorHandler) -> None:
        """First COMPLETION event for a plan folder produces advisory context."""
        hook_input = _write_input(
            "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md",
            "**Status**: Complete\n",
        )
        result = handler.handle(hook_input)
        assert result.context

    def test_completion_suppressed_on_second_write_same_plan(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """Re-saving an already-Complete plan is silent the second time."""
        path = "/workspace/CLAUDE/Plan/00042-my-plan/PLAN.md"
        content = "**Status**: Complete\n"
        handler.handle(_write_input(path, content))  # 1st write advises
        result = handler.handle(_write_input(path, content))  # 2nd write silent
        assert not result.context

    def test_completion_fires_independently_per_plan(
        self, handler: RecoveryCronAdvisorHandler
    ) -> None:
        """A DIFFERENT plan folder still gets its own first completion advisory."""
        handler.handle(
            _write_input("/workspace/CLAUDE/Plan/00042-plan-a/PLAN.md", "**Status**: Complete\n")
        )
        result = handler.handle(
            _write_input("/workspace/CLAUDE/Plan/00043-plan-b/PLAN.md", "**Status**: Complete\n")
        )
        assert result.context

    def test_creation_seen_map_is_bounded(self, handler: RecoveryCronAdvisorHandler) -> None:
        """The per-plan creation-seen map never exceeds _MAX_TRACKED_PLANS entries."""
        content = "# Plan\n\n**Status**: Not Started\n"
        for i in range(_MAX_TRACKED_PLANS + 50):
            handler.handle(_write_input(f"/workspace/CLAUDE/Plan/{i:05d}-plan/PLAN.md", content))
        assert len(handler._creation_seen) <= _MAX_TRACKED_PLANS

    def test_completion_seen_map_is_bounded(self, handler: RecoveryCronAdvisorHandler) -> None:
        """The per-plan completion-seen map never exceeds _MAX_TRACKED_PLANS entries."""
        content = "**Status**: Complete\n"
        for i in range(_MAX_TRACKED_PLANS + 50):
            handler.handle(_write_input(f"/workspace/CLAUDE/Plan/{i:05d}-plan/PLAN.md", content))
        assert len(handler._completion_seen) <= _MAX_TRACKED_PLANS


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
