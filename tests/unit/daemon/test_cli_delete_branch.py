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
import subprocess  # nosec B404 - trusted system tool (git) for repo fixtures
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
from claude_code_hooks_daemon.daemon.cli import (
    _ABANDON_CONFIRMATION_WORD,
    _confirm_abandonment_on_tty,
    _stdin_is_a_terminal,
    cmd_delete_branch,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_EXIT_REFUSED = 1


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
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
        "allow_unproven": True,
        "reason": "no longer needed",
        "bundle": str(repo / "bundle.bundle"),
        "no_bundle": True,
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestTerminalDetection:
    """``_stdin_is_a_terminal`` decides whether a human can be asked."""

    def test_a_pipe_is_not_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("abandon\n"))
        assert _stdin_is_a_terminal() is False

    def test_a_closed_stdin_is_not_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A closed stdin raises on ``isatty()``; that is an answer, not a crash."""
        closed = io.StringIO()
        closed.close()
        monkeypatch.setattr("sys.stdin", closed)
        assert _stdin_is_a_terminal() is False

    def test_an_absent_stdin_is_not_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Detached processes can have ``sys.stdin is None``."""
        monkeypatch.setattr("sys.stdin", None)
        assert _stdin_is_a_terminal() is False


class TestAgentsCannotAbandonWork:
    """The behaviour the gate exists for."""

    def test_abandonment_without_a_terminal_is_refused(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Every flag declared, no terminal: still refused, branch still there."""
        monkeypatch.setattr("sys.stdin", io.StringIO())

        exit_code = cmd_delete_branch(_args(repo_with_abandoned_branch))

        assert exit_code == _EXIT_REFUSED
        assert "doomed" in _git(repo_with_abandoned_branch, "branch", "--list")
        stderr = capsys.readouterr().err
        assert "human" in stderr.lower()

    def test_the_refusal_names_the_terminal_requirement(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dead-end refusal is a bug; the message must say what would work."""
        monkeypatch.setattr("sys.stdin", io.StringIO())

        cmd_delete_branch(_args(repo_with_abandoned_branch))

        stderr = capsys.readouterr().err
        assert "terminal" in stderr.lower()

    def test_a_dry_run_still_classifies_without_a_terminal(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Inspection is not deletion, so the gate must not block understanding."""
        monkeypatch.setattr("sys.stdin", io.StringIO())

        exit_code = cmd_delete_branch(
            _args(repo_with_abandoned_branch, dry_run=True, allow_unproven=True)
        )

        assert exit_code == 0
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
            raise subprocess.CalledProcessError(
                127, ["git", "bundle", "create"], "", "timed out after 300s"
            )

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


class TestTheConfirmationPrompt:
    """What a human at a terminal is actually shown and asked."""

    def _unproven(self) -> BranchClassification:
        return BranchClassification(
            name="doomed",
            tier=TIER_UNPROVEN,
            content_unique_paths=("only-here.txt",),
            detail="1 file(s) with unique content",
        )

    def test_the_exact_word_consents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda *_a: _ABANDON_CONFIRMATION_WORD)
        assert _confirm_abandonment_on_tty([self._unproven()], "cleanup") is True

    def test_a_bare_yes_does_not_consent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One keystroke is too easy to fat-finger for abandoning work."""
        monkeypatch.setattr("builtins.input", lambda *_a: "y")
        assert _confirm_abandonment_on_tty([self._unproven()], "cleanup") is False

    def test_whitespace_and_case_are_forgiven(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda *_a: "  ABANDON \n")
        assert _confirm_abandonment_on_tty([self._unproven()], "cleanup") is True

    def test_ctrl_d_is_a_refusal_not_a_traceback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A person pressing Ctrl-D has declined; that is an answer, not a crash."""

        def _eof() -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", lambda *_a: _eof())
        assert _confirm_abandonment_on_tty([self._unproven()], "cleanup") is False

    def test_nothing_is_written_to_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--format json`` writes JSON to stdout, so the prompt must not.

        ``input(prompt)`` writes its prompt to stdout, which would land inside
        the JSON stream of a caller piping this to a parser — and piping stdout
        does not stop stdin being a terminal, so the combination is reachable.
        """
        monkeypatch.setattr("builtins.input", lambda *_a: "no")

        _confirm_abandonment_on_tty([self._unproven()], "cleanup")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert _ABANDON_CONFIRMATION_WORD in captured.err

    def test_the_prompt_names_the_branch_and_the_stakes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A human cannot consent to something they were not told."""
        monkeypatch.setattr("builtins.input", lambda *_a: "no")

        _confirm_abandonment_on_tty([self._unproven()], "tidying up")

        stderr = capsys.readouterr().err
        assert "doomed" in stderr
        assert "1 file(s)" in stderr
        assert "tidying up" in stderr

    def test_provably_safe_branches_are_not_listed_as_at_risk(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Listing a merged branch as endangered would teach humans to skim."""
        monkeypatch.setattr("builtins.input", lambda *_a: "no")
        safe = BranchClassification(name="already-merged", tier=TIER_MERGED)

        _confirm_abandonment_on_tty([safe, self._unproven()], "")

        assert "already-merged" not in capsys.readouterr().err


class TestAPartialBatchIsReportedHonestly:
    """Plan 00253: ``refused`` does NOT mean nothing happened.

    Plan 00249 made a partial batch a real outcome — git can decline one branch
    after others are already gone — and deliberately KEEPS the recovery bundle in
    that case, because it is then the only route back to what WAS deleted. The CLI
    was never updated for either, so one hard-coded line could assert three
    untruths at once: that a deleted branch survived, that no bundle existed, and
    that ``--allow-unproven`` was the remedy when nothing was unproven.

    The report shape asserted here is not invented — it is the shape
    ``delete_branches`` really produces, and
    ``test_a_genuine_partial_batch_produces_this_shape`` proves that with real git
    rather than leaving these tests resting on a guess.
    """

    @staticmethod
    def _partial(bundle: Path | None) -> DeletionReport:
        """The real shape: one branch gone, one refused by git, bundle retained."""
        return DeletionReport(
            classifications=(
                BranchClassification(name="shipped", tier=TIER_MERGED_UNPUSHED),
                BranchClassification(name="stuck", tier=TIER_MERGED),
            ),
            deleted=("shipped",),
            bundle=bundle,
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
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial(None))

        assert "nothing was deleted" not in capsys.readouterr().err

    def test_it_names_what_actually_went(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial(None))

        err = capsys.readouterr().err
        assert "shipped" in err
        assert "PARTIALLY REFUSED" in err

    def test_it_discloses_the_surviving_bundle(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The only recovery route for the branch that WAS deleted.

        Withholding it is the most expensive of the three untruths: the branch is
        gone and the bundle is on disk, so a reader told "nothing was deleted" has
        no reason to look for it.
        """
        bundle = repo_with_abandoned_branch / "recovery.bundle"
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial(bundle))

        err = capsys.readouterr().err
        assert str(bundle) in err
        assert "git fetch" in err

    def test_it_does_not_offer_allow_unproven_for_a_git_refusal(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Advice that cannot help is worse than none — it sends the reader away."""
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial(None))

        assert "--allow-unproven" not in capsys.readouterr().err

    def test_it_still_offers_allow_unproven_when_a_tier_is_unproven(
        self,
        repo_with_abandoned_branch: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Control: the guidance must survive for the case it was written for."""
        report = DeletionReport(
            classifications=(BranchClassification(name="doomed", tier=TIER_UNPROVEN),),
            deleted=(),
            bundle=None,
            refused=True,
            blockers=("doomed: content found only here",),
        )
        self._run(monkeypatch, repo_with_abandoned_branch, report)

        err = capsys.readouterr().err
        assert "--allow-unproven" in err
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
        self._run(monkeypatch, repo_with_abandoned_branch, self._partial(None))
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
        subprocess.run(  # nosec B603 B607 - trusted system tool, list form
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

        bundle = tmp_path / "real.bundle"
        with patch.object(
            branch_safety, "delete_argv_for_tier", safe_delete_for_the_head_tier_only
        ):
            report = branch_safety.delete_branches(repo, ["shipped", "stuck"], bundle_path=bundle)

        assert report.refused is True, "the forced argv must make git decline `stuck`"
        assert report.deleted == ("shipped",), "and the other branch must be gone"
        assert report.bundle == bundle, "a bundle must survive when something went"
        assert bundle.exists()
