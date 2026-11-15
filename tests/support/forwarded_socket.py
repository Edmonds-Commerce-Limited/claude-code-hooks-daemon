"""Test support: prove a remote-touching git call carries the forwarded agent socket."""

from __future__ import annotations

from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest

from claude_code_hooks_daemon.utils import remote_refs
from claude_code_hooks_daemon.utils.git_repo import run_git

FORWARDED = "/run/forwarded-agent.sock"
NEVER_TAKEN = ("GIT_SSH_COMMAND", "GIT_SSH", "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AGENT_PID")


def spy_remote_env(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, subcommand: str
) -> list[Mapping[str, str] | None]:
    """Forward ``FORWARDED`` and record the env of each ``module.run_git(<subcommand>)``."""
    monkeypatch.setattr(remote_refs, "forwarded_agent_socket", lambda: FORWARDED)
    seen: list[Mapping[str, str] | None] = []

    def _spy(repo: Any, *args: str, **kwargs: Any) -> Any:
        if args and args[0] == subcommand:
            seen.append(kwargs.get("env"))
        return run_git(repo, *args, **kwargs)

    monkeypatch.setattr(module, "run_git", _spy)
    return seen


def assert_forwarded(seen: list[Mapping[str, str] | None], expected_calls: int = 1) -> None:
    """Every recorded call carried the socket and none carried a command-running variable."""
    assert len(seen) == expected_calls
    for env in seen:
        assert env is not None
        assert env["SSH_AUTH_SOCK"] == FORWARDED
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert not any(name in env for name in NEVER_TAKEN)

