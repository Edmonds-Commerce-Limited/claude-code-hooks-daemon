"""Where a parsed ``git`` invocation runs, and when that cannot be stated."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    dash_c_values,
    invocation_directory,
    placement_problem,
)


def _only(command: str) -> GitInvocation:
    runs = git_invocations(command)
    assert len(runs) == 1
    return runs[0]


class TestDashCValues:
    def test_collects_every_dash_c_in_order(self) -> None:
        run = _only("git -C /a -C b status")
        assert dash_c_values(run.global_options) == ["/a", "b"]

    def test_none_without_dash_c(self) -> None:
        assert dash_c_values(_only("git --no-pager status").global_options) == []


class TestInvocationDirectory:
    def test_starts_at_cwd(self) -> None:
        assert invocation_directory(_only("git status"), Path("/start")) == Path("/start")

    def test_cd_then_dash_c_compose(self) -> None:
        run = _only("cd sub && git -C inner status")
        assert invocation_directory(run, Path("/start")) == Path("/start/sub/inner")

    def test_absolute_dash_c_replaces_cwd(self) -> None:
        run = _only("git -C /elsewhere status")
        assert invocation_directory(run, Path("/start")) == Path("/elsewhere")


class TestPlacementProblem:
    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git -C /abs/path status",
            "cd /abs && git status",
            "cd ~/work && git status",
        ],
    )
    def test_placeable(self, command: str) -> None:
        assert placement_problem(_only(command)) is None

    @pytest.mark.parametrize(
        "command",
        [
            "GIT_DIR=/x git status",
            "git --git-dir=/x status",
            "git --work-tree /x status",
            "git -C '$D' status",
            "git -C /a/* status",
            "cd - && git status",
            "cd a b && git status",
            "cd ~other && git status",
        ],
    )
    def test_unplaceable(self, command: str) -> None:
        assert placement_problem(_only(command)) is not None
