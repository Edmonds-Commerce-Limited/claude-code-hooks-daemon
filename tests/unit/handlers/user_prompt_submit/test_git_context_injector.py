"""Comprehensive tests for GitContextInjectorHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
    _MAX_SUPPRESSION_SECONDS,
    _MAX_TRACKED_SESSIONS,
    GitContextInjectorHandler,
)

_MOCK_PROJECT_ROOT = patch(
    "claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector.ProjectContext.project_root",
    return_value=Path("/fake/project"),
)


class TestGitContextInjectorHandler:
    """Test suite for GitContextInjectorHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return GitContextInjectorHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'git-context-injector'."""
        assert handler.name == "git-context-injector"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 20."""
        assert handler.priority == 20

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal (provides context)."""
        assert handler.terminal is False

    # matches() Tests
    def test_matches_always_returns_true(self, handler):
        """Should match all user prompt submissions."""
        hook_input = {"prompt": "Implement feature X"}
        assert handler.matches(hook_input) is True

    def test_matches_empty_input_returns_true(self, handler):
        """Should match even empty input."""
        hook_input = {}
        assert handler.matches(hook_input) is True

    # handle() - Git Available Tests
    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_adds_git_status_context(self, mock_run, _mock_ctx, handler):
        """Should add git status to context when git is available."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="On branch main\nnothing to commit",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "git" in context_text or "repository" in context_text
        assert "On branch main" in "\n".join(result.context)

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_adds_branch_name(self, mock_run, _mock_ctx, handler):
        """Should include current branch in context."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="On branch feature/new-handler\nChanges not staged",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        context_text = "\n".join(result.context)
        assert "feature/new-handler" in context_text

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_adds_uncommitted_changes_info(self, mock_run, _mock_ctx, handler):
        """Should include uncommitted changes info."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Changes not staged for commit:\n  modified: file.py",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        context_text = "\n".join(result.context).lower()
        assert "modified" in context_text

    # handle() - Git Not Available Tests
    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_handle_git_not_installed(self, mock_run, _mock_ctx, handler):
        """Should return silent allow when git is not installed."""
        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_not_a_git_repository(self, mock_run, _mock_ctx, handler):
        """Should return silent allow when not in a git repository."""
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="fatal: not a git repository",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_git_command_timeout(self, mock_run, _mock_ctx, handler):
        """Should handle git command timeout gracefully."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="git status", timeout=Timeout.SOCKET_CONNECT
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    # Result Properties Tests
    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_has_no_reason(self, mock_run, _mock_ctx, handler):
        """Should not provide reason."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.reason is None

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_has_no_guidance(self, mock_run, _mock_ctx, handler):
        """Should not provide guidance."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.guidance is None

    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_returns_hook_result_instance(self, mock_run, _mock_ctx, handler):
        """Should return HookResult instance."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert isinstance(result, HookResult)

    # Integration Tests
    @_MOCK_PROJECT_ROOT
    @patch("subprocess.run")
    def test_handle_calls_git_status_with_correct_args(self, mock_run, _mock_ctx, handler):
        """Should call git status with correct arguments."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Status")

        hook_input = {"prompt": "Test"}
        handler.handle(hook_input)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "git" in call_args[0][0]
        assert "status" in call_args[0][0]
        assert call_args[1].get("capture_output") is True
        assert call_args[1].get("text") is True


class TestTheStatusReadTakesNoIndexLock:
    """Plan 00246: this runs on EVERY user prompt, in the agent's own tree.

    `git status` refreshes the index and writes it back, taking
    `.git/index.lock` — so gathering context for a prompt was contending with
    whatever git command the agent was running at that moment. Of the three
    daemon paths that did this, this one and the status line are the frequent
    ones; the CLAUDE.md auto-commit merely holds the lock longest.
    """

    def _real_repo(self, tmp_path: Path) -> Path:
        import subprocess

        repo = tmp_path / "proj"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        for key, value in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(
                ["git", "config", "--local", key, value],
                cwd=repo,
                capture_output=True,
                check=True,
            )
        (repo / "f.txt").write_text("one\n")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
        return repo

    def test_injecting_context_does_not_rewrite_the_index(
        self, tmp_path: Path, git_index_watch
    ) -> None:
        repo = self._real_repo(tmp_path)
        handler = GitContextInjectorHandler()

        with (
            patch(
                "claude_code_hooks_daemon.handlers.user_prompt_submit."
                "git_context_injector.ProjectContext.project_root",
                return_value=repo,
            ),
            git_index_watch.expect_none(repo, "the per-prompt git context injection"),
        ):
            result = handler.handle({"prompt": "Test", "session_id": "lock-test"})

        assert result.context, "the handler must still report the status it read"

    def test_the_control_shows_bare_git_status_rewrites_it(
        self, tmp_path: Path, git_index_watch
    ) -> None:
        """Without this, the assertion above could pass vacuously."""
        import subprocess

        repo = self._real_repo(tmp_path)

        with git_index_watch.expect_one(repo, "bare git status"):
            subprocess.run(["git", "status"], cwd=repo, capture_output=True, check=True)


@_MOCK_PROJECT_ROOT
class TestOnlyInjectsOnChange:
    """Plan 00238 Task 4.1 — the duty is wanted, the repetition is not.

    Git state genuinely informs decisions, so this handler stays. But it was
    re-sending the SAME ~460-token payload on every prompt, and a second
    identical copy teaches nothing the first did not — the agent already has it.

    'Changed' is defined as the rendered payload differing from the one last
    injected FOR THIS SESSION. Two properties matter and are pinned below:
    keying by session, because sessions share one daemon and one session's
    injection must not silence another's; and a maximum suppression age,
    because context can be compacted away and a definition with no ceiling
    would silently stop informing — the exact failure the plan warned about.
    """

    @pytest.fixture
    def handler(self):
        return GitContextInjectorHandler()

    @staticmethod
    def _submit(handler, status: str, session: str = "s1"):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=status)):
            return handler.handle({"prompt": "Test", "session_id": session})

    def test_first_prompt_injects(self, _mock_ctx, handler):
        assert self._submit(handler, "On branch main").context

    def test_an_unchanged_status_is_not_re_injected(self, _mock_ctx, handler):
        self._submit(handler, "On branch main")
        assert self._submit(handler, "On branch main").context == []

    def test_a_changed_status_is_injected_again(self, _mock_ctx, handler):
        """Anti-vacuity companion: proves suppression tracks the CONTENT and is
        not simply 'inject once and never again'."""
        self._submit(handler, "On branch main")
        assert self._submit(handler, "On branch main\n\tmodified: a.py").context

    def test_a_return_to_a_previously_seen_status_still_injects(self, _mock_ctx, handler):
        """Only the LAST injection is compared. Reverting to an earlier state is
        news again, because what the agent last saw was the state in between."""
        self._submit(handler, "clean")
        self._submit(handler, "dirty")
        assert self._submit(handler, "clean").context

    def test_a_second_session_is_not_silenced_by_the_first(self, _mock_ctx, handler):
        """Sessions share one daemon (Plan 00127). A global 'last payload' would
        make whichever session prompted first mute the others."""
        self._submit(handler, "On branch main", session="s1")
        assert self._submit(handler, "On branch main", session="s2").context

    def test_suppression_expires_so_context_loss_is_recoverable(self, _mock_ctx, handler):
        """The ceiling that keeps 'changed' from meaning 'never again'.

        A compaction can evict the earlier injection; without a maximum age the
        agent would then have no git context until the repository happened to
        change.
        """
        self._submit(handler, "On branch main")
        later = handler._now() + _MAX_SUPPRESSION_SECONDS + 1.0
        handler._now = lambda: later

        assert self._submit(handler, "On branch main").context

    def test_the_tracked_session_count_is_bounded(self, _mock_ctx, handler):
        """A daemon runs for days; per-session state must not grow forever."""
        for index in range(_MAX_TRACKED_SESSIONS * 2):
            self._submit(handler, "On branch main", session=f"s{index}")

        assert len(handler._last_injected) <= _MAX_TRACKED_SESSIONS
