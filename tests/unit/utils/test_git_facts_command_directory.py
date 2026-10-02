"""Ledger 00474 N299 and N301: where a commit's pathspecs are read, and what that costs.

N299: ``cd sub && git commit -m x f.txt`` records ``sub/f.txt``, so its pathspec
must be read from ``sub``, not from the repository root.

N301: the "every pathspec selects something" question is one git call however
many paths the commit names. These tests count invocations, not seconds.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils import git_facts as git_facts_module
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    CommitForm,
    CommitReading,
    read_commit_form,
)
from claude_code_hooks_daemon.utils.git_facts import (
    GitFactsBase,
    PathspecScope,
    commit_directory,
    commit_facts,
    commit_scopes,
    landing_directories,
    run_directories,
)
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.staging_simulation import simulated_staging
from tests.support.git_fixtures import run_git as _git


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def twin(tmp_path: Path) -> Path:
    """``f.txt`` at the root and in ``sub/``, both edited since HEAD."""
    root = tmp_path / "twin"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _write(root, "f.txt", "head\n")
    _write(root, "sub/f.txt", "head\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    _write(root, "f.txt", "root-edit\n")
    _write(root, "sub/f.txt", "sub-edit\n")
    return root


def _recorded(facts: GitFactsBase) -> set[str]:
    return {change.path for change in facts.staged_changes()}


class TestPathspecsAreReadFromWhereTheCommandMovesTo:
    @pytest.mark.parametrize(
        "command",
        [
            "cd sub && git commit -m x f.txt",
            "git -C sub commit -m x f.txt",
            "git -Csub commit -m x f.txt",
            "(cd sub && git commit -m x f.txt)",
            "pushd sub && git commit -m x f.txt",
            "cd sub/.. && cd sub && git commit -m x f.txt",
        ],
    )
    def test_a_pathspec_names_the_file_in_the_directory_it_moved_to(
        self, twin: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "sub/f.txt" in _recorded(facts)
        assert "f.txt" not in _recorded(facts)

    def test_a_move_back_to_the_root_names_the_root_file(self, twin: Path) -> None:
        command = "cd sub && cd .. && git commit -m x f.txt"

        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "f.txt" in _recorded(facts)
        assert "sub/f.txt" not in _recorded(facts)

    def test_the_move_is_relative_to_the_hooks_own_directory(self, twin: Path) -> None:
        _write(twin, "sub/deeper/f.txt", "head\n")
        _git(twin, "add", "-A")
        _git(twin, "commit", "-m", "deeper")
        _write(twin, "sub/deeper/f.txt", "deeper-edit\n")

        facts = commit_facts(
            read_commit_form("cd deeper && git commit -m x f.txt"), twin, twin / "sub"
        )

        assert "sub/deeper/f.txt" in _recorded(facts)

    @pytest.mark.parametrize(
        "command",
        [
            "cd $WHERE && git commit -m x f.txt",
            "cd - && git commit -m x f.txt",
            "cd ~ && git commit -m x f.txt",
            "git --git-dir=.git commit -m x f.txt",
            "GIT_DIR=.git git commit -m x f.txt",
        ],
    )
    def test_a_move_this_reading_cannot_state_keeps_the_root_reading(
        self, twin: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "f.txt" in _recorded(facts)

    def test_a_move_outside_the_repository_keeps_the_root_reading(
        self, twin: Path, tmp_path: Path
    ) -> None:
        command = f"cd {tmp_path} && git commit -m x f.txt"

        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "f.txt" in _recorded(facts)

    def test_an_uncertain_reading_is_still_the_index_plus_the_named_paths(self, twin: Path) -> None:
        _git(twin, "add", "f.txt")
        _write(twin, "f.txt", "head\n")

        facts = commit_facts(read_commit_form("cd sub && git commit -m x f.txt"), twin, twin)

        assert facts.union is True
        assert {"f.txt", "sub/f.txt"} <= _recorded(facts)


#: Moves that may fail, be skipped or run in the background: the commit may stay
#: where the hook runs, so neither reading can be dropped.
_UNCERTAIN_MOVES = [
    "cd nosuch; git commit -m x f.txt",
    "test -d nosuch && cd nosuch; git commit -m x f.txt",
    "cd sub & git commit -m x f.txt",
    "cd sub || cd other; git commit -m x f.txt",
    "false || cd sub && git commit -m x f.txt",
    "cd sub && echo hi; git commit -m x f.txt",
    "echo hi | cd sub && git commit -m x f.txt",
    "(cd sub; git commit -m x f.txt)",
]
#: Moves every one of which must succeed for the commit to run at all.
_CERTAIN_MOVES = [
    "cd sub && git commit -m x f.txt",
    "test -d sub && cd sub && git commit -m x f.txt",
    "cd sub && cd .. && git commit -m x f.txt",
    "(cd sub && git commit -m x f.txt)",
    "git -C sub commit -m x f.txt",
    "git commit -m x f.txt",
]


class TestWhetherTheMovesAreCertain:
    @pytest.mark.parametrize("command", _UNCERTAIN_MOVES)
    def test_a_move_that_may_not_take_effect_is_uncertain(self, command: str) -> None:
        assert read_commit_form(command).moves_certain is False

    @pytest.mark.parametrize("command", _CERTAIN_MOVES)
    def test_a_move_the_commit_cannot_run_without_is_certain(self, command: str) -> None:
        assert read_commit_form(command).moves_certain is True


class TestAnUncertainMoveJudgesBothDirectories:
    """Ledger 00474 N299 round 2: a cd that may not have taken effect fails closed."""

    @pytest.mark.parametrize("command", _UNCERTAIN_MOVES)
    def test_the_paths_named_in_the_hooks_directory_are_judged(
        self, twin: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "f.txt" in _recorded(facts)

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub & git commit -m x f.txt",
            "cd sub; git commit -m x f.txt",
        ],
    )
    def test_the_paths_named_where_it_may_have_moved_to_are_judged_too(
        self, twin: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), twin, twin)

        assert {"f.txt", "sub/f.txt"} <= _recorded(facts)

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub && git commit -m x f.txt",
            "test -d sub && cd sub && git commit -m x f.txt",
            "(cd sub && git commit -m x f.txt)",
            "git -C sub commit -m x f.txt",
        ],
    )
    def test_a_certain_move_still_reads_only_where_it_moved_to(
        self, twin: Path, command: str
    ) -> None:
        facts = commit_facts(read_commit_form(command), twin, twin)

        assert "sub/f.txt" in _recorded(facts)
        assert "f.txt" not in _recorded(facts)

    def test_the_hooks_directory_is_read_as_well_as_the_one_moved_to(self, twin: Path) -> None:
        reading = read_commit_form("cd sub & git commit -m x f.txt")

        directories = [scope.directory for scope in commit_scopes(reading, twin, twin)]

        assert directories == [twin / "sub", twin]

    @pytest.mark.parametrize(
        "command", ["cd sub && git commit -m x f.txt", "git commit -m x f.txt"]
    )
    def test_a_certain_reading_has_one_directory(self, twin: Path, command: str) -> None:
        scopes = commit_scopes(read_commit_form(command), twin, twin)

        assert len(scopes) == 1


class TestCommitDirectory:
    def test_no_move_is_the_hooks_directory(self, twin: Path) -> None:
        reading = read_commit_form("git commit -m x f.txt")

        assert commit_directory(reading, twin) == twin

    def test_a_cd_is_joined_to_the_hooks_directory(self, twin: Path) -> None:
        reading = read_commit_form("cd sub && git commit -m x f.txt")

        assert commit_directory(reading, twin) == twin / "sub"

    def test_an_absolute_target_replaces_the_directory(self, twin: Path, tmp_path: Path) -> None:
        reading = read_commit_form(f"cd {tmp_path} && git commit -m x f.txt")

        assert commit_directory(reading, twin) == tmp_path

    def test_a_dash_c_follows_a_cd(self, twin: Path) -> None:
        _write(twin, "sub/deeper/f.txt", "x\n")
        reading = read_commit_form("cd sub && git -C deeper commit -m x f.txt")

        assert commit_directory(reading, twin) == twin / "sub" / "deeper"

    @pytest.mark.parametrize(
        "command",
        ["cd $X && git commit -m x f.txt", "cd - && git commit -m x f.txt"],
    )
    def test_an_unstatable_move_is_none(self, twin: Path, command: str) -> None:
        assert commit_directory(read_commit_form(command), twin) is None

    def test_a_bare_commit_with_a_cd_is_resolved_too(self, twin: Path) -> None:
        reading = read_commit_form("cd sub && git commit -m x")

        assert commit_directory(reading, twin) == twin / "sub"


@pytest.fixture
def git_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Every argv ``git_facts`` hands to ``run_git``, in order."""
    calls: list[tuple[str, ...]] = []
    real: Callable[..., Any] = run_git

    def counting(root: Path, *args: str, **kwargs: Any) -> Any:
        calls.append(args)
        return real(root, *args, **kwargs)

    monkeypatch.setattr(git_facts_module, "run_git", counting)
    return calls


class TestEveryPathspecMatchesCostsOneGitCall:
    @pytest.fixture
    def many(self, tmp_path: Path) -> tuple[Path, list[str]]:
        root = tmp_path / "many"
        root.mkdir()
        _git(root, "init")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "T")
        names = [f"p{number}.txt" for number in range(12)]
        for name in names:
            _write(root, name, "head\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        for name in names:
            _write(root, name, "edit\n")
        return root, names

    def test_twelve_matching_paths_are_one_invocation(
        self, many: tuple[Path, list[str]], git_calls: list[tuple[str, ...]]
    ) -> None:
        root, names = many

        assert GitFactsBase(root, pathspecs=names).every_pathspec_matches() is True
        assert len(git_calls) == 1

    def test_one_unmatched_path_among_many_is_false(self, many: tuple[Path, list[str]]) -> None:
        root, names = many

        assert (
            GitFactsBase(root, pathspecs=[*names, "nosuch.txt"]).every_pathspec_matches() is False
        )

    def test_a_directory_pathspec_matches(
        self, twin: Path, git_calls: list[tuple[str, ...]]
    ) -> None:
        assert GitFactsBase(twin, pathspecs=["sub"]).every_pathspec_matches() is True
        assert len(git_calls) == 1

    def test_a_path_removed_from_the_index_but_in_head_still_matches(self, twin: Path) -> None:
        _git(twin, "rm", "--cached", "-q", "f.txt")

        assert GitFactsBase(twin, pathspecs=["f.txt", "sub/f.txt"]).every_pathspec_matches() is True

    def test_commit_facts_judging_many_paths_stays_a_few_invocations(
        self, many: tuple[Path, list[str]], git_calls: list[tuple[str, ...]]
    ) -> None:
        root, names = many

        facts = commit_facts(read_commit_form("git commit -m x " + " ".join(names)), root)
        facts.staged_changes()

        assert facts.union is False
        assert len(git_calls) <= 3


class TestEveryDirectoryACdMayLandIn:
    """Ledger 00474 N306: ``cd a || cd b`` runs one of them, so both are places git may run."""

    def test_no_moves_is_the_start(self, tmp_path: Path) -> None:
        assert landing_directories((), 0, tmp_path) == (tmp_path,)

    def test_a_certain_chain_lands_in_one_directory(self, tmp_path: Path) -> None:
        assert landing_directories(("a", "b"), 0, tmp_path) == (tmp_path / "a" / "b",)

    def test_every_subset_of_the_optional_moves_is_a_place(self, tmp_path: Path) -> None:
        landed = set(landing_directories(("a", "b"), 2, tmp_path))

        assert landed == {tmp_path, tmp_path / "a", tmp_path / "b", tmp_path / "a" / "b"}

    def test_the_whole_chain_comes_first(self, tmp_path: Path) -> None:
        assert landing_directories(("a",), 1, tmp_path)[0] == tmp_path / "a"

    def test_a_dash_c_operand_always_applies(self, tmp_path: Path) -> None:
        landed = set(landing_directories(("a", "z"), 1, tmp_path))

        assert landed == {tmp_path / "a" / "z", tmp_path / "z"}

    def test_a_move_that_cannot_be_stated_drops_only_the_combinations_with_it(
        self, tmp_path: Path
    ) -> None:
        landed = set(landing_directories(("a", None), 2, tmp_path))

        assert landed == {tmp_path, tmp_path / "a"}

    def test_a_fixed_move_that_cannot_be_stated_leaves_nothing(self, tmp_path: Path) -> None:
        assert landing_directories((None,), 0, tmp_path) == ()

    def test_a_long_chain_tries_the_whole_chain_each_move_alone_and_none(
        self, tmp_path: Path
    ) -> None:
        moves = tuple(f"d{number}" for number in range(7))

        landed = set(landing_directories(moves, 7, tmp_path))

        assert landed == {
            tmp_path,
            tmp_path.joinpath(*moves),
            *(tmp_path / move for move in moves),
        }

    def test_only_directories_inside_the_repository_are_read(self, twin: Path) -> None:
        directories = run_directories(("sub", "/"), 2, twin, twin)

        assert set(directories) == {twin, twin / "sub"}

    def test_a_chain_that_leaves_the_repository_falls_back_to_the_hooks_directory(
        self, twin: Path
    ) -> None:
        assert run_directories(("/",), 0, twin / "sub", twin) == (twin / "sub",)

    def test_without_a_hooks_directory_the_repository_root_is_read(self, twin: Path) -> None:
        assert run_directories(("sub",), 0, None, twin) == (twin,)


class TestCommitScopes:
    def test_a_bare_commit_has_no_scope(self, twin: Path) -> None:
        assert commit_scopes(read_commit_form("git commit -m x"), twin, twin) == ()

    def test_each_commit_is_read_from_where_it_runs(self, twin: Path) -> None:
        reading = read_commit_form(
            "cd sub && git commit -m x f.txt; cd .. && git commit -m y f.txt"
        )

        scopes = commit_scopes(reading, twin, twin)

        assert [(scope.directory, scope.pathspecs) for scope in scopes] == [
            (twin / "sub", ("f.txt",)),
            (twin, ("f.txt",)),
        ]

    def test_a_reading_built_by_hand_is_one_commit(self, twin: Path) -> None:
        reading = CommitReading(CommitForm(pathspecs=("f.txt",)), certain=True)

        assert commit_scopes(reading, twin, twin) == (PathspecScope(twin, ("f.txt",)),)

    def test_a_hand_built_reading_with_uncertain_moves_reads_both_directories(
        self, twin: Path
    ) -> None:
        reading = CommitReading(
            CommitForm(pathspecs=("f.txt",)), certain=False, moves=("sub",), moves_certain=False
        )

        directories = {scope.directory for scope in commit_scopes(reading, twin, twin)}

        assert directories == {twin, twin / "sub"}


class TestFactsOfSeveralCommits:
    def test_the_second_commits_pathspec_is_judged(self, twin: Path) -> None:
        reading = read_commit_form("git commit -m x sub/f.txt; git commit -m y f.txt")

        facts = commit_facts(reading, twin, twin)

        assert _recorded(facts) == {"f.txt", "sub/f.txt"}

    def test_each_pathspec_is_read_from_its_own_commits_directory(self, twin: Path) -> None:
        _write(twin, "g.txt", "head\n")
        _git(twin, "add", "g.txt")
        _git(twin, "commit", "-m", "g")
        _write(twin, "g.txt", "edit\n")
        reading = read_commit_form(
            "cd sub && git commit -m x f.txt; cd .. && git commit -m y g.txt"
        )

        facts = commit_facts(reading, twin, twin)

        assert _recorded(facts) == {"sub/f.txt", "g.txt"}
        assert "f.txt" not in _recorded(facts)

    def test_a_bare_first_commit_adds_the_index_to_the_second_commits_paths(
        self, twin: Path
    ) -> None:
        _git(twin, "add", "f.txt")
        reading = read_commit_form("git commit -m x; git commit -m y sub/f.txt")

        facts = commit_facts(reading, twin, twin)

        assert _recorded(facts) == {"f.txt", "sub/f.txt"}

    def test_the_scopes_are_the_ones_the_facts_read(self, twin: Path) -> None:
        reading = read_commit_form("git commit -m x f.txt; git commit -m y sub/f.txt")

        facts = commit_facts(reading, twin, twin)

        assert [scope.pathspecs for scope in facts.scopes] == [("f.txt",), ("sub/f.txt",)]
        assert facts.pathspecs == ("f.txt", "sub/f.txt")
        assert facts.union is True
        assert facts.index_env is None


class TestFactsReadThePostAddIndex:
    def test_an_environment_makes_every_read_see_the_added_file(self, twin: Path) -> None:
        _write(twin, "new.txt", "new\n")
        reading = read_commit_form("git add new.txt && git commit -m x")

        with simulated_staging(reading, twin, twin) as env:
            facts = commit_facts(reading, twin, twin, index_env=env)
            assert _recorded(facts) == {"new.txt"}
            assert facts.staged_file_text("new.txt") == "new\n"
            listing = facts.index_listing(".")
            assert listing is not None
            assert facts.index_texts(listing, ["new.txt"]) == {"new.txt": "new\n"}
            assert facts.index_env == env

    def test_without_one_the_index_is_the_real_one(self, twin: Path) -> None:
        _write(twin, "new.txt", "new\n")

        assert _recorded(commit_facts(read_commit_form("git commit -m x"), twin, twin)) == set()
