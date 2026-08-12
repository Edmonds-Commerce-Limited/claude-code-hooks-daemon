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

import pytest

from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_MERGED,
    TIER_UNPROVEN,
    BranchClassification,
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
