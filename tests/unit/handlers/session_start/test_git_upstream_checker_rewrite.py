"""git_upstream_checker must not advise `git pull` after an upstream rewrite.

Ordinary divergence and a history rewrite are indistinguishable from ahead/
behind counts alone, but the correct advice is opposite. After a rewrite (a
``filter-repo`` run to strip secrets, say) every local commit is a pre-rewrite
duplicate, so `git pull` merges the whole contaminated history back in and
re-publishes precisely what the rewrite destroyed.

This handler is the one thing that speaks up on a fresh session in that state,
so its advice being wrong is the most consequential sentence it can emit.

The discriminating signal is ``git_sync.upstream_tree_matches`` — identical
trees under different commit shas. These tests patch it directly; the git-level
behaviour of that signal is covered in
``tests/unit/utils/test_git_sync_rewrite_detection.py``.
"""

from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.handlers.session_start.git_upstream_checker import (
    GitUpstreamCheckerHandler,
)
from claude_code_hooks_daemon.utils import git_sync

_ROOT = (
    "claude_code_hooks_daemon.handlers.session_start."
    "git_upstream_checker.ProjectContext.project_root"
)
_FETCH = "claude_code_hooks_daemon.utils.git_sync.fetch_all"
_STATUS = "claude_code_hooks_daemon.utils.git_sync.upstream_status"
_GONE = "claude_code_hooks_daemon.utils.git_sync.gone_branches"
_TREE_MATCHES = "claude_code_hooks_daemon.utils.git_sync.upstream_was_rewritten"

_PULL_ADVICE = "git pull"


def _session_start_input() -> dict[str, Any]:
    return {HookInputField.HOOK_EVENT_NAME: "SessionStart"}


def _diverged() -> git_sync.UpstreamStatus:
    """The exact shape a 1:1 history rewrite produces."""
    return git_sync.UpstreamStatus(branch="main", upstream="origin/main", behind=1562, ahead=1562)


def _make(mode: str = "warn") -> GitUpstreamCheckerHandler:
    handler = GitUpstreamCheckerHandler()
    handler._mode = mode
    handler._auto_fetch = False
    return handler


def _context(mode: str, *, tree_matches: bool) -> str:
    with (
        patch(_ROOT, return_value="/fake/project"),
        patch(_FETCH, return_value=True),
        patch(_STATUS, return_value=_diverged()),
        patch(_GONE, return_value=[]),
        patch(_TREE_MATCHES, return_value=tree_matches),
    ):
        result = _make(mode).handle(_session_start_input())
    return "\n".join(result.context or [])


class TestRewriteDivergence:
    """Trees identical + shas different => never advise a merge."""

    def test_warn_mode_does_not_recommend_pull(self) -> None:
        text = _context("warn", tree_matches=True)

        assert _PULL_ADVICE not in text, (
            "Advised a pull after an upstream history rewrite. That merges every "
            f"pre-rewrite commit back in. Emitted:\n{text}"
        )

    def test_agent_pull_mode_does_not_order_a_pull(self) -> None:
        """agent-pull is the most dangerous mode: it instructs, not suggests."""
        text = _context("agent-pull", tree_matches=True)

        assert (
            _PULL_ADVICE not in text
        ), f"agent-pull ordered a pull after a rewrite. Emitted:\n{text}"

    def test_auto_pull_mode_does_not_recommend_pull(self) -> None:
        text = _context("auto-pull", tree_matches=True)

        assert (
            _PULL_ADVICE not in text
        ), f"auto-pull advised a pull after a rewrite. Emitted:\n{text}"

    def test_names_the_rewrite_so_the_reader_can_act(self) -> None:
        text = _context("warn", tree_matches=True)

        assert (
            "rewritten" in text.lower()
        ), f"Suppressed the pull advice but never explained why. Emitted:\n{text}"
        assert "identical" in text.lower() or "same content" in text.lower(), (
            "Did not state the evidence (the trees match), so a reader cannot "
            f"check the diagnosis. Emitted:\n{text}"
        )

    def test_still_reports_the_divergence_itself(self) -> None:
        """Suppressing the ADVICE must not suppress the FACT."""
        text = _context("warn", tree_matches=True)

        assert "diverged" in text.lower()
        assert "1562" in text


class TestOrdinaryDivergenceIsUnchanged:
    """Different trees => genuinely different work => merging is still right."""

    def test_warn_mode_still_recommends_pull(self) -> None:
        text = _context("warn", tree_matches=False)

        assert _PULL_ADVICE in text, (
            "Ordinary divergence lost its pull advice — the rewrite guard is "
            f"over-matching. Emitted:\n{text}"
        )

    def test_agent_pull_mode_still_orders_a_pull(self) -> None:
        text = _context("agent-pull", tree_matches=False)

        assert _PULL_ADVICE in text
