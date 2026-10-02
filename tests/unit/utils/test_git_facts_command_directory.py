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
from claude_code_hooks_daemon.utils.git_commit_parsing import read_commit_form
from claude_code_hooks_daemon.utils.git_facts import (
    GitFactsBase,
    commit_directory,
    commit_facts,
    unmoved_directories,
)
from claude_code_hooks_daemon.utils.git_repo import run_git
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

    def test_the_hooks_directory_is_the_extra_one(self, twin: Path) -> None:
        reading = read_commit_form("cd sub & git commit -m x f.txt")

        assert unmoved_directories(reading, twin, twin) == (twin,)

    @pytest.mark.parametrize(
        "command", ["cd sub && git commit -m x f.txt", "git commit -m x f.txt"]
    )
    def test_a_certain_reading_has_no_extra_directory(self, twin: Path, command: str) -> None:
        assert unmoved_directories(read_commit_form(command), twin, twin) == ()


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
