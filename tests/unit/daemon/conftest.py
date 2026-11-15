"""Shared fixtures for the daemon CLI tests."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils import git_sync


@pytest.fixture
def default_branch_is_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the default branch to ``main`` for tests that fake git behind a made-up path.

    ``worktree-reap`` validates ``--base-branch`` against the resolved default, which
    needs a real repository; a fake-git test has none.
    """
    monkeypatch.setattr(git_sync, "resolve_default_branch", lambda _config, _repo: "main")
