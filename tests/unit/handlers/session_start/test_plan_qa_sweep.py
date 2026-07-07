"""Tests for PlanQaSweepHandler (Plan 00144, Task 2.3).

SessionStart advisory that runs the Stage 3 plan QA sweep and injects one
compact drift report — silent when the plan tree is clean.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep import PlanQaSweepHandler

_PLAN_DIR_REL = "CLAUDE/Plan"


def _scaffold(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    plan_dir = root / _PLAN_DIR_REL
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return root


def _handler(
    plan_dir_rel: str | None = _PLAN_DIR_REL,
    policy: PlanWorkflowQaConfig | None = None,
) -> PlanQaSweepHandler:
    handler = PlanQaSweepHandler()
    handler._track_plans_in_project = plan_dir_rel
    handler._plan_qa = policy if policy is not None else PlanWorkflowQaConfig()
    return handler


def _new_session_input() -> dict[str, Any]:
    return {"hook_event_name": "SessionStart"}


class TestInit:
    def test_identity(self) -> None:
        handler = PlanQaSweepHandler()
        assert handler.name == "plan-qa-sweep"
        assert handler.terminal is False
        assert "planning" in handler.tags
        assert "advisory" in handler.tags


class TestMatches:
    def test_matches_new_session_with_policy(self) -> None:
        assert _handler().matches(_new_session_input()) is True

    def test_skips_resume_session(self, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 500)
        hook_input: dict[str, Any] = {"transcript_path": str(transcript)}
        assert _handler().matches(hook_input) is False

    def test_skips_without_injected_policy(self) -> None:
        handler = PlanQaSweepHandler()
        handler._track_plans_in_project = _PLAN_DIR_REL
        handler._plan_qa = None
        assert handler.matches(_new_session_input()) is False

    def test_skips_when_qa_disabled(self) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(enabled=False))
        assert handler.matches(_new_session_input()) is False

    def test_skips_when_sweep_mode_off(self) -> None:
        handler = _handler(policy=PlanWorkflowQaConfig(sweep_mode="off"))
        assert handler.matches(_new_session_input()) is False

    def test_skips_without_plan_dir(self) -> None:
        handler = _handler(plan_dir_rel=None)
        assert handler.matches(_new_session_input()) is False


class TestHandle:
    def _run(self, handler: PlanQaSweepHandler, root: Path) -> Any:
        target = (
            "claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep."
            "ProjectContext.project_root"
        )
        with patch(target, return_value=root):
            return handler.handle(_new_session_input())

    def test_clean_tree_is_silent(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        result = self._run(_handler(), root)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_drifted_tree_injects_compact_report(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        rogue = root / _PLAN_DIR_REL / "00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")

        result = self._run(_handler(), root)

        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "location-status-coherence" in text
        assert "plan-qa --sweep" in text

    def test_missing_plan_dir_surfaces_structural_warning(self, tmp_path: Path) -> None:
        root = tmp_path / "bare"
        root.mkdir()
        result = self._run(_handler(), root)
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert _PLAN_DIR_REL in text
        assert "does not exist" in text.lower()


class TestGuidance:
    def test_get_claude_md_documents_sweep(self) -> None:
        text = PlanQaSweepHandler().get_claude_md()
        assert text is not None
        assert "plan-qa" in text

    def test_acceptance_tests_defined(self) -> None:
        assert len(PlanQaSweepHandler().get_acceptance_tests()) >= 1

    def test_default_enabled(self) -> None:
        assert PlanQaSweepHandler().get_default_enabled() is True
