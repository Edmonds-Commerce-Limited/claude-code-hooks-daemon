"""Tests for the shared argv parser that names the branch a git command creates."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.git_branch_creation import (
    ROUTE_SETUP_WORKTREE,
    created_branches,
    worktree_add_path,
)


def _names(command: str) -> list[tuple[str, str, bool]]:
    return [(c.name, c.route, c.dwim) for c in created_branches(command)]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git switch -c feat", [("feat", "switch", False)]),
        ("git switch -C feat main", [("feat", "switch", False)]),
        ("git switch --create feat", [("feat", "switch", False)]),
        ("git switch --create=feat", [("feat", "switch", False)]),
        ("git switch -cfeat", [("feat", "switch", False)]),
        ("git switch --force-create feat", [("feat", "switch", False)]),
        ("git switch --orphan feat", [("feat", "switch", False)]),
        ("git checkout -b feat", [("feat", "checkout", False)]),
        ("git checkout -B feat origin/main", [("feat", "checkout", False)]),
        ("git checkout -bfeat", [("feat", "checkout", False)]),
        ("git checkout --orphan feat", [("feat", "checkout", False)]),
        ("git branch feat", [("feat", "branch", False)]),
        ("git branch feat main", [("feat", "branch", False)]),
        ("git branch -f --track feat origin/x", [("feat", "branch", False)]),
        ("git worktree add -b feat ../p", [("feat", "worktree", False)]),
        ("git worktree add -B feat ../p main", [("feat", "worktree", False)]),
        ("git worktree add ../wt/feat", [("feat", "worktree", True)]),
        ("git -C /x switch -c feat", [("feat", "switch", False)]),
        (
            "cd a && git checkout -b one && git switch -c two",
            [
                ("one", "checkout", False),
                ("two", "switch", False),
            ],
        ),
    ],
)
def test_creation_forms_name_the_branch(
    command: str, expected: list[tuple[str, str, bool]]
) -> None:
    assert _names(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "git switch main",
        "git checkout main",
        "git checkout -- file.py",
        "git branch",
        "git branch -a",
        "git branch -d old",
        "git branch -D old",
        "git branch -m old new",
        "git branch --list 'x*'",
        "git branch -v feat",
        "git branch a b c",
        "git worktree add --detach ../p",
        "git worktree add -d ../p",
        "git worktree add ../p main",
        "git worktree list",
        "git switch -c $NAME",
        'git checkout -b "$(date)"',
        "git worktree add ../$X",
        "git switch -c",
        "git status",
    ],
)
def test_non_creations_and_unreadable_names_yield_nothing(command: str) -> None:
    assert created_branches(command) == []


def test_creation_keeps_its_invocation() -> None:
    (creation,) = created_branches("git -C /repo switch -c feat")
    assert creation.invocation.subcommand == "switch"
    assert creation.invocation.global_options == ("-C", "/repo")


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("add", "../p"), "../p"),
        (("add", "-b", "feat", "../p"), "../p"),
        (("add", "-B", "feat", "../p", "main"), "../p"),
        (("add", "--reason", "why", "../p"), "../p"),
        (("add", "--detach", "../p"), "../p"),
        (("add", "--", "../p"), "../p"),
        (("add",), None),
        (("add", "-b", "feat"), None),
        (("list",), None),
        ((), None),
    ],
)
def test_worktree_add_path_reads_the_target_directory(
    arguments: tuple[str, ...], expected: str | None
) -> None:
    assert worktree_add_path(arguments) == expected


@pytest.mark.parametrize(
    "command",
    [
        "scripts/setup_worktree.sh worktree-feat",
        "./scripts/setup_worktree.sh worktree-feat",
        "bash scripts/setup_worktree.sh worktree-feat",
        "bash ./scripts/setup_worktree.sh worktree-feat main",
        "sh /workspace/scripts/setup_worktree.sh worktree-feat",
        "/workspace/scripts/setup_worktree.sh worktree-feat",
        "FOO=1 ./scripts/setup_worktree.sh worktree-feat",
        "cd /repo && ./scripts/setup_worktree.sh worktree-feat",
    ],
)
def test_setup_worktree_script_creates_the_named_branch(command: str) -> None:
    (creation,) = created_branches(command)
    assert (creation.name, creation.route, creation.dwim) == (
        "worktree-feat",
        ROUTE_SETUP_WORKTREE,
        False,
    )


def test_setup_worktree_script_acts_in_the_repository_that_holds_it() -> None:
    (creation,) = created_branches("cd /a && /workspace/scripts/setup_worktree.sh worktree-x")
    assert creation.invocation.directory == ("/a", "/workspace")


@pytest.mark.parametrize(
    "command",
    [
        "cat scripts/setup_worktree.sh",
        "echo scripts/setup_worktree.sh worktree-feat",
        'echo "run ./scripts/setup_worktree.sh worktree-feat"',
        "grep -n branch scripts/setup_worktree.sh",
        "bash -n scripts/setup_worktree.sh",
        "bash scripts/other.sh worktree-feat",
        "scripts/setup_worktree.sh",
        "./setup_worktree.sh worktree-feat",
        "scripts/setup_worktree.sh $NAME",
        "scripts/setup_worktree.sh --help",
    ],
)
def test_setup_worktree_script_mentions_that_create_nothing(command: str) -> None:
    assert created_branches(command) == []
