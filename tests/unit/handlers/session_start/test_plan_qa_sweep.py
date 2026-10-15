"""Tests for PlanQaSweepHandler (Plan 00144, Task 2.3).

SessionStart advisory that runs the Stage 3 plan QA sweep and injects one
compact drift report — silent when the plan tree is clean.
"""

import contextlib
import os
import subprocess
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.support.git_fixtures import git_setup_timeout

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep import PlanQaSweepHandler
from claude_code_hooks_daemon.plan_qa.runner import run_stage

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
    # A JOURNAL/ dir keeps the tree clean under the Plan 00163 journal checks
    # (has_journal → folder-present passes; no dated file → freshness skips).
    (folder / "JOURNAL").mkdir()
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=git_setup_timeout(),
    )
    return root


@contextlib.contextmanager
def _patched_context(root: Path) -> Iterator[None]:
    """Point the handler at ``root`` and give its cache a per-test directory."""
    module = "claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep.ProjectContext"
    with (
        patch(f"{module}.project_root", return_value=root),
        patch(f"{module}.daemon_untracked_dir", return_value=root.parent / "untracked"),
    ):
        yield


def _handler(
    plan_dir_rel: str | None = _PLAN_DIR_REL,
    policy: PlanWorkflowQaConfig | None = None,
) -> PlanQaSweepHandler:
    handler = PlanQaSweepHandler()
    handler._track_plans_in_project = plan_dir_rel
    handler._plan_qa = policy if policy is not None else PlanWorkflowQaConfig()
    # A cold sweep is awaited in full so these tests are not timing-dependent;
    # TestSweepCache sets it to zero where the pending path is the point.
    handler._sweep_wait_seconds = 60.0
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
        with _patched_context(root):
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

    def test_get_claude_md_names_the_exclusion(self) -> None:
        content = PlanQaSweepHandler().get_claude_md()
        assert content is not None
        assert "daemon.exclude_paths" in content


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: a plan folder under ``daemon.exclude_paths`` is not swept."""

    def test_drift_in_an_excluded_folder_is_silent(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        rogue = root / _PLAN_DIR_REL / "00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")
        handler = _handler()
        handler._project_exclude_paths = ["CLAUDE/Plan/00002-rogue/**"]

        with _patched_context(root):
            result = handler.handle(_new_session_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []


_RUN_STAGE = "claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep.run_stage"


def _rogue_plan(root: Path) -> None:
    rogue = root / _PLAN_DIR_REL / "00002-rogue"
    rogue.mkdir()
    (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")


class TestSweepCache:
    """Plan 00495 Task 2.6: the sweep is cached by input fingerprint, off the chain."""

    def _handle(self, handler: PlanQaSweepHandler, root: Path) -> list[str]:
        with _patched_context(root):
            context: list[str] = handler.handle(_new_session_input()).context
        return context

    def test_unchanged_inputs_reuse_the_cached_report(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _rogue_plan(root)
        handler = _handler()
        with patch(_RUN_STAGE, wraps=run_stage) as sweep:
            first = self._handle(handler, root)
            second = self._handle(handler, root)
        assert first
        assert second == first
        assert sweep.call_count == 1

    def test_editing_a_scanned_file_invalidates_the_cache(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        handler = _handler()
        assert self._handle(handler, root) == []

        _rogue_plan(root)

        assert "location-status-coherence" in "\n".join(self._handle(handler, root))

    def test_fixing_drift_clears_the_cached_report(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _rogue_plan(root)
        handler = _handler()
        assert self._handle(handler, root)

        (root / _PLAN_DIR_REL / "00002-rogue" / "PLAN.md").unlink()
        (root / _PLAN_DIR_REL / "00002-rogue").rmdir()

        assert self._handle(handler, root) == []

    def test_a_new_day_invalidates_the_cache(self, tmp_path: Path) -> None:
        """Staleness is judged against the current date, so one day's verdict is not the next."""
        root = _scaffold(tmp_path)
        handler = _handler()
        module = "claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep.date"
        with patch(_RUN_STAGE, wraps=run_stage) as sweep, patch(module) as fake_date:
            fake_date.today.return_value = date(2026, 1, 1)
            self._handle(handler, root)
            fake_date.today.return_value = date(2026, 1, 2)
            self._handle(handler, root)
        assert sweep.call_count == 2

    def test_a_new_commit_invalidates_the_cache(self, tmp_path: Path) -> None:
        """Dormancy and staleness read git history, which no file stat reflects."""
        root = _scaffold(tmp_path)
        handler = _handler()
        identity = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        with patch(_RUN_STAGE, wraps=run_stage) as sweep:
            self._handle(handler, root)
            subprocess.run(
                ["git", "-C", str(root), "commit", "--allow-empty", "-m", "x"],
                capture_output=True,
                check=True,
                timeout=git_setup_timeout(),
                env={**os.environ, **identity},
            )
            self._handle(handler, root)
        assert sweep.call_count == 2

    def test_slow_sweep_is_reported_pending_without_blocking_the_chain(
        self, tmp_path: Path
    ) -> None:
        root = _scaffold(tmp_path)
        handler = _handler()
        handler._sweep_wait_seconds = 0.0
        release = threading.Event()

        def slow(*args: object, **kwargs: object) -> list[object]:
            release.wait(60.0)
            return []

        with patch(_RUN_STAGE, side_effect=slow):
            context = self._handle(handler, root)
            release.set()

        text = "\n".join(context)
        assert "background" in text
        assert "plan-qa" in text
        assert "--sweep" in text
