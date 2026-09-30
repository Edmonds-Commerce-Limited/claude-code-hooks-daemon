"""Plan 00466 lifecycle round 9b: the CLI takes the caller's logical root.

A launcher that names the root resolved hands the CLI the root as its caller
reached it, links unresolved, in ``CLAUDE_HOOKS_DAEMON_CALLER_ROOT``. ``main``
takes it out of the environment, so a daemon a start forks never carries a
caller's hint, and the relaunch of a start naming no root passes it on.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.process_verification import CALLER_ROOT_ENV_VAR

#: A pid no process has, for the relaunch's stubbed spawn to return.
_NONEXISTENT_PID = 2**22 + 7


def _run_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> argparse.Namespace:
    """Run ``main`` for a ``stop`` whose command is stubbed; return its arguments."""
    seen: list[argparse.Namespace] = []

    def _stop(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    monkeypatch.setattr(sys, "argv", ["cli", "--project-root", str(tmp_path), "stop"])
    monkeypatch.setattr(cli, "cmd_stop", _stop)
    assert cli.main() == 0
    return seen[0]


class TestMainTakesTheCallersLogicalRoot:
    def test_it_is_taken_out_of_the_environment_onto_the_arguments(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(CALLER_ROOT_ENV_VAR, "/link/project")

        args = _run_main(monkeypatch, tmp_path)

        assert args.caller_logical_root == "/link/project"
        assert CALLER_ROOT_ENV_VAR not in os.environ

    @pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
    def test_none_is_taken_when_the_caller_names_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
    ) -> None:
        if value is None:
            monkeypatch.delenv(CALLER_ROOT_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(CALLER_ROOT_ENV_VAR, value)

        assert _run_main(monkeypatch, tmp_path).caller_logical_root is None


class TestTheRelaunchPassesItOn:
    @pytest.mark.parametrize("caller_root", ["/link/project", None], ids=["named", "none"])
    def test_the_relaunched_start_is_given_the_callers_logical_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caller_root: str | None
    ) -> None:
        monkeypatch.delenv(CALLER_ROOT_ENV_VAR, raising=False)
        args = argparse.Namespace(
            command="start",
            project_root=None,
            global_project_root=None,
            pid_file=None,
            socket=None,
            caller_logical_root=caller_root,
        )
        with (
            patch.object(cli, "get_project_path", return_value=tmp_path),
            patch.object(os, "posix_spawn", return_value=_NONEXISTENT_PID) as spawn,
            patch.object(os, "waitpid", return_value=(_NONEXISTENT_PID, 0)),
            pytest.raises(SystemExit) as exited,
        ):
            cli._reexec_daemon_launch_with_explicit_project_root(args)

        assert exited.value.code == 0
        env = spawn.call_args.args[2]
        assert env.get(CALLER_ROOT_ENV_VAR) == caller_root
