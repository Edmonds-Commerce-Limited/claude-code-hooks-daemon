"""The git metadata calls around WorktreeCreate follow host load (Plan 00474 N623, N624).

Class: a hard failure gated on a fixed wall-clock budget for a call whose duration
follows host load. The branch-cap verdict and the creator record run inside the
event, whose budget is pinned in ``Timeout.EVENT_HANDLER_BUDGET``; each is a base
scaled by load and bounded by a ceiling that budget is sized for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import branch_creation, branch_inventory, branch_records
from claude_code_hooks_daemon.utils import git_config_write

_SATURATED = (700.0, 700.0, 700.0)
_LOAD_PATH = "claude_code_hooks_daemon.utils.load_scaling.os.getloadavg"


def _result(args: tuple[str, ...], code: int, stderr: str = "") -> Any:
    return subprocess.CompletedProcess(["git", *args], code, "", stderr)


class TestCreatorRecord:
    def test_each_key_write_waits_for_the_lock_within_the_event_ceilings(
        self, tmp_path: Path
    ) -> None:
        calls: list[dict[str, Any]] = []

        def fake_write(repo: Path, *args: str, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return _result(args, 0)

        with patch.object(branch_records, "run_git_config_write", fake_write):
            assert branch_records.write_creator(tmp_path, "b", "s:", "worktree_create")
        assert len(calls) == Timeout.GIT_BRANCH_RECORD_CALLS
        for kwargs in calls:
            assert kwargs["ceiling"] == Timeout.GIT_CREATOR_LOCK_WAIT_MAX
            assert kwargs["timeout"] <= Timeout.GIT_BRANCH_METADATA_MAX

    def test_a_held_lock_is_waited_out_and_the_record_lands(self, tmp_path: Path) -> None:
        held = {"left": 2}
        written: list[tuple[str, ...]] = []

        def fake_run_git(repo: Path, *args: str, **_: Any) -> Any:
            if held["left"]:
                held["left"] -= 1
                return _result(args, 255, "error: could not lock config file .git/config: busy")
            written.append(args)
            return _result(args, 0)

        with patch.object(git_config_write, "run_git", fake_run_git):
            assert branch_records.write_creator(tmp_path, "b", "s:", "worktree_create")
        assert len(written) == Timeout.GIT_BRANCH_RECORD_CALLS

    def test_a_lock_held_past_the_wait_is_a_logged_false_never_a_raise(
        self, tmp_path: Path
    ) -> None:
        def always_held(repo: Path, *args: str, **_: Any) -> Any:
            return _result(args, 255, "error: could not lock config file .git/config: busy")

        with (
            patch.object(git_config_write, "run_git", always_held),
            patch.object(Timeout, "GIT_CREATOR_LOCK_WAIT_MAX", 0.2),
            patch.object(Timeout, "GIT_CONFIG_LOCK_WAIT", 0.1),
        ):
            assert branch_records.write_creator(tmp_path, "b", "s:", "worktree_create") is False


class TestBranchCapVerdictCalls:
    @pytest.mark.parametrize(
        "call",
        [
            lambda repo: branch_creation._read_refs(repo, BranchesConfig()),
            lambda repo: branch_inventory._worktrees(repo),
        ],
        ids=["for-each-ref", "worktree-list"],
    )
    def test_the_call_follows_host_load_up_to_the_ceiling(self, tmp_path: Path, call: Any) -> None:
        seen: list[float] = []

        def fake_run_git(repo: Path, *args: str, timeout: float = 0, **_: Any) -> Any:
            seen.append(timeout)
            return _result(args, 1, "boom")

        with (
            patch.object(branch_creation, "run_git", fake_run_git),
            patch.object(branch_inventory, "run_git", fake_run_git),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            call(tmp_path)
        assert seen == [Timeout.GIT_BRANCH_METADATA_MAX]

    def test_the_merged_listing_follows_host_load(self, tmp_path: Path) -> None:
        seen: list[float] = []

        def fake_run_git(repo: Path, *args: str, timeout: float = 0, **_: Any) -> Any:
            seen.append(timeout)
            return _result(args, 1, "boom")

        refs = [branch_creation._Ref("main", "1" * 40, 0.0, True, "refs/heads/main", False, "")]
        with (
            patch.object(branch_creation, "run_git", fake_run_git),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            branch_creation._merged_refnames(tmp_path, BranchesConfig(), refs, "main")
        assert seen == [Timeout.GIT_BRANCH_METADATA_MAX]
