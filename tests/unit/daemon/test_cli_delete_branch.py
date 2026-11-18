"""Tests for the ``delete-branch`` CLI surface (Plan 00206).

The proof engine is tested exhaustively in ``test_branch_safety.py`` against
real repositories. What is tested HERE is the one thing only the CLI can decide:
**whether a human is reachable at all**.

That distinction is the whole human gate. The engine refuses abandonment unless
a confirmation callback consents; the CLI supplies that callback only when
stdin is a real terminal. An agent's Bash tool is not one, so an agent cannot
abandon unmerged work however many flags it declares — not because it is
distrusted, but because consent is not something the requesting party can grant
itself.
"""

from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_MERGED,
    TIER_MERGED_NOT_IN_HEAD,
    TIER_MERGED_UNPUSHED,
    TIER_UNPROVEN,
    BranchClassification,
    DeletionReport,
)
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_delete_branch

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_EXIT_REFUSED = 1
_TIP = "a" * 40
_EXIT_USAGE = 2


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repo_with_abandoned_branch(tmp_path: Path) -> Path:
    """A repo whose ``doomed`` branch holds content found nowhere else."""
    path = tmp_path / "repo"
    path.mkdir()
    # ``get_project_path`` validates a project root by its ``.claude`` dir and,
    # in normal (non-self-install) mode, an installed ``hooks-daemon`` beneath it.
    (path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _commit(path, "base.txt", "base\n", "Initial commit")
    _git(path, "checkout", "-b", "doomed")
    _commit(path, "only-here.txt", "unique work\n", "Work only on the branch")
    _git(path, "checkout", "main")
    return path


def _args(repo: Path, **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": ["doomed"],
        "protected_ref": "main",
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _line_repo(tmp_path: Path, *, merged: bool) -> Path:
    """A repo declaring `release/*` as an integration line, with `release/1` on it."""
    path = tmp_path / "linerepo"
    path.mkdir()
    (path / ".claude" / "hooks-daemon").mkdir(parents=True)
    (path / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '2.0'\nbranches:\n  integration_lines: ['release/*']\n", encoding="utf-8"
    )
    _git(path, "init", "-b", "main")
    _git(path, "remote", "add", "origin", "https://example.invalid/repo.git")
    _commit(path, "base.txt", "base\n", "Initial commit")
    _git(path, "checkout", "-b", "release/1")
    _commit(path, "rel.txt", "release\n", "Release work")
    _git(path, "checkout", "main")
    if merged:
        _git(path, "merge", "--no-ff", "-m", "Merge release/1", "release/1")
    return path


class TestIntegrationLines:
    """An integration line merged into the default is deletable; an unmerged one is not."""

    def test_a_merged_line_is_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=True)
        exit_code = cmd_delete_branch(_args(repo, branches=["release/1"]))
        assert exit_code == 0
        assert "release/1" not in _git(repo, "branch", "--list")

    def test_an_unmerged_line_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=False)
        exit_code = cmd_delete_branch(_args(repo, branches=["release/1"]))
        assert exit_code == _EXIT_REFUSED
        assert "release/1" in _git(repo, "branch", "--list")
        assert "not yet merged into" in capsys.readouterr().err

    def test_an_unmerged_line_is_refused_whatever_protected_ref_names_another_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=False)
        _git(repo, "branch", "release/2", "release/1")
        exit_code = cmd_delete_branch(
            _args(repo, branches=["release/1"], protected_ref="release/2")
        )
        assert exit_code == _EXIT_REFUSED
        assert "release/1" in _git(repo, "branch", "--list")
        assert "not yet merged into" in capsys.readouterr().err

    def test_an_unmerged_line_is_refused_when_protected_ref_is_its_own_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=False)
        own_sha = _git(repo, "rev-parse", "release/1").strip()
        exit_code = cmd_delete_branch(_args(repo, branches=["release/1"], protected_ref=own_sha))
        assert exit_code == _EXIT_USAGE
        assert "release/1" in _git(repo, "branch", "--list")

    def test_every_line_is_refused_when_the_default_cannot_be_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=True)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.cli.git_sync.resolve_default_branch",
            lambda *_a, **_k: None,
        )
        exit_code = cmd_delete_branch(_args(repo, branches=["release/1"], protected_ref="main"))
        assert exit_code == _EXIT_USAGE
        assert "release/1" in _git(repo, "branch", "--list")

    def test_the_default_branch_is_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        repo = _line_repo(tmp_path, merged=True)
        _git(repo, "checkout", "-b", "elsewhere")
        exit_code = cmd_delete_branch(_args(repo, branches=["main"]))
        assert exit_code == _EXIT_REFUSED
        assert "main" in _git(repo, "branch", "--list")


class TestAgentsCannotAbandonWork:
    """An unproven branch is never deleted: no flag, reason or terminal changes that."""

    def test_an_unproven_branch_is_refused_and_survives(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())

        exit_code = cmd_delete_branch(_args(repo_with_abandoned_branch))

        assert exit_code == _EXIT_REFUSED
        assert "doomed" in _git(repo_with_abandoned_branch, "branch", "--list")
        assert "never deleted by this command" in capsys.readouterr().err

    def test_the_refusal_names_no_route_around_the_proof(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())

        cmd_delete_branch(_args(repo_with_abandoned_branch))

        stderr = capsys.readouterr().err
        assert "--allow-unproven" not in stderr
        assert "--reason" not in stderr

    def test_the_flags_that_declared_intent_no_longer_exist(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["delete-branch", "doomed", "--allow-unproven"])

    def test_a_dry_run_still_classifies_an_unproven_branch(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())

        exit_code = cmd_delete_branch(_args(repo_with_abandoned_branch, dry_run=True))

        assert exit_code == _EXIT_REFUSED
        assert TIER_UNPROVEN in capsys.readouterr().out


class TestAGitFailureIsARefusalNotATraceback:
    """Plan 00248 F1: an expired budget must read as a refusal.

    ``run_git`` reports a timeout as returncode 127 and ``branch_safety._git``
    re-raises that as ``CalledProcessError``. This command caught only
    ``ValueError``, so any git failure it had not classified escaped as a stack
    trace — from the one command in the daemon whose entire purpose is to refuse
    clearly when it cannot prove a deletion is safe.
    """

    def test_a_git_failure_exits_nonzero_with_a_message(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise subprocess.CalledProcessError(127, ["git", "cherry"], "", "timed out after 300s")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.branch_safety.delete_branches", explode
        )

        exit_code = cmd_delete_branch(_args(repo_with_abandoned_branch))

        assert exit_code == 2
        stderr = capsys.readouterr().err
        assert "nothing was deleted" in stderr
        assert "timed out" in stderr

    def test_the_branch_survives_a_git_failure(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The report must match reality: nothing deleted means nothing deleted."""
        monkeypatch.setattr("sys.stdin", io.StringIO())

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise subprocess.CalledProcessError(127, ["git", "cherry"], "", "timed out")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.branch_safety.delete_branches", explode
        )

        cmd_delete_branch(_args(repo_with_abandoned_branch))
        capsys.readouterr()

        assert "doomed" in _git(repo_with_abandoned_branch, "branch", "--list")


class TestAPartialBatchIsReportedHonestly:
    """Plan 00253: ``refused`` does NOT mean nothing happened.

    Plan 00249 made a partial batch a real outcome — git can decline one branch
    after others are already gone. The CLI was never updated for that, so one
    hard-coded line could assert untruths at once: that a deleted branch survived,
    that no restore line was owed, and that ``--allow-unproven`` was the remedy
    when nothing was unproven.

    The report shape asserted here is not invented — it is the shape
    ``delete_branches`` really produces, and
    ``test_a_genuine_partial_batch_produces_this_shape`` proves that with real git
    rather than leaving these tests resting on a guess.
    """

    @staticmethod
    def _partial() -> DeletionReport:
        """The real shape: one branch gone, one refused by git."""
        return DeletionReport(
            classifications=(
                BranchClassification(name="shipped", tier=TIER_MERGED_UNPUSHED, tip=_TIP),
                BranchClassification(name="stuck", tier=TIER_MERGED),
            ),
            deleted=("shipped",),
            refused=True,
            blockers=("stuck: git refused the delete (proven merged) — not fully merged.",),
        )

    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        repo: Path,
        report: DeletionReport,
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.branch_safety.delete_branches",
            lambda *_a, **_kw: report,
        )
        self.exit_code = cmd_delete_branch(_args(repo, branches=["shipped", "stuck"]))

    def test_it_does_not_claim_nothing_was_deleted(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The sentence that was false: a branch HAD been deleted."""
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial())

        assert "nothing was deleted" not in capsys.readouterr().err

    def test_it_names_what_actually_went(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial())

        err = capsys.readouterr().err
        assert "shipped" in err
        assert "PARTIALLY REFUSED" in err

    def test_it_prints_the_restore_line_for_the_branch_that_went(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The exact line that puts back the branch that WAS deleted."""
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial())

        err = capsys.readouterr().err
        assert f"git branch shipped {_TIP}" in err
        assert "git branch stuck" not in err

    def test_it_names_no_unproven_route_for_a_git_refusal(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial())

        assert "--allow-unproven" not in capsys.readouterr().err

    def test_an_unproven_tier_says_the_command_never_deletes_it(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        report = DeletionReport(
            classifications=(BranchClassification(name="doomed", tier=TIER_UNPROVEN),),
            deleted=(),
            refused=True,
            blockers=("doomed: content found only here",),
        )
        self._run(monkeypatch, repo_with_abandoned_branch, report)

        err = capsys.readouterr().err
        assert "--allow-unproven" not in err
        assert "never deleted by this command" in err
        assert "nothing was deleted" in err

    def test_the_exit_code_stays_non_zero(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Something the caller asked for did not happen (Plan 00253 Decision 2).

        The defect was the message, not the status. A zero exit would hide the
        refusal from any script wrapping this command.
        """
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial())
        capsys.readouterr()

        assert self.exit_code == _EXIT_REFUSED

    def test_a_genuine_partial_batch_produces_this_shape(self, tmp_path: Path) -> None:
        """Proves the crafted report above is real, using real git.

        Without this every test in this class could pass against a shape
        ``delete_branches`` never produces. The refusal is provoked the way the
        engine's own tests do it — forcing the SAFE delete argv for the one tier
        git will decline — rather than by mocking git away.
        """
        remote = tmp_path / "remote.git"
        subprocess.run(
            ["git", "init", "--quiet", "--bare", str(remote)],
            check=True,
            capture_output=True,
            env={**_ENV, "HOME": str(tmp_path)},
        )
        repo = tmp_path / "real"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _commit(repo, "base.txt", "base\n", "Initial commit")
        _git(repo, "remote", "add", "origin", str(remote))
        _git(repo, "push", "--quiet", "--set-upstream", "origin", "main")

        # `shipped`: merged, ahead of its own upstream -> force-deletes cleanly.
        _git(repo, "checkout", "-b", "shipped")
        _commit(repo, "shipped.txt", "shipped\n", "Add shipped")
        _git(repo, "push", "--quiet", "--set-upstream", "origin", "shipped")
        _commit(repo, "shipped.txt", "shipped\nmore\n", "Never pushed")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge shipped", "shipped")

        # `stuck`: merged, no upstream -> `merged-not-in-head` once HEAD moves.
        _git(repo, "checkout", "-b", "stuck", "main")
        _commit(repo, "stuck.txt", "stuck\n", "Add stuck")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge stuck", "stuck")
        _git(repo, "checkout", "-b", "elsewhere", "HEAD~2")

        real_argv = branch_safety.delete_argv_for_tier

        def safe_delete_for_the_head_tier_only(tier: str | None) -> tuple[str, ...]:
            """Only `stuck` gets the argv git refuses; `shipped` keeps its own."""
            if tier == TIER_MERGED_NOT_IN_HEAD:
                return ("branch", "--delete")
            return real_argv(tier)

        with patch.object(
            branch_safety, "delete_argv_for_tier", safe_delete_for_the_head_tier_only
        ):
            report = branch_safety.delete_branches(repo, ["shipped", "stuck"])

        assert report.refused is True, "the forced argv must make git decline `stuck`"
        assert report.deleted == ("shipped",), "and the other branch must be gone"
        assert len(report.restore_commands) == 1, "a restore line is owed for what went"
        assert report.restore_commands[0].startswith("git branch shipped ")


class TestADeletionMainNeverHeldIsRefused:
    """Plan 00618 B-1 through the command: no new bytes, but a net change main never held."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        path = tmp_path / "repo"
        path.mkdir()
        (path / ".claude" / "hooks-daemon").mkdir(parents=True)
        _git(path, "init", "-b", "main")
        _commit(path, "a.txt", "v1\n", "Add a at v1")
        _commit(path, "b.txt", "b\n", "Add b")
        _commit(path, "a.txt", "v2\n", "Main moves a to v2")
        _git(path, "checkout", "-b", "doomed")
        _git(path, "rm", "-q", "b.txt")
        _commit(path, "a.txt", "v1\n", "Delete b, put a back to v1")
        _git(path, "checkout", "main")
        return path

    def test_the_command_refuses_and_says_why(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tip = _git(repo, "rev-parse", "refs/heads/doomed").strip()
        exit_code = cmd_delete_branch(_args(repo))
        captured = capsys.readouterr()
        assert exit_code == _EXIT_REFUSED
        assert _git(repo, "rev-parse", "refs/heads/doomed").strip() == tip
        assert "net change" in captured.out + captured.err
