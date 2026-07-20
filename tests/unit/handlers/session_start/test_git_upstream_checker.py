"""Tests for the git_upstream_checker SessionStart handler (Plan 00178).

On new sessions the handler runs a full ``git fetch --all --prune`` then, if the
current branch is behind its upstream, applies a configurable ``mode``:
``warn`` (default), ``agent-pull``, or ``auto-pull``. The git mechanism lives in
``utils/git_sync``; these tests patch it so only handler *policy* is exercised.
"""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.git_upstream_checker import (
    GitUpstreamCheckerHandler,
)
from claude_code_hooks_daemon.utils import git_sync

_ROOT = "claude_code_hooks_daemon.handlers.session_start.git_upstream_checker.ProjectContext.project_root"
_FETCH = "claude_code_hooks_daemon.utils.git_sync.fetch_all_prune"
_STATUS = "claude_code_hooks_daemon.utils.git_sync.upstream_status"
_CLEAN = "claude_code_hooks_daemon.utils.git_sync.working_tree_clean"
_PULL = "claude_code_hooks_daemon.utils.git_sync.pull_ff_only"

_FAKE_ROOT = Path("/fake/project")


def _session_start_input(transcript_path: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {HookInputField.HOOK_EVENT_NAME: "SessionStart"}
    if transcript_path is not None:
        hook_input[HookInputField.TRANSCRIPT_PATH] = transcript_path
    return hook_input


def _status(behind: int, ahead: int = 0) -> git_sync.UpstreamStatus:
    return git_sync.UpstreamStatus(
        branch="main", upstream="origin/main", behind=behind, ahead=ahead
    )


def _make(mode: str = "warn", auto_fetch: bool = True) -> GitUpstreamCheckerHandler:
    handler = GitUpstreamCheckerHandler()
    handler._mode = mode
    handler._auto_fetch = auto_fetch
    return handler


class TestInit:
    def test_handler_id(self) -> None:
        assert GitUpstreamCheckerHandler().handler_id.config_key == "git_upstream_checker"

    def test_non_terminal(self) -> None:
        assert GitUpstreamCheckerHandler().terminal is False

    def test_priority(self) -> None:
        assert GitUpstreamCheckerHandler().priority == 56

    def test_default_mode_is_warn(self) -> None:
        assert GitUpstreamCheckerHandler()._mode == "warn"

    def test_auto_fetch_defaults_true(self) -> None:
        assert GitUpstreamCheckerHandler()._auto_fetch is True

    @pytest.mark.parametrize("tag", [HandlerTag.ADVISORY, HandlerTag.GIT, HandlerTag.NON_TERMINAL])
    def test_tags(self, tag: str) -> None:
        assert tag in GitUpstreamCheckerHandler().tags


class TestMatches:
    def test_matches_new_session_no_transcript(self) -> None:
        assert _make().matches(_session_start_input()) is True

    def test_matches_empty_transcript(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            pass
        try:
            assert _make().matches(_session_start_input(tmp.name)) is True
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_no_match_resume_session(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp.write("x" * 200)
        try:
            assert _make().matches(_session_start_input(tmp.name)) is False
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_matches_nonexistent_transcript(self) -> None:
        assert _make().matches(_session_start_input("/nonexistent/path.jsonl")) is True


class TestFetchBehaviour:
    def test_auto_fetch_true_calls_fetch(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True) as fetch,
            patch(_STATUS, return_value=_status(0)),
        ):
            _make(auto_fetch=True).handle(_session_start_input())
        fetch.assert_called_once_with(_FAKE_ROOT)

    def test_auto_fetch_false_skips_fetch(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True) as fetch,
            patch(_STATUS, return_value=_status(0)),
        ):
            _make(auto_fetch=False).handle(_session_start_input())
        fetch.assert_not_called()


class TestSilentPaths:
    def test_in_sync_is_silent(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(0)),
        ):
            result = _make().handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_no_upstream_is_silent(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=False),
            patch(_STATUS, return_value=None),
        ):
            result = _make().handle(_session_start_input())
        assert result.context == []


class TestWarnMode:
    def test_behind_warns_to_pull(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(3)),
        ):
            result = _make(mode="warn").handle(_session_start_input())
        text = "\n".join(result.context)
        assert result.decision == Decision.ALLOW
        assert "git pull" in text
        assert "behind" in text.lower()
        assert "3" in text
        assert "origin/main" in text

    def test_diverged_mentions_divergence(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2, ahead=1)),
        ):
            result = _make(mode="warn").handle(_session_start_input())
        text = "\n".join(result.context).lower()
        assert "diverged" in text

    def test_unknown_mode_falls_back_to_warn(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(1)),
        ):
            result = _make(mode="bogus-mode").handle(_session_start_input())
        text = "\n".join(result.context)
        assert "git pull" in text


class TestAgentPullMode:
    def test_behind_injects_directive(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2)),
        ):
            result = _make(mode="agent-pull").handle(_session_start_input())
        text = "\n".join(result.context)
        assert "git pull" in text
        assert "agent-pull" in text
        # A directive tells the agent to act now.
        assert "ACTION REQUIRED" in text


class TestAutoPullMode:
    def test_clean_fast_forward_pulls_and_reports(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2)),
            patch(_CLEAN, return_value=True),
            patch(
                _PULL, return_value=git_sync.PullResult(ok=True, detail="fast-forwarded")
            ) as pull,
        ):
            result = _make(mode="auto-pull").handle(_session_start_input())
        pull.assert_called_once_with(_FAKE_ROOT)
        text = "\n".join(result.context).lower()
        assert "pull" in text
        assert "auto-pull" in "\n".join(result.context)

    def test_dirty_tree_degrades_to_warn_without_pulling(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2)),
            patch(_CLEAN, return_value=False),
            patch(_PULL) as pull,
        ):
            result = _make(mode="auto-pull").handle(_session_start_input())
        pull.assert_not_called()
        text = "\n".join(result.context).lower()
        assert "git pull" in text
        # Explains why it did not auto-pull.
        assert "dirty" in text or "uncommitted" in text or "clean" in text

    def test_diverged_degrades_to_warn_without_pulling(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2, ahead=1)),
            patch(_CLEAN, return_value=True),
            patch(_PULL) as pull,
        ):
            result = _make(mode="auto-pull").handle(_session_start_input())
        pull.assert_not_called()
        text = "\n".join(result.context).lower()
        assert "diverged" in text

    def test_ff_failure_degrades_to_warn(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2)),
            patch(_CLEAN, return_value=True),
            patch(
                _PULL, return_value=git_sync.PullResult(ok=False, detail="could not fast-forward")
            ),
        ):
            result = _make(mode="auto-pull").handle(_session_start_input())
        text = "\n".join(result.context)
        assert "git pull" in text
        assert "could not fast-forward" in text


class TestDefensivePaths:
    def test_matches_handles_stat_error(self) -> None:
        # If probing the transcript raises (OSError/ValueError), _is_resume_session
        # must treat it as "not a resume" (matches True) rather than crash.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp.write("x" * 200)
        try:
            with patch("pathlib.Path.stat", side_effect=OSError("boom")):
                assert _make().matches(_session_start_input(tmp.name)) is True
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_project_context_uninitialised_falls_back_to_cwd(self) -> None:
        with (
            patch(_ROOT, side_effect=RuntimeError("no context")),
            patch(_FETCH, return_value=False),
            patch(_STATUS, return_value=None),
        ):
            result = _make().handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_agent_pull_diverged_mentions_rebase(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2, ahead=1)),
        ):
            result = _make(mode="agent-pull").handle(_session_start_input())
        text = "\n".join(result.context).lower()
        assert "diverged" in text
        assert "rebase" in text

    def test_auto_pull_success_includes_nonstandard_detail(self) -> None:
        with (
            patch(_ROOT, return_value=_FAKE_ROOT),
            patch(_FETCH, return_value=True),
            patch(_STATUS, return_value=_status(2)),
            patch(_CLEAN, return_value=True),
            patch(_PULL, return_value=git_sync.PullResult(ok=True, detail="Updating 3 files")),
        ):
            result = _make(mode="auto-pull").handle(_session_start_input())
        text = "\n".join(result.context)
        assert "Updating 3 files" in text


class TestGuidanceAndAcceptance:
    def test_get_claude_md_documents_modes(self) -> None:
        md = GitUpstreamCheckerHandler().get_claude_md()
        assert md is not None
        assert "warn" in md
        assert "auto-pull" in md
        assert "agent-pull" in md

    def test_has_acceptance_tests(self) -> None:
        tests = GitUpstreamCheckerHandler().get_acceptance_tests()
        assert len(tests) >= 1
        assert tests[0].title
