"""`delete-branch` and `worktree-reap` read the default branch from `branches:` (Plan 00558 Task 2.0).

The argparse defaults are `None`; `None` resolves through
`git_sync.resolve_default_branch`, and an explicit flag still wins.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import worktree_reaping
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport
from claude_code_hooks_daemon.daemon.cli import (
    build_parser,
    cmd_delete_branch,
    cmd_worktree_reap,
)

_EXIT_USAGE = 2


def _project(tmp_path: Path, branches_yaml: str | None) -> Path:
    """A git repository with no commits, so `auto` cannot name a default branch."""
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q", "-b", "main"], check=True)
    # Project detection requires an `origin`; it need not exist, nothing is fetched.
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", str(tmp_path / "none.git")],
        check=True,
    )
    if branches_yaml is not None:
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            f'version: "2.0"\nbranches:\n{branches_yaml}'
        )
    return tmp_path


class TestParserDefaults:
    def test_delete_branch_protected_ref_defaults_to_none(self) -> None:
        args = build_parser().parse_args(["delete-branch", "x"])
        assert args.protected_ref is None

    def test_worktree_reap_base_branch_defaults_to_none(self) -> None:
        args = build_parser().parse_args(["worktree-reap"])
        assert args.base_branch is None


def _delete_args(repo: Path, protected_ref: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=repo,
        branches=["doomed"],
        protected_ref=protected_ref,
        allow_unproven=False,
        reason=None,
        bundle=str(repo / "b.bundle"),
        no_bundle=True,
        dry_run=True,
        format="text",
    )


@pytest.fixture
def captured_delete(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_delete(repo: Path, names: list[str], **kwargs: Any) -> DeletionReport:
        seen.update(kwargs)
        return DeletionReport()

    monkeypatch.setattr(branch_safety, "delete_branches", fake_delete)
    return seen


class TestDeleteBranch:
    def test_named_default_is_the_protected_ref(
        self, tmp_path: Path, captured_delete: dict[str, Any]
    ) -> None:
        repo = _project(tmp_path, "  default: trunk\n  protected_names: [keep]\n")
        cmd_delete_branch(_delete_args(repo, None))
        assert captured_delete["protected_ref"] == "trunk"
        assert set(captured_delete["protected_names"]) == {"keep", "trunk"}

    def test_explicit_flag_wins(self, tmp_path: Path, captured_delete: dict[str, Any]) -> None:
        repo = _project(tmp_path, "  default: trunk\n")
        cmd_delete_branch(_delete_args(repo, "release"))
        assert captured_delete["protected_ref"] == "release"

    def test_model_default_protected_names_without_a_block(
        self, tmp_path: Path, captured_delete: dict[str, Any]
    ) -> None:
        repo = _project(tmp_path, None)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "c",
            ],
            check=True,
        )
        cmd_delete_branch(_delete_args(repo, None))
        assert captured_delete["protected_ref"] == "main"
        assert set(captured_delete["protected_names"]) == {"main", "master", "develop", "trunk"}

    def test_unresolvable_default_is_a_usage_error(
        self,
        tmp_path: Path,
        captured_delete: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = _project(tmp_path, None)
        assert cmd_delete_branch(_delete_args(repo, None)) == _EXIT_USAGE
        assert "--protected-ref" in capsys.readouterr().err
        assert captured_delete == {}


class TestDeleteBranchRefusesNeverWorkBranches:
    """Exempt and protected-name matches are refused like the default.

    An integration line is judged by the proof instead (see ``test_cli_delete_branch``).
    """

    @pytest.mark.parametrize("name", ["users/alice", "keep"])
    def test_refused_although_merged(
        self, tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _project(
            tmp_path,
            "  default: main\n  exempt: ['users/*']\n  integration_lines: ['release/*']\n"
            "  protected_names: [keep]\n",
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "c",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(repo), "branch", name], check=True)
        args = _delete_args(repo, None)
        args.branches = [name]
        args.format = "json"
        assert cmd_delete_branch(args) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["classifications"][0]["refusal"] == branch_safety.REFUSAL_PROTECTED

    def test_globs_are_passed_through(
        self, tmp_path: Path, captured_delete: dict[str, Any]
    ) -> None:
        repo = _project(
            tmp_path, "  default: trunk\n  exempt: ['users/*']\n  integration_lines: ['rel/*']\n"
        )
        cmd_delete_branch(_delete_args(repo, None))
        assert {"users/*", "trunk"} <= set(captured_delete["protected_names"])
        assert "rel/*" not in captured_delete["protected_names"]
        assert list(captured_delete["line_names"]) == ["rel/*"]


class TestClassifyBranchGlobs:
    def test_a_protected_glob_refuses_a_matching_name(self, tmp_path: Path) -> None:
        repo = _project(tmp_path, None)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "c",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(repo), "branch", "users/bob"], check=True)
        verdict = branch_safety.classify_branch(
            repo, "users/bob", protected_ref="main", protected_names=("users/*",)
        )
        assert verdict.refusal == branch_safety.REFUSAL_PROTECTED


class TestWorktreeReap:
    @pytest.fixture
    def captured_base(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []

        def fake_states(repo: Path, base: str, **_: Any) -> tuple[()]:
            seen.append(base)
            return ()

        def fake_orphans(repo: Path, base: str, **_: Any) -> tuple[()]:
            seen.append(base)
            return ()

        monkeypatch.setattr(worktree_reaping, "collect_worktree_states", fake_states)
        monkeypatch.setattr(worktree_reaping, "collect_orphaned_branches", fake_orphans)
        return seen

    def _args(self, repo: Path, base: str | None) -> argparse.Namespace:
        return argparse.Namespace(project_root=repo, base_branch=base, reap=False, only=None)

    def test_named_default_is_the_base(self, tmp_path: Path, captured_base: list[str]) -> None:
        repo = _project(tmp_path, "  default: trunk\n")
        assert cmd_worktree_reap(self._args(repo, None)) == 0
        assert captured_base == ["trunk", "trunk"]

    def test_explicit_flag_wins(self, tmp_path: Path, captured_base: list[str]) -> None:
        repo = _project(tmp_path, "  default: trunk\n")
        assert cmd_worktree_reap(self._args(repo, "develop")) == 0
        assert captured_base == ["develop", "develop"]

    def test_unresolvable_default_is_a_usage_error(
        self, tmp_path: Path, captured_base: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _project(tmp_path, None)
        assert cmd_worktree_reap(self._args(repo, None)) == _EXIT_USAGE
        assert "--base-branch" in capsys.readouterr().err
        assert captured_base == []
