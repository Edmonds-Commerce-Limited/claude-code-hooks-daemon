"""Tests for GitHooksExecutableFixerHandler.

Covers detection of git's "not set as executable" hint and automatic
remediation that makes non-executable git hook files executable.
"""

import os
import stat
import subprocess  # nosec B404 - git used only to create real repos in test fixtures
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision, HookResult
from claude_code_hooks_daemon.handlers.post_tool_use.git_hooks_executable_fixer import (
    GitHooksExecutableFixerHandler,
)

_GIT_WARNING = (
    "hint: The '.git/hooks/pre-push' hook was ignored because " "it's not set as executable."
)


def _is_executable(path: str) -> bool:
    return bool(os.stat(path).st_mode & stat.S_IXUSR)


def _make_git_repo(tmp_path) -> str:
    """Create a real git repo and return its working-directory path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(  # nosec B603 B607 - trusted git, isolated tmp repo
        ["git", "init"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    return str(repo)


def _write_hook(repo: str, name: str, *, executable: bool) -> str:
    hooks_dir = os.path.join(repo, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    path = os.path.join(hooks_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\nexit 0\n")
    # Start as a plain readable/writable file (644)
    os.chmod(path, 0o644)
    if executable:
        os.chmod(path, 0o755)
    return path


class TestGitHooksExecutableFixerHandlerInit:
    @pytest.fixture
    def handler(self):
        return GitHooksExecutableFixerHandler()

    def test_name(self, handler):
        assert handler.name == "git-hooks-executable-fixer"

    def test_priority(self, handler):
        assert handler.priority == 27

    def test_non_terminal(self, handler):
        assert handler.terminal is False


class TestGitHooksExecutableFixerHandlerMatches:
    @pytest.fixture
    def handler(self):
        return GitHooksExecutableFixerHandler()

    def test_matches_warning_in_stderr(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_response": {"stdout": "", "stderr": _GIT_WARNING},
        }
        assert handler.matches(hook_input) is True

    def test_matches_warning_in_stdout(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_response": {"stdout": _GIT_WARNING, "stderr": ""},
        }
        assert handler.matches(hook_input) is True

    def test_no_match_without_warning(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_response": {"stdout": "Everything up-to-date", "stderr": ""},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_non_bash_tool(self, handler):
        hook_input = {
            "tool_name": "Write",
            "tool_response": {"stderr": _GIT_WARNING},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_missing_tool_response(self, handler):
        assert handler.matches({"tool_name": "Bash"}) is False


class TestGitHooksExecutableFixerHandlerHandle:
    @pytest.fixture
    def handler(self):
        return GitHooksExecutableFixerHandler()

    def test_makes_non_executable_hook_executable(self, handler, tmp_path):
        repo = _make_git_repo(tmp_path)
        hook = _write_hook(repo, "pre-push", executable=False)
        assert _is_executable(hook) is False

        result = handler.handle(
            {
                "tool_name": "Bash",
                "cwd": repo,
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        assert isinstance(result, HookResult)
        assert result.decision == Decision.ALLOW
        assert _is_executable(hook) is True

    def test_reports_fixed_hook_in_context(self, handler, tmp_path):
        repo = _make_git_repo(tmp_path)
        _write_hook(repo, "pre-push", executable=False)

        result = handler.handle(
            {
                "tool_name": "Bash",
                "cwd": repo,
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        joined = "\n".join(result.context or [])
        assert "pre-push" in joined

    def test_leaves_sample_files_untouched(self, handler, tmp_path):
        repo = _make_git_repo(tmp_path)
        sample = _write_hook(repo, "pre-commit.sample", executable=False)

        handler.handle(
            {
                "tool_name": "Bash",
                "cwd": repo,
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        assert _is_executable(sample) is False

    def test_already_executable_hook_not_reported(self, handler, tmp_path):
        repo = _make_git_repo(tmp_path)
        _write_hook(repo, "pre-commit", executable=True)
        _write_hook(repo, "pre-push", executable=False)

        result = handler.handle(
            {
                "tool_name": "Bash",
                "cwd": repo,
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        joined = "\n".join(result.context or [])
        assert "pre-push" in joined
        assert "pre-commit\n" not in joined and "pre-commit " not in joined

    def test_least_privilege_bits(self, handler, tmp_path):
        repo = _make_git_repo(tmp_path)
        hook = _write_hook(repo, "pre-push", executable=False)
        os.chmod(hook, 0o600)  # owner read/write only

        handler.handle(
            {
                "tool_name": "Bash",
                "cwd": repo,
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        mode = stat.S_IMODE(os.stat(hook).st_mode)
        # Owner gains execute; group/other (no read) gain nothing -> 0o700
        assert mode == 0o700

    def test_graceful_when_not_a_git_repo(self, handler, tmp_path):
        non_repo = tmp_path / "plain"
        non_repo.mkdir()

        result = handler.handle(
            {
                "tool_name": "Bash",
                "cwd": str(non_repo),
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        assert result.decision == Decision.ALLOW

    def test_graceful_when_git_unavailable(self, handler, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.post_tool_use."
            "git_hooks_executable_fixer.subprocess.run",
            _boom,
        )

        result = handler.handle(
            {
                "tool_name": "Bash",
                "cwd": "/tmp",
                "tool_response": {"stderr": _GIT_WARNING},
            }
        )

        assert result.decision == Decision.ALLOW
        joined = "\n".join(result.context or [])
        assert "git" in joined.lower()


class TestGitHooksExecutableFixerHandlerHelpers:
    def test_parse_hooks_dir_returns_none_on_failure(self):
        assert GitHooksExecutableFixerHandler._parse_hooks_dir(1, ".git/hooks", "/repo") is None

    def test_parse_hooks_dir_returns_none_on_empty_output(self):
        assert GitHooksExecutableFixerHandler._parse_hooks_dir(0, "   ", "/repo") is None

    def test_parse_hooks_dir_keeps_absolute_path(self):
        result = GitHooksExecutableFixerHandler._parse_hooks_dir(0, "/abs/hooks", None)
        assert result == Path("/abs/hooks")

    def test_parse_hooks_dir_resolves_relative_against_cwd(self):
        result = GitHooksExecutableFixerHandler._parse_hooks_dir(0, ".git/hooks", "/repo")
        assert result == Path("/repo/.git/hooks")

    def test_make_hooks_executable_skips_non_file_entries(self, tmp_path):
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "a_subdir").mkdir()  # non-file entry must be skipped
        fixed = GitHooksExecutableFixerHandler._make_hooks_executable(hooks_dir)
        assert fixed == []


class TestGitHooksExecutableFixerHandlerMetadata:
    @pytest.fixture
    def handler(self):
        return GitHooksExecutableFixerHandler()

    def test_get_claude_md_returns_guidance(self, handler):
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "executable" in guidance.lower()

    def test_get_acceptance_tests_returns_list(self, handler):
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) >= 1
