"""Tests for scripts/qa/check_fixed_worktree_budget.py (class: fixed budget on a load-scaled subprocess)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "qa"))
import check_fixed_worktree_budget as checker

_SCAN_ROOT = checker._DEFAULT_SCAN_ROOT


def _scan(tmp_path: Path, code: str) -> list[checker.Violation]:
    module = tmp_path / "mod.py"
    module.write_text(textwrap.dedent(code), encoding="utf-8")
    violations, _ = checker.scan_file(module, tmp_path)
    return violations


class TestDetectsTheClass:
    def test_fixed_budget_on_worktree_add_is_reported(self, tmp_path: Path) -> None:
        found = _scan(
            tmp_path,
            """
            def add(cwd, path):
                run_git(cwd, "worktree", "add", str(path), timeout=Timeout.GIT_WORKTREE)
            """,
        )
        assert [v.function for v in found] == ["add"]

    def test_a_missing_timeout_is_reported(self, tmp_path: Path) -> None:
        found = _scan(
            tmp_path,
            """
            def remove(cwd, path):
                run_git(cwd, "worktree", "remove", str(path))
            """,
        )
        assert len(found) == 1

    def test_a_failure_path_call_beside_the_verb_is_reported(self, tmp_path: Path) -> None:
        found = _scan(
            tmp_path,
            """
            def undo(cwd, path):
                steps = [("worktree", "remove", "--force", str(path))]
                for args in steps:
                    run_git(cwd, *args, timeout=Timeout.GIT_WORKTREE_CLEANUP)
            """,
        )
        assert len(found) == 1

    def test_injected_runner_name_is_reported(self, tmp_path: Path) -> None:
        found = _scan(
            tmp_path,
            """
            def reap(run_fn, root, path):
                run_fn(root, "worktree", "remove", str(path), timeout=300)
            """,
        )
        assert len(found) == 1


class TestAcceptsTheFix:
    def test_scaled_budget_passes(self, tmp_path: Path) -> None:
        assert not _scan(
            tmp_path,
            """
            def add(cwd, path):
                run_git(cwd, "worktree", "add", str(path),
                        timeout=scaled_timeout(Timeout.GIT_WORKTREE, Timeout.GIT_WORKTREE_ADD_MAX))
            """,
        )

    def test_scaling_inside_a_wrapper_call_passes(self, tmp_path: Path) -> None:
        assert not _scan(
            tmp_path,
            """
            def remove(cwd, clock):
                args = ("worktree", "remove")
                run_git(cwd, *args, timeout=clock.timeout(scaled_timeout(30, 120), "step"))
            """,
        )

    def test_a_function_that_does_not_write_a_worktree_is_ignored(self, tmp_path: Path) -> None:
        assert not _scan(
            tmp_path,
            """
            def listing(cwd):
                run_git(cwd, "worktree", "list", "--porcelain")
            """,
        )


class TestTheRepositoryIsClean:
    def test_no_fixed_budget_remains_on_a_worktree_write(self) -> None:
        violations, rotted = checker.scan_tree(_SCAN_ROOT)
        assert [(v.file, v.line) for v in violations] == []
        assert rotted == []
