"""Where a parsed ``git`` invocation runs, and when that cannot be stated."""

import inspect
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    dash_c_values,
    invocation_directory,
    placed_moves,
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

    @pytest.mark.parametrize("prefix", ["builtin", "command", "command -p"])
    def test_a_cd_behind_a_builtin_or_command_prefix_moves(self, prefix: str) -> None:
        run = _only(f"{prefix} cd sub && git status")
        assert invocation_directory(run, Path("/start")) == Path("/start/sub")

    @pytest.mark.parametrize("prefix", ["command -v", "command -V"])
    def test_command_lookup_flags_do_not_move(self, prefix: str) -> None:
        run = _only(f"{prefix} cd && git status")
        assert invocation_directory(run, Path("/start")) == Path("/start")


@pytest.fixture()
def checkout(tmp_path: Path) -> Path:
    """A directory holding a ``.git`` entry, with a subdirectory the hook starts in."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "sub" / "inner").mkdir(parents=True)
    return root


class TestCwdExpansionsAreSteps:
    """A ``cd`` operand spelled as a cwd expansion is placed, as path judgement places it."""

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$(git rev-parse --show-toplevel)" && git commit -m x',
            'cd "$(git  rev-parse --show-toplevel )"; git commit -m x',
        ],
    )
    def test_show_toplevel_is_the_repository_root(self, checkout: Path, command: str) -> None:
        run = _only(command)
        start = checkout / "sub"
        assert placement_problem(run, start) is None
        assert invocation_directory(run, start) == checkout

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$PWD" && git commit -m x',
            'cd "${PWD}" && git commit -m x',
            'cd "$(pwd)" && git commit -m x',
        ],
    )
    def test_pwd_spellings_are_the_start_directory(self, checkout: Path, command: str) -> None:
        run = _only(command)
        start = checkout / "sub"
        assert placement_problem(run, start) is None
        assert invocation_directory(run, start) == start

    def test_a_later_step_is_read_in_the_directory_the_earlier_cd_reached(
        self, checkout: Path
    ) -> None:
        run = _only('cd sub && cd "$PWD/inner" && git commit -m x')
        assert placement_problem(run, checkout) is None
        assert invocation_directory(run, checkout) == checkout / "sub" / "inner"

    def test_dash_c_is_read_in_the_directory_the_cd_chain_reached(self, checkout: Path) -> None:
        run = _only('cd sub && git -C "$(pwd)/inner" commit -m x')
        assert placement_problem(run, checkout) is None
        assert invocation_directory(run, checkout) == checkout / "sub" / "inner"

    def test_a_relative_start_directory_resolves_nothing(self) -> None:
        run = _only('cd "$PWD" && git commit -m x')
        assert placement_problem(run, Path("relative")) is not None

    def test_no_repository_leaves_the_toplevel_expansion_reported(self, tmp_path: Path) -> None:
        run = _only('cd "$(git rev-parse --show-toplevel)" && git commit -m x')
        assert "needs an expansion" in (placement_problem(run, tmp_path / "nowhere") or "")

    @pytest.mark.parametrize(
        "command",
        [
            "cd $PROJ && git commit -m x",
            'cd "$PROJ" && git commit -m x',
            'cd "$PWD/$SUB" && git commit -m x',
            'cd "$(dirname "$PWD")" && git commit -m x',
            "cd - && git commit -m x",
        ],
    )
    def test_any_other_expansion_stays_reported(self, checkout: Path, command: str) -> None:
        assert placement_problem(_only(command), checkout / "sub") is not None

    def test_an_unplaced_cd_leaves_the_next_expansion_unplaced(self, checkout: Path) -> None:
        run = _only('cd "$PROJ" && cd "$PWD" && git commit -m x')
        assert placement_problem(run, checkout) is not None


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
        assert placement_problem(_only(command), Path("/start")) is None

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
        assert placement_problem(_only(command), Path("/start")) is not None


class TestUnresolvableHomeSteps:
    """A `~name` step is reported, never expanded (it raised RuntimeError for an unknown user)."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd ~nosuchuser-zz && git commit -m x",
            "cd ~- && git commit -m x",
            "cd ~+ && git commit -m x",
            "cd ~nosuchuser-zz/sub && git commit -m x",
        ],
    )
    def test_reported_not_raised(self, checkout: Path, command: str) -> None:
        problem = placement_problem(_only(command), checkout)
        assert problem is not None
        assert "needs an expansion" in problem

    def test_a_later_expansion_after_a_home_step_is_not_resolved(self, checkout: Path) -> None:
        run = _only('cd ~nosuchuser-zz && cd "$PWD" && git commit -m x')
        assert placement_problem(run, checkout) is not None

    def test_the_cwd_is_required(self) -> None:
        parameter = inspect.signature(placement_problem).parameters["cwd"]
        assert parameter.default is inspect.Parameter.empty


class TestPlacedMoves:
    """The ``cd`` chain read as the shell reads it, for a caller with no git run (ledger N403)."""

    def test_a_plain_chain_is_returned_as_written(self) -> None:
        assert placed_moves(("sub", "..", "x"), Path("/start")) == (("sub", "..", "x"), None)

    def test_a_pwd_spelling_is_read_in_the_directory_reached_so_far(self) -> None:
        placed, problem = placed_moves(("sub", "$PWD/inner"), Path("/start"))
        assert problem is None
        assert placed == ("sub", "/start/sub/inner")

    def test_a_home_step_is_made_absolute(self) -> None:
        placed, problem = placed_moves(("~/work",), Path("/start"))
        assert problem is None
        assert placed == (str(Path("~/work").expanduser()),)

    @pytest.mark.parametrize("step", ["$UNKNOWN", "dir/*", "~nosuchuser-zz"])
    def test_an_unplaceable_step_is_reported(self, step: str) -> None:
        _placed, problem = placed_moves(("sub", step), Path("/start"))
        assert problem is not None
        assert "needs an expansion" in problem

    def test_a_step_that_names_no_directory_is_reported(self) -> None:
        _placed, problem = placed_moves(("sub", None), Path("/start"))
        assert problem is not None
        assert "names no directory" in problem

    def test_a_relative_cwd_resolves_nothing(self) -> None:
        _placed, problem = placed_moves(("$PWD/x",), Path("rel"))
        assert problem is not None
