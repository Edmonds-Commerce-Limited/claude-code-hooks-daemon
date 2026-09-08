"""A plan may not flip to Complete until its holding-area criterion is present.

Project-only (this repository's plan tree and its `UNRELEASED/` holding area);
deliberately NOT a daemon handler. The rule it enforces is step 0 of the Plan
Completion Checklist in `CLAUDE/core/PlanWorkflow.core.md`.
"""

from pathlib import Path
from typing import Any

import pytest
from plan_done_requires_holding_area import PlanDoneRequiresHoldingAreaHandler

from claude_code_hooks_daemon.core.hook_result import Decision

_ACTIVE = "CLAUDE/Plan/00999-example/PLAN.md"
_ARCHIVED = "CLAUDE/Plan/Completed/00999-example/PLAN.md"

_HEAD = "# Plan 00999: example\n\n**Status**: {status}\n**Created**: 2026-09-08\n\n"
_TASKS = "## Tasks\n\n- [x] ✅ **Task 1.1**: done\n\n"
_CRITERIA_WITH = (
    "## Success Criteria\n\n- [x] All QA checks passing\n"
    "- [x] Every release-bound consequence is in the pending-release holding area:\n"
    "  `UNRELEASED/release-notes/01-example.md`.\n\n## Delivery & Milestones\n\n- x\n"
)
_CRITERIA_NONE = (
    "## Success Criteria\n\n- [x] All QA checks passing\n"
    "- [x] This plan has no release-bound consequences.\n\n## Delivery & Milestones\n\n- x\n"
)
_CRITERIA_WITHOUT = (
    "## Success Criteria\n\n- [x] All QA checks passing\n\n## Delivery & Milestones\n\n- x\n"
)


def _plan(status: str, criteria: str) -> str:
    return _HEAD.format(status=status) + _TASKS + criteria


@pytest.fixture
def handler() -> PlanDoneRequiresHoldingAreaHandler:
    return PlanDoneRequiresHoldingAreaHandler()


class TestIdentity:
    def test_name_and_shape(self, handler: PlanDoneRequiresHoldingAreaHandler) -> None:
        assert handler.name == "plan-done-requires-holding-area"
        assert handler.terminal is True
        assert "project" in handler.tags
        assert "blocking" in handler.tags


class TestAWriteThatCompletesAPlan:
    def test_denied_without_the_criterion(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        payload = write_hook_input(_ACTIVE, _plan("Complete", _CRITERIA_WITHOUT))
        assert handler.matches(payload) is True
        result = handler.handle(payload)
        assert result.decision.value == "deny"
        assert "holding area" in result.reason
        assert "UNRELEASED" in result.reason

    def test_allowed_when_the_criterion_names_an_artefact(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        assert (
            handler.matches(write_hook_input(_ACTIVE, _plan("Complete", _CRITERIA_WITH))) is False
        )

    def test_allowed_when_the_plan_declares_no_consequences(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        assert (
            handler.matches(write_hook_input(_ACTIVE, _plan("Complete", _CRITERIA_NONE))) is False
        )

    def test_a_non_terminal_status_is_never_judged(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        for status in ("In Progress", "Not Started", "Dormant", "Blocked"):
            payload = write_hook_input(_ACTIVE, _plan(status, _CRITERIA_WITHOUT))
            assert handler.matches(payload) is False, status

    def test_cancelled_and_superseded_ship_nothing_so_are_exempt(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        for status in ("Cancelled", "Superseded"):
            payload = write_hook_input(_ACTIVE, _plan(status, _CRITERIA_WITHOUT))
            assert handler.matches(payload) is False, status

    def test_the_criterion_must_be_in_the_success_criteria_section(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        """A mention in the Overview does not satisfy a criterion."""
        content = (
            _HEAD.format(status="Complete")
            + "## Overview\n\nThe holding area is nice.\n\n"
            + _TASKS
            + _CRITERIA_WITHOUT
        )
        assert handler.matches(write_hook_input(_ACTIVE, content)) is True


class TestScope:
    def test_only_plans_in_the_active_root_are_judged(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        """An archived plan is history; correcting one is not a status flip."""
        payload = write_hook_input(_ARCHIVED, _plan("Complete", _CRITERIA_WITHOUT))
        assert handler.matches(payload) is False

    def test_other_files_in_a_plan_folder_are_not_judged(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        payload = write_hook_input("CLAUDE/Plan/00999-example/RESEARCH.md", "**Status**: Complete")
        assert handler.matches(payload) is False

    def test_an_absolute_path_is_judged_the_same(
        self, handler: PlanDoneRequiresHoldingAreaHandler, write_hook_input: Any
    ) -> None:
        payload = write_hook_input(f"/workspace/{_ACTIVE}", _plan("Complete", _CRITERIA_WITHOUT))
        assert handler.matches(payload) is True

    def test_tools_other_than_write_and_edit_are_ignored(
        self, handler: PlanDoneRequiresHoldingAreaHandler, bash_hook_input: Any
    ) -> None:
        assert (
            handler.matches(bash_hook_input("git mv CLAUDE/Plan/x CLAUDE/Plan/Completed/")) is False
        )


class TestAnEditThatCompletesAPlan:
    """An Edit is judged on the content the file WOULD have."""

    def test_status_flip_is_denied_when_the_file_lacks_the_criterion(
        self,
        handler: PlanDoneRequiresHoldingAreaHandler,
        edit_hook_input: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = tmp_path / _ACTIVE
        plan.parent.mkdir(parents=True)
        plan.write_text(_plan("In Progress", _CRITERIA_WITHOUT), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        payload = edit_hook_input(_ACTIVE, "**Status**: In Progress", "**Status**: Complete")
        assert handler.matches(payload) is True

    def test_status_flip_is_allowed_when_the_criterion_is_already_there(
        self,
        handler: PlanDoneRequiresHoldingAreaHandler,
        edit_hook_input: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = tmp_path / _ACTIVE
        plan.parent.mkdir(parents=True)
        plan.write_text(_plan("In Progress", _CRITERIA_NONE), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        payload = edit_hook_input(_ACTIVE, "**Status**: In Progress", "**Status**: Complete")
        assert handler.matches(payload) is False

    def test_adding_the_criterion_in_the_same_edit_as_the_flip_is_allowed(
        self,
        handler: PlanDoneRequiresHoldingAreaHandler,
        edit_hook_input: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = tmp_path / _ACTIVE
        plan.parent.mkdir(parents=True)
        plan.write_text(_plan("In Progress", _CRITERIA_WITHOUT), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        payload = edit_hook_input(
            _ACTIVE,
            "- [x] All QA checks passing\n",
            "- [x] All QA checks passing\n- [x] This plan has no release-bound consequences.\n",
        )
        # The flip itself is a second edit; this one adds the criterion under
        # a still-non-terminal header, so nothing to judge.
        assert handler.matches(payload) is False

    def test_an_edit_to_a_file_that_does_not_exist_is_not_judged(
        self,
        handler: PlanDoneRequiresHoldingAreaHandler,
        edit_hook_input: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fail open on an unreadable target: the Edit tool will refuse it anyway."""
        monkeypatch.chdir(tmp_path)
        payload = edit_hook_input(_ACTIVE, "**Status**: In Progress", "**Status**: Complete")
        assert handler.matches(payload) is False


class TestDeclaredAcceptanceTestsAreProducible:
    """Plan 00319 Task 4.6: the declared acceptance test must carry a

    `tool_payload` (the `command` here is prose, not literal bash), and
    driving the handler with it must really produce the declared verdict.
    """

    def test_the_acceptance_test_declares_a_tool_payload(
        self, handler: PlanDoneRequiresHoldingAreaHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert tests, "fixture handler declared no acceptance tests"
        assert all(t.tool_payload is not None for t in tests)

    def test_the_declared_payload_produces_its_declared_verdict(
        self, handler: PlanDoneRequiresHoldingAreaHandler
    ) -> None:
        import re

        for test in handler.get_acceptance_tests():
            assert test.tool_payload is not None
            hook_input = {
                "tool_name": test.tool_payload.tool_name,
                "tool_input": test.tool_payload.tool_input,
            }
            if test.expected_decision == Decision.ALLOW:
                # The near miss: this handler allows by NOT matching, so
                # there is no handle() verdict to inspect.
                assert handler.matches(hook_input) is False, test.title
                continue
            assert handler.matches(hook_input) is True
            result = handler.handle(hook_input)
            assert result.decision == test.expected_decision, test.title
            for pattern in test.expected_message_patterns:
                assert re.search(pattern, result.reason or ""), (test.title, pattern)
