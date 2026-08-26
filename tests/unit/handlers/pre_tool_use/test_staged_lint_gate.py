"""Tests for StagedLintGateHandler (Plan 00268 Task 3.2).

The backstop half of the verifier/mutator work: `lint_on_edit` only ever sees
a file at the moment `Write`/`Edit` touches it, so a file that reached the
index by any OTHER route (`git add` of something written earlier in the
session, a `git commit` of pre-existing changes, a merge) is never linted
before it lands. This handler runs a CHEAP syntax check over every staged
Added/Copied/Modified file at `git commit` time, so the outcome is caught
however the commit was invoked -- the same "however it happened" framing as
`plan_qa_commit_gate`, applied to lint rather than plan hygiene.

Cost bounds are part of the contract, not an afterthought: only the
default/syntax tier ever runs (never the extended linter), and `max_files`
stands the whole check down rather than linting an unbounded set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, TestType
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import (
    StagedLintGateHandler,
)

_SAFE_PATH = "/srv/project"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _bash(command: str, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _patched_root(root: Path) -> Any:
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate."
        "ProjectContext.project_root"
    )
    return patch(target, return_value=root)


def _stage_file(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", relpath)


@pytest.fixture()
def handler() -> StagedLintGateHandler:
    return StagedLintGateHandler()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal git repo with an initial commit, ready to stage files into."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestInitialisation:
    def test_identity_and_priority(self, handler: StagedLintGateHandler) -> None:
        assert handler.handler_id == HandlerID.STAGED_LINT_GATE
        assert handler.priority == Priority.STAGED_LINT_GATE

    def test_is_not_terminal(self, handler: StagedLintGateHandler) -> None:
        assert handler.terminal is False


class TestMatches:
    def test_ignores_non_bash_tools(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {"file_path": "/x"}}) is False

    def test_matches_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash('git commit -m "x"')) is True

    def test_matches_git_commit_with_global_options(self, handler: StagedLintGateHandler) -> None:
        """`git -C /path commit` read "/path" as the subcommand and walked past
        an earlier guard in this codebase -- GIT_INVOCATION exists for it."""
        assert handler.matches(_bash(f"git -C {_SAFE_PATH} commit -m x")) is True

    def test_matches_env_prefixed_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash("env git commit -m x")) is True

    def test_matches_line_continued_git_commit(self, handler: StagedLintGateHandler) -> None:
        assert handler.matches(_bash("git \\\n  commit -m x")) is True

    def test_matches_git_commit_after_a_chained_command(
        self, handler: StagedLintGateHandler
    ) -> None:
        assert handler.matches(_bash("npm run build && git commit -m x")) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff --cached",
            'gh pr create --title "x" --body "y"',
            "",
        ],
    )
    def test_does_not_match_non_commit_commands(
        self, handler: StagedLintGateHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False


class TestNoStagedLintableFiles:
    def test_allows_silently_when_nothing_is_staged(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_allows_silently_when_staged_files_have_no_strategy(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "notes.txt", "just some prose\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestSyntaxFailureIsSurfaced:
    def test_a_failing_staged_python_file_is_named_with_its_diagnosis(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW  # warn mode: the default
        assert result.context
        rendered = " ".join(result.context)
        assert "broken.py" in rendered

    def test_a_clean_staged_python_file_produces_no_finding(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestModes:
    def test_warn_mode_allows_with_context(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert result.context

    def test_block_mode_denies(self, handler: StagedLintGateHandler, repo: Path) -> None:
        handler._mode = "block"
        _stage_file(repo, "broken.py", "def broken(\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.DENY
        assert result.reason
        assert "broken.py" in result.reason

    def test_a_clean_commit_allows_silently_in_block_mode(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._mode = "block"
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestMaxFiles:
    def test_standing_down_names_how_many_files_were_skipped(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        handler._max_files = 1
        _stage_file(repo, "a.py", "def a() -> None:\n    return None\n")
        _stage_file(repo, "b.py", "def b() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW
        assert result.context
        rendered = " ".join(result.context)
        assert "2" in rendered

    def test_a_non_int_option_is_ignored_rather_than_crashing(
        self, handler: StagedLintGateHandler, repo: Path
    ) -> None:
        """Options arrive by blind setattr from YAML, so the handler must not
        trust the type it is handed."""
        handler._max_files = "not-a-number"
        _stage_file(repo, "clean.py", "def clean() -> None:\n    return None\n")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"'))

        assert result.decision == Decision.ALLOW


class TestForeignRepoExempt:
    def test_a_commit_inside_a_nested_or_foreign_repo_is_ignored(
        self, handler: StagedLintGateHandler, repo: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other-repo"
        other.mkdir()
        _git(other, "init")
        _git(other, "config", "user.email", "t@example.com")
        _git(other, "config", "user.name", "T")
        (other / "broken.py").write_text("def broken(\n")
        _git(other, "add", "-A")

        with _patched_root(repo):
            result = handler.handle(_bash('git commit -m "x"', cwd=str(other)))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestGuidance:
    def test_publishes_resident_guidance(self, handler: StagedLintGateHandler) -> None:
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "staged" in guidance.lower()

    def test_publishes_acceptance_tests(self, handler: StagedLintGateHandler) -> None:
        tests = handler.get_acceptance_tests()

        assert tests
        for test in tests:
            assert test.test_type == TestType.ADVISORY
            assert test.requires_main_thread is False
