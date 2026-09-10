"""Tests for PlanCloseApprovalHandler (Plan 00367).

With ``plan_workflow.close_requires_human_approval`` true, an agent's
Write/Edit that flips a PLAN.md ``**Status**`` to a terminal state (Complete,
Cancelled, Superseded) is denied unless a human has recorded a one-shot
approval for that plan. With the key false (the shipped default) the handler
never matches, so a fully completed plan closes as before.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, TestType
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_close_approval import (
    PlanCloseApprovalHandler,
)
from claude_code_hooks_daemon.plan_qa.close_approval import (
    approval_marker_path,
    record_approval,
)

_PLAN_DIR_REL = "CLAUDE/Plan"

_IN_PROGRESS = (
    "# Plan 00042: Widget\n\n"
    "**Status**: In Progress\n"
    "**Created**: 2026-07-01\n\n"
    "- [x] ✅ **Task 1.1**: x\n"
)
_COMPLETE = _IN_PROGRESS.replace("**Status**: In Progress", "**Status**: Complete (2026-09-10)")
_CANCELLED = _IN_PROGRESS.replace("**Status**: In Progress", "**Status**: Cancelled")
_SUPERSEDED = _IN_PROGRESS.replace("**Status**: In Progress", "**Status**: Superseded")


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def untracked(tmp_path: Path) -> Iterator[Path]:
    untracked_dir = tmp_path / "untracked"
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.plan_close_approval."
        "ProjectContext.daemon_untracked_dir"
    )
    with patch(target, return_value=untracked_dir):
        yield untracked_dir


@pytest.fixture
def plan_doc(tmp_path: Path) -> Path:
    folder = tmp_path / _PLAN_DIR_REL / "00042-widget"
    folder.mkdir(parents=True)
    doc = folder / "PLAN.md"
    doc.write_text(_IN_PROGRESS, encoding="utf-8")
    return doc


def _handler(*, gate_on: bool = True, plan_dir: str | None = _PLAN_DIR_REL) -> Any:
    handler = PlanCloseApprovalHandler()
    handler._track_plans_in_project = plan_dir
    handler._close_requires_human_approval = gate_on
    return handler


def _write(path: Path, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def _edit(path: Path, old: str, new: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _flip(path: Path, to: str = "Complete (2026-09-10)") -> dict[str, Any]:
    return _edit(path, "**Status**: In Progress", f"**Status**: {to}")


class TestIdentity:
    def test_identity(self) -> None:
        handler = PlanCloseApprovalHandler()
        assert handler.handler_id == HandlerID.PLAN_CLOSE_APPROVAL
        assert handler.name == "plan-close-approval"
        assert handler.priority == Priority.PLAN_CLOSE_APPROVAL
        assert HandlerTag.PLANNING in handler.tags
        assert HandlerTag.BLOCKING in handler.tags

    def test_rule_is_registered(self) -> None:
        rules = PlanCloseApprovalHandler().get_rules()
        assert [rule.rule_id for rule in rules] == [RuleID.PLAN_CLOSE_APPROVAL]
        assert "close_requires_human_approval" in rules[0].verbose

    def test_claude_md_names_the_key_and_the_command(self) -> None:
        guidance = PlanCloseApprovalHandler().get_claude_md()
        assert guidance is not None
        assert "plan_workflow.close_requires_human_approval" in guidance
        assert "approve-plan-close" in guidance

    def test_acceptance_tests_cover_both_branches(self) -> None:
        tests = PlanCloseApprovalHandler().get_acceptance_tests()
        decisions = {test.expected_decision for test in tests}
        assert decisions == {Decision.DENY, Decision.ALLOW}
        assert all(test.test_type == TestType.BLOCKING for test in tests)


class TestMatches:
    def test_default_off_never_matches(self, plan_doc: Path) -> None:
        assert _handler(gate_on=False).matches(_flip(plan_doc)) is False

    def test_no_plan_workflow_never_matches(self, plan_doc: Path) -> None:
        assert _handler(plan_dir=None).matches(_flip(plan_doc)) is False

    def test_matches_a_plan_doc_write_and_edit(self, plan_doc: Path) -> None:
        handler = _handler()
        assert handler.matches(_flip(plan_doc)) is True
        assert handler.matches(_write(plan_doc, _COMPLETE)) is True

    def test_ignores_other_files_under_the_plan_directory(self, plan_doc: Path) -> None:
        journal = plan_doc.parent / "JOURNAL" / "00042-Journal-26-09-10.md"
        assert _handler().matches(_write(journal, "## 09:00 · action · — x\n")) is False

    def test_ignores_a_plan_doc_outside_the_plan_directory(self, tmp_path: Path) -> None:
        other = tmp_path / "docs" / "00042-widget" / "PLAN.md"
        assert _handler().matches(_write(other, _COMPLETE)) is False

    def test_ignores_bash(self, plan_doc: Path) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": f"cat {plan_doc}"}}
        assert _handler().matches(payload) is False


class TestGate:
    @pytest.mark.parametrize("terminal", ["Complete (2026-09-10)", "Cancelled", "Superseded"])
    def test_flip_to_terminal_is_denied_without_approval(
        self, plan_doc: Path, untracked: Path, terminal: str
    ) -> None:
        result = _handler().handle(_flip(plan_doc, terminal))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "plan_workflow.close_requires_human_approval" in result.reason
        assert "approve-plan-close 00042" in result.reason
        assert RuleID.PLAN_CLOSE_APPROVAL in result.reason

    def test_write_of_a_terminal_status_is_denied_too(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        result = _handler().handle(_write(plan_doc, _CANCELLED))
        assert result.decision == Decision.DENY

    def test_a_brand_new_terminal_plan_doc_is_denied(self, tmp_path: Path, untracked: Path) -> None:
        fresh = tmp_path / _PLAN_DIR_REL / "00099-fresh" / "PLAN.md"
        result = _handler().handle(_write(fresh, _SUPERSEDED))
        assert result.decision == Decision.DENY
        assert "approve-plan-close 00099" in result.reason

    def test_non_terminal_flip_is_allowed(self, plan_doc: Path, untracked: Path) -> None:
        result = _handler().handle(_flip(plan_doc, "Blocked"))
        assert result.decision == Decision.ALLOW

    def test_edit_that_keeps_the_status_is_allowed(self, plan_doc: Path, untracked: Path) -> None:
        result = _handler().handle(
            _edit(plan_doc, "- [x] ✅ **Task 1.1**: x", "- [x] ✅ **Task 1.1**: y")
        )
        assert result.decision == Decision.ALLOW

    def test_editing_an_already_terminal_plan_is_allowed(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        """The gate is on the FLIP: a plan a human already closed stays editable."""
        plan_doc.write_text(_COMPLETE, encoding="utf-8")
        result = _handler().handle(_edit(plan_doc, "x\n", "x (archived)\n"))
        assert result.decision == Decision.ALLOW

    def test_switching_between_terminal_states_is_a_flip(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        plan_doc.write_text(_CANCELLED, encoding="utf-8")
        result = _handler().handle(_edit(plan_doc, "**Status**: Cancelled", "**Status**: Complete"))
        assert result.decision == Decision.DENY

    def test_edit_with_unmatched_old_string_is_allowed(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        """The tool call fails on its own; there is no would-be content to judge."""
        result = _handler().handle(_edit(plan_doc, "not in the file", "**Status**: Complete"))
        assert result.decision == Decision.ALLOW

    def test_approval_marker_lets_the_flip_through_once(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        record_approval(untracked, 42)
        first = _handler().handle(_flip(plan_doc))
        assert first.decision == Decision.ALLOW
        assert any("approval" in line for line in first.context)
        assert not approval_marker_path(untracked, 42).exists()

        second = _handler().handle(_flip(plan_doc))
        assert second.decision == Decision.DENY

    def test_approval_for_another_plan_does_not_count(
        self, plan_doc: Path, untracked: Path
    ) -> None:
        record_approval(untracked, 43)
        assert _handler().handle(_flip(plan_doc)).decision == Decision.DENY
        assert approval_marker_path(untracked, 43).exists()

    def test_deny_reason_is_terse_after_first_fire(self, plan_doc: Path, untracked: Path) -> None:
        payload = _flip(plan_doc)
        payload["transcript_path"] = "/tmp/transcript.jsonl"
        handler = _handler()
        first = handler.handle(payload)
        second = handler.handle(payload)
        assert first.reason is not None and second.reason is not None
        assert len(second.reason) < len(first.reason)
        assert "approve-plan-close 00042" in second.reason
