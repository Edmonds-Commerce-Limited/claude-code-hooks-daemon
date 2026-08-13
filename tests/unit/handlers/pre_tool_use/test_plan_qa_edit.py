"""Tests for PlanQaEditHandler (Plan 00144, Task 3.2).

Stage 1 edit-time lint: Write/Edit of a PLAN.md under the plan directory is
checked against the edit-stage plan QA catalogue on the WOULD-BE content
(for Edit, old/new applied to the current file). Blocks new-material
violations in ``edit_mode: block``; advises otherwise.
"""

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit import PlanQaEditHandler

_PLAN_DIR_REL = "CLAUDE/Plan"

_VALID_PLAN = (
    "# Plan 00042: Widget\n\n"
    "**Status**: In Progress\n"
    "**Created**: 2026-07-01\n"
    "**Owner**: joseph\n"
    "**Priority**: Medium\n\n"
    "- [ ] ⬜ **Task 1.1**: x\n"
)
_NO_STATUS_PLAN = "# Plan 00042: Widget\n\n## Progress\n\nno header here\n"


def _handler(
    plan_dir_rel: str | None = _PLAN_DIR_REL,
    policy: PlanWorkflowQaConfig | None = None,
) -> PlanQaEditHandler:
    handler = PlanQaEditHandler()
    handler._track_plans_in_project = plan_dir_rel
    handler._plan_qa = policy if policy is not None else PlanWorkflowQaConfig()
    return handler


def _write_input(file_path: Path, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(file_path), "content": content},
    }


def _edit_input(
    file_path: Path,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(file_path),
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
    }


def _patched_root(root: Path) -> Any:
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit." "ProjectContext.project_root"
    )
    return patch(target, return_value=root)


class TestInit:
    def test_identity(self) -> None:
        handler = PlanQaEditHandler()
        assert handler.name == "plan-qa-edit"
        assert handler.terminal is False
        assert "planning" in handler.tags


class TestMatches:
    def test_matches_write_to_plan_md(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        assert _handler().matches(_write_input(target, _VALID_PLAN)) is True

    def test_matches_edit_to_plan_md(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        assert _handler().matches(_edit_input(target, "a", "b")) is True

    def test_ignores_other_tools(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": f"cat {target}"}}
        assert _handler().matches(hook_input) is False

    def test_ignores_non_plan_md(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "notes.md"
        assert _handler().matches(_write_input(target, "x")) is False

    def test_ignores_plan_md_outside_plan_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "PLAN.md"
        assert _handler().matches(_write_input(target, "x")) is False

    def test_skips_without_policy(self, tmp_path: Path) -> None:
        handler = PlanQaEditHandler()
        handler._track_plans_in_project = _PLAN_DIR_REL
        handler._plan_qa = None
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        assert handler.matches(_write_input(target, "x")) is False

    def test_skips_when_qa_disabled(self, tmp_path: Path) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(enabled=False))
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        assert handler.matches(_write_input(target, "x")) is False

    def test_skips_when_edit_mode_off(self, tmp_path: Path) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(edit_mode="off"))
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        assert handler.matches(_write_input(target, "x")) is False

    def test_matches_journal_dayfile(self, tmp_path: Path) -> None:
        # Plan 00163: journal day-files are lintable plan artifacts too.
        target = tmp_path / _PLAN_DIR_REL / "00163-x" / "JOURNAL" / "00163-Journal-26-07-14.md"
        assert _handler().matches(_write_input(target, "x")) is True

    def test_journal_dayfile_skipped_when_journal_disabled(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.config.models import PlanWorkflowQaJournalConfig

        policy = PlanWorkflowQaConfig(journal=PlanWorkflowQaJournalConfig(enabled=False))
        target = tmp_path / _PLAN_DIR_REL / "00163-x" / "JOURNAL" / "00163-Journal-26-07-14.md"
        assert _handler(policy=policy).matches(_write_input(target, "x")) is False

    def test_journal_dayfile_skipped_when_journal_mode_off(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.config.models import PlanWorkflowQaJournalConfig

        policy = PlanWorkflowQaConfig(journal=PlanWorkflowQaJournalConfig(mode="off"))
        target = tmp_path / _PLAN_DIR_REL / "00163-x" / "JOURNAL" / "00163-Journal-26-07-14.md"
        assert _handler(policy=policy).matches(_write_input(target, "x")) is False

    def test_matches_the_plan_index_readme(self, tmp_path: Path) -> None:
        # Plan 00218: the index has a shape rule (index-row-length) and so needs
        # the fast loop too. It is the ONLY README the handler admits.
        target = tmp_path / _PLAN_DIR_REL / "README.md"
        assert _handler().matches(_write_input(target, "x")) is True

    def test_ignores_readme_inside_a_plan_folder(self, tmp_path: Path) -> None:
        """A README in a plan folder is a supporting doc, not the index."""
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "README.md"
        assert _handler().matches(_write_input(target, "x")) is False

    def test_ignores_readme_outside_the_plan_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "README.md"
        assert _handler().matches(_write_input(target, "x")) is False


class TestHandleJournal:
    """Plan 00163: journal day-file edit linting through the handler."""

    def _journal_file(self, tmp_path: Path, name: str | None = None) -> Path:
        # Default to TODAY's date so the journal-dayfile-naming check (which
        # only accepts today/yesterday) never trips on a stale hardcoded date —
        # a hardcoded date here is a time-bomb that fails the day after it ages
        # out of the tolerance window.
        if name is None:
            name = f"00163-Journal-{date.today():%y-%m-%d}.md"
        journal = tmp_path / _PLAN_DIR_REL / "00163-x" / "JOURNAL"
        journal.mkdir(parents=True)
        return journal / name

    def test_journal_block_mode_is_subordinate_to_edit_mode(self, tmp_path: Path) -> None:
        """`journal.mode: block` does NOT deny unless `edit_mode` is also block.

        Plan 00190: the docs promised `journal-dayfile-naming` "may ratchet to
        block via mode: block". That promise is CONDITIONAL — the handler
        re-gates every blocker on `edit_mode` (plan_qa_edit.py:121), so a
        project on the documented `edit_mode: warn` rollout posture that sets
        `journal.mode: block` gets advisories while believing naming is
        enforced.

        This test pins the ACTUAL behaviour so the documented claim can be
        corrected against something executable rather than a reading of it.
        """
        target = self._journal_file(tmp_path, "my-journal.md")
        policy = PlanWorkflowQaConfig(edit_mode="warn")
        policy.journal.mode = "block"

        with _patched_root(tmp_path):
            result = _handler(policy=policy).handle(_write_input(target, "# journal\n"))

        assert result.decision == Decision.ALLOW, "edit_mode: warn downgrades the journal block"
        assert "journal-dayfile-naming" in " ".join(result.context)

    def test_journal_checks_are_disabled_entirely_by_edit_mode_off(self, tmp_path: Path) -> None:
        """`edit_mode: off` silences journal checks even with journal.enabled.

        The sub-block cannot keep itself alive: `matches()` returns False on
        `edit_mode: off` (plan_qa_edit.py:71) before journal config is ever
        consulted.
        """
        target = self._journal_file(tmp_path, "my-journal.md")
        policy = PlanWorkflowQaConfig(edit_mode="off")
        policy.journal.enabled = True
        policy.journal.mode = "block"

        assert _handler(policy=policy).matches(_write_input(target, "# journal\n")) is False

    def test_new_journal_with_bad_name_advises(self, tmp_path: Path) -> None:
        target = self._journal_file(tmp_path, "my-journal.md")
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, "# journal\n"))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "journal-dayfile-naming" in " ".join(result.context)

    def test_pure_append_is_silent(self, tmp_path: Path) -> None:
        target = self._journal_file(tmp_path)
        before = "# Journal\n\n## 09:00 · action · —\n\nfirst\n"
        target.write_text(before)
        after = before + "\n## 10:00 · finding · —\n\nsecond\n"
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, after))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_history_rewrite_advises(self, tmp_path: Path) -> None:
        target = self._journal_file(tmp_path)
        before = "# Journal\n\n## 09:00 · action · —\n\nfirst\n"
        target.write_text(before)
        rewritten = before.replace("first", "EDITED first")
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, rewritten))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "journal-append-only" in " ".join(result.context)


class TestHandleWrite:
    def test_valid_new_plan_allows_silently(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, _VALID_PLAN))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_new_plan_without_status_is_denied(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, _NO_STATUS_PLAN))
        assert result.decision == Decision.DENY
        assert "status-line-present" in (result.reason or "")
        assert "**Status**:" in (result.reason or "")

    def test_warn_mode_downgrades_block_to_advisory(self, tmp_path: Path) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(edit_mode="warn"))
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path):
            result = handler.handle(_write_input(target, _NO_STATUS_PLAN))
        assert result.decision == Decision.ALLOW
        assert "status-line-present" in "\n".join(result.context)

    def test_legacy_allowlisted_plan_advises(self, tmp_path: Path) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(legacy_plan_allowlist=[42]))
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(_NO_STATUS_PLAN)
        with _patched_root(tmp_path):
            result = handler.handle(_write_input(target, _NO_STATUS_PLAN))
        assert result.decision == Decision.ALLOW
        assert "status-line-present" in "\n".join(result.context)

    def test_terminal_status_in_root_advises_placement(self, tmp_path: Path) -> None:
        content = _VALID_PLAN.replace("**Status**: In Progress", "**Status**: Complete")
        content = content.replace("- [ ] ⬜", "- [x] ✅")
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, content))
        assert result.decision == Decision.ALLOW
        assert "terminal-placement-hint" in "\n".join(result.context)


class TestHandlePlanIndex:
    """Plan 00218: the index row-length rule, end to end through the handler."""

    @staticmethod
    def _index(row_length: int) -> str:
        return "# Plans Index\n\n## Active Plans\n\n- " + "x" * row_length + "\n"

    def test_long_row_written_into_the_index_is_denied(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.plan_qa.types import DEFAULT_INDEX_ROW_MAX_CHARS

        target = tmp_path / _PLAN_DIR_REL / "README.md"
        with _patched_root(tmp_path):
            result = _handler().handle(
                _write_input(target, self._index(DEFAULT_INDEX_ROW_MAX_CHARS + 1))
            )
        assert result.decision == Decision.DENY
        assert "index-row-length" in (result.reason or "")

    def test_index_within_the_limit_allows_silently(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.plan_qa.types import DEFAULT_INDEX_ROW_MAX_CHARS

        target = tmp_path / _PLAN_DIR_REL / "README.md"
        with _patched_root(tmp_path):
            result = _handler().handle(
                _write_input(target, self._index(DEFAULT_INDEX_ROW_MAX_CHARS - 10))
            )
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_plan_document_rules_do_not_fire_on_the_index(self, tmp_path: Path) -> None:
        """Widening the handler gate must not let PLAN.md rules onto a README.

        The index has no ``**Status**:`` line and never will; if
        ``status-line-present`` reached it, every index edit would be denied.
        """
        target = tmp_path / _PLAN_DIR_REL / "README.md"
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, "# Plans Index\n\nno status here\n"))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestHandleEdit:
    def test_edit_applies_old_new_to_current_content(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(_VALID_PLAN)
        # This edit REMOVES the status line — the would-be content violates.
        hook_input = _edit_input(target, "**Status**: In Progress\n", "")
        with _patched_root(tmp_path):
            result = _handler().handle(hook_input)
        assert result.decision == Decision.DENY
        assert "status-line-present" in (result.reason or "")

    def test_benign_edit_allows(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(_VALID_PLAN)
        hook_input = _edit_input(target, "Task 1.1", "Task 1.1 (renamed)")
        with _patched_root(tmp_path):
            result = _handler().handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_edit_on_missing_file_allows(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        hook_input = _edit_input(target, "a", "b")
        with _patched_root(tmp_path):
            result = _handler().handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_edit_with_unmatched_old_string_allows(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(_VALID_PLAN)
        hook_input = _edit_input(target, "NOT PRESENT ANYWHERE", "b")
        with _patched_root(tmp_path):
            result = _handler().handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_replace_all_is_honoured(self, tmp_path: Path) -> None:
        content = "# Plan 00042: W\n\n**Status**: In Progress\n\n- [ ] x1\n- [ ] x1\n"
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(content)
        hook_input = _edit_input(target, "- [ ] x1", "- [x] x1", replace_all=True)
        with _patched_root(tmp_path):
            result = _handler().handle(hook_input)
        # Both boxes ticked while header stays In Progress → coherence block.
        assert result.decision == Decision.DENY
        assert "header-body-coherence" in (result.reason or "")


class TestGuidance:
    def test_get_claude_md_documents_lint(self) -> None:
        text = PlanQaEditHandler().get_claude_md()
        assert text is not None
        assert "**Status**:" in text

    def test_get_claude_md_documents_journal_today_only_block(self) -> None:
        # Plan 00197: the resident guidance must tell agents that a stale
        # (including yesterday-dated) journal day-file edit is blocked.
        text = PlanQaEditHandler().get_claude_md()
        assert text is not None
        assert "journal-dayfile-is-today" in text
        assert "today_only_mode" in text

    def test_acceptance_tests_defined(self) -> None:
        assert len(PlanQaEditHandler().get_acceptance_tests()) >= 2

    def test_default_enabled(self) -> None:
        assert PlanQaEditHandler().get_default_enabled() is True


class TestCounterAllocationOnNewPlan:
    """Plan 00237 Task 4.1: the DIRECT-path plan-counter writer lives here now.

    It moved off ``validate_plan_number``, which is being deleted. The counter
    is not just how the next number is chosen — it is the reference value the
    commit-stage ``counter-sanity`` check compares a staged plan folder
    against, and that check only READS. So a plan created by hand with no
    writer on this path leaves the counter behind, and the NEXT plan is
    blocked at commit for drift the missing writer caused.

    These tests pin the WIRING (is it called, with what, and does a failure
    stay non-fatal). The window rule itself is pinned in
    ``tests/unit/handlers/utils/test_plan_numbering.py``.
    """

    _RECORDER = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit." "record_new_plan_document"
    )

    def test_creating_a_plan_document_records_the_allocation(self, tmp_path: Path) -> None:
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path), patch(self._RECORDER) as recorder:
            _handler().handle(_write_input(target, _VALID_PLAN))

        recorder.assert_called_once_with(target, _PLAN_DIR_REL, tmp_path)

    def test_editing_an_existing_plan_does_not_record(self, tmp_path: Path) -> None:
        """Only CREATION is an allocation.

        Recording on every PLAN.md write would be harmless arithmetic (the
        counter is a max) but it would spend a git subprocess on every edit
        and blur what the counter records.
        """
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        target.parent.mkdir(parents=True)
        target.write_text(_VALID_PLAN)

        with _patched_root(tmp_path), patch(self._RECORDER) as recorder:
            _handler().handle(_write_input(target, _VALID_PLAN))

        recorder.assert_not_called()

    def test_a_counter_write_failure_never_blocks_the_plan(self, tmp_path: Path) -> None:
        """FAIL-SAFE. Losing the counter is recoverable — it self-heals from a
        filesystem scan on the next read. Losing the agent's plan document
        because git config misbehaved is not.
        """
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "PLAN.md"
        with _patched_root(tmp_path), patch(self._RECORDER, side_effect=OSError("git gone")):
            result = _handler().handle(_write_input(target, _VALID_PLAN))

        assert result.decision == Decision.ALLOW

    def test_a_journal_write_is_delegated_unchanged(self, tmp_path: Path) -> None:
        """The handler also lints journal day-files and plan-index READMEs.

        It does NOT pre-filter those — it hands the path over and lets the
        helper decide, because "is this a new plan allocation?" is one rule
        with one home. ``test_plan_numbering.py`` proves the helper records
        nothing for a non-``PLAN.md`` path; duplicating that judgement here
        would give the rule two homes that can disagree.
        """
        target = tmp_path / _PLAN_DIR_REL / "00042-widget" / "JOURNAL" / "00042-Journal-26-08-13.md"
        with _patched_root(tmp_path), patch(self._RECORDER) as recorder:
            _handler().handle(_write_input(target, "## 10:00 · note\n"))

        recorder.assert_called_once_with(target, _PLAN_DIR_REL, tmp_path)
