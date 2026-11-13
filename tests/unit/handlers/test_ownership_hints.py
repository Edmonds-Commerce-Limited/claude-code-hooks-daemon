"""Hint drops wired into existing handlers (Plan 00599 Task 3)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig, ClaudeMdConfig, ClaudeMdOwnership
from claude_code_hooks_daemon.core import branch_sweep, ownership
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchRecord,
    BranchState,
)
from claude_code_hooks_daemon.core.ownership import HINT_TEXT, OwnershipHint
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.agent_isolation_advisor import (
    AgentIsolationAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import PlanWorkflowHandler

_CONFIG = BranchesConfig()
_HINT = HINT_TEXT[OwnershipHint.BRANCH_OWNED]


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    ownership.reset()
    yield
    ownership.reset()


def _on() -> None:
    ownership.configure(ClaudeMdConfig())


def _off() -> None:
    ownership.configure(ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF))


# --- plan / ledger edits -------------------------------------------------------------


def _plan_edit(name: str = "README.md", tool: str = "Edit", session: str = "s1") -> dict[str, Any]:
    return {
        "tool_name": tool,
        "session_id": session,
        "tool_input": {"file_path": f"/repo/CLAUDE/Plan/00001-x/{name}"},
    }


class TestPlanTidyHint:
    def test_plan_file_edit_matches_and_hints_once(self) -> None:
        _on()
        handler = PlanWorkflowHandler()
        hook = _plan_edit()
        assert handler.matches(hook) is True
        context = "\n".join(handler.handle(hook).context or [])
        assert HINT_TEXT[OwnershipHint.PLAN_TIDY] in context
        assert handler.matches(hook) is False

    def test_plan_md_write_keeps_workflow_guidance_plus_hint(self) -> None:
        _on()
        handler = PlanWorkflowHandler()
        hook = _plan_edit("PLAN.md", tool="Write")
        context = "\n".join(handler.handle(hook).context or [])
        assert "Plan Workflow Reminders" in context
        assert HINT_TEXT[OwnershipHint.PLAN_TIDY] in context

    def test_off_means_no_match_for_other_plan_files_and_no_hint(self) -> None:
        _off()
        handler = PlanWorkflowHandler()
        assert handler.matches(_plan_edit()) is False
        context = "\n".join(handler.handle(_plan_edit("PLAN.md", tool="Write")).context or [])
        assert HINT_TEXT[OwnershipHint.PLAN_TIDY] not in context

    def test_non_plan_path_never_matches(self) -> None:
        _on()
        hook = {"tool_name": "Edit", "tool_input": {"file_path": "/repo/src/a.py"}}
        assert PlanWorkflowHandler().matches(hook) is False


# --- QA failure ----------------------------------------------------------------------


class TestQaFailureHint:
    def test_lint_deny_reason_carries_hint_once_per_session(self) -> None:
        _on()
        handler = LintOnEditHandler()
        hook = {"session_id": "s1"}
        first = handler._deny_reason(hook, "detail")
        assert HINT_TEXT[OwnershipHint.QA_FAILURE] in first
        assert HINT_TEXT[OwnershipHint.QA_FAILURE] not in handler._deny_reason(hook, "detail")

    def test_off_is_silent(self) -> None:
        _off()
        reason = LintOnEditHandler()._deny_reason({"session_id": "s1"}, "detail")
        assert HINT_TEXT[OwnershipHint.QA_FAILURE] not in reason


# --- branches ------------------------------------------------------------------------

_BASE = BranchRecord(
    name="base",
    state=BranchState.LIVE,
    local_tip="a" * 40,
    remote_tip=None,
    upstream=None,
    worktree=None,
    ahead=None,
    behind=None,
    lines=None,
    committed_at=None,
    age_days=None,
    parked_reason=None,
    plan=None,
    issue=None,
)


def _record(name: str, state: BranchState, **extra: Any) -> BranchRecord:
    return replace(_BASE, name=name, state=state, **extra)


def _inventory(*records: BranchRecord) -> BranchInventory:
    return BranchInventory(
        default_branch="main",
        default_ref="refs/remotes/origin/main",
        records={r.name: r for r in records},
    )


class TestBranchHints:
    def test_session_summary_owned_hint_on_new_session_with_owned_work(self) -> None:
        inv = _inventory(_record("done", BranchState.MERGED_DEFAULT))
        lines = branch_sweep.session_summary(
            inv, _CONFIG, cap=10, new_session=True, owned_hint=lambda: _HINT
        )
        assert HINT_TEXT[OwnershipHint.BRANCH_OWNED] in "\n".join(lines)

    def test_session_summary_default_has_no_hint(self) -> None:
        inv = _inventory(_record("done", BranchState.MERGED_DEFAULT))
        lines = branch_sweep.session_summary(inv, _CONFIG, cap=10, new_session=True)
        assert HINT_TEXT[OwnershipHint.BRANCH_OWNED] not in "\n".join(lines)

    def test_session_summary_silent_when_nothing_to_say(self) -> None:
        lines = branch_sweep.session_summary(
            _inventory(), _CONFIG, cap=10, new_session=True, owned_hint=lambda: _HINT
        )
        assert lines == []

    def test_report_foreign_counter_hint(self) -> None:
        inv = _inventory(_record("theirs", BranchState.FOREIGN, author="Someone"))
        text = "\n".join(branch_sweep.render_report(inv, _CONFIG, cap=10, ownership_hints=True))
        assert HINT_TEXT[OwnershipHint.BRANCH_FOREIGN] in text

    def test_report_foreign_no_hint_by_default_or_without_foreign(self) -> None:
        inv = _inventory(_record("theirs", BranchState.FOREIGN, author="Someone"))
        assert HINT_TEXT[OwnershipHint.BRANCH_FOREIGN] not in "\n".join(
            branch_sweep.render_report(inv, _CONFIG, cap=10)
        )
        assert HINT_TEXT[OwnershipHint.BRANCH_FOREIGN] not in "\n".join(
            branch_sweep.render_report(_inventory(), _CONFIG, cap=10, ownership_hints=True)
        )

    def test_report_owned_hint_when_owned_groups_listed(self) -> None:
        inv = _inventory(_record("done", BranchState.MERGED_DEFAULT))
        text = "\n".join(branch_sweep.render_report(inv, _CONFIG, cap=10, ownership_hints=True))
        assert HINT_TEXT[OwnershipHint.BRANCH_OWNED] in text


# --- dispatch ------------------------------------------------------------------------


def _dispatch(session: str = "s1") -> dict[str, Any]:
    return {"tool_name": "Task", "session_id": session, "tool_input": {"prompt": "do it"}}


class TestDispatchHint:
    @pytest.fixture
    def handler(self, tmp_path: Path) -> AgentIsolationAdvisorHandler:
        instance = AgentIsolationAdvisorHandler()
        instance._project_root = tmp_path / "p"
        instance._config_dir = tmp_path / "c"
        return instance

    def test_lone_agent_matches_for_hint_once(self, handler: AgentIsolationAdvisorHandler) -> None:
        _on()
        with patch.object(AgentIsolationAdvisorHandler, "_count_live_threads", return_value=1):
            hook = _dispatch()
            assert handler.matches(hook) is True
            context = "\n".join(handler.handle(hook).context or [])
            assert HINT_TEXT[OwnershipHint.DISPATCH] in context
            assert "CONCURRENT AGENTS" not in context
            assert handler.matches(hook) is False

    def test_concurrent_agents_get_both(self, handler: AgentIsolationAdvisorHandler) -> None:
        _on()
        with patch.object(AgentIsolationAdvisorHandler, "_count_live_threads", return_value=3):
            context = "\n".join(handler.handle(_dispatch()).context or [])
        assert "CONCURRENT AGENTS" in context
        assert HINT_TEXT[OwnershipHint.DISPATCH] in context

    def test_off_keeps_old_silence(self, handler: AgentIsolationAdvisorHandler) -> None:
        _off()
        with patch.object(AgentIsolationAdvisorHandler, "_count_live_threads", return_value=1):
            assert handler.matches(_dispatch()) is False
