"""Tests for PlanWorkflowAssetCheckerHandler (Plan 00185 Task 3.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.session_start.plan_workflow_asset_checker import (
    PlanWorkflowAssetCheckerHandler,
)


def _session_start_input(transcript_path: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"hook_event_name": "SessionStart"}
    if transcript_path is not None:
        hook_input["transcript_path"] = transcript_path
    return hook_input


def _make_handler(plan_dir_rel: str | None = "CLAUDE/Plan") -> PlanWorkflowAssetCheckerHandler:
    handler = PlanWorkflowAssetCheckerHandler()
    # The registry injects this for planning-tagged handlers (None when the
    # plan workflow is disabled in config).
    handler._track_plans_in_project = plan_dir_rel
    return handler


class TestInit:
    def test_name_and_priority(self) -> None:
        handler = PlanWorkflowAssetCheckerHandler()
        assert handler.name == "plan-workflow-asset-checker"
        assert handler.priority == 59
        assert handler.terminal is False


class TestMatches:
    def test_disabled_workflow_does_not_match(self) -> None:
        handler = _make_handler(plan_dir_rel=None)
        assert handler.matches(_session_start_input()) is False

    def test_enabled_new_session_matches(self) -> None:
        handler = _make_handler()
        assert handler.matches(_session_start_input()) is True

    def test_resume_session_does_not_match(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x" * 200)
        handler = _make_handler()
        assert handler.matches(_session_start_input(str(transcript))) is False


class TestHandle:
    def test_silent_when_mkplan_present(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "mkplan.bash").write_text("#!/bin/bash\n")
        handler = _make_handler()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "plan_workflow_asset_checker.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            result = handler.handle(_session_start_input())
        assert result.decision.value == "allow"
        assert result.context == []

    def test_advises_when_mkplan_missing(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE" / "Plan").mkdir(parents=True)  # dir exists, mkplan absent
        handler = _make_handler()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "plan_workflow_asset_checker.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            result = handler.handle(_session_start_input())
        assert result.decision.value == "allow"
        text = "\n".join(result.context)
        assert "mkplan.bash" in text
        assert "deploy-plan-workflow" in text

    def test_names_missing_journal_assets_too(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE" / "Plan").mkdir(parents=True)
        handler = _make_handler()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "plan_workflow_asset_checker.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            result = handler.handle(_session_start_input())
        text = "\n".join(result.context)
        assert "_JOURNAL_TEMPLATE_.md" in text
        assert "PlanJournalling.md" in text

    def test_silent_when_all_assets_present(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "mkplan.bash").write_text("x")
        (plan_dir / "_JOURNAL_TEMPLATE_.md").write_text("x")
        (tmp_path / "CLAUDE" / "PlanJournalling.md").write_text("x")
        handler = _make_handler()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "plan_workflow_asset_checker.ProjectContext.project_root",
            return_value=tmp_path,
        ):
            result = handler.handle(_session_start_input())
        assert result.context == []


class TestClaudeMd:
    def test_get_claude_md_present(self) -> None:
        handler = PlanWorkflowAssetCheckerHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "deploy-plan-workflow" in guidance


class TestAcceptance:
    def test_returns_list(self) -> None:
        handler = PlanWorkflowAssetCheckerHandler()
        assert isinstance(handler.get_acceptance_tests(), list)
