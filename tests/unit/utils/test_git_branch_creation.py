"""Tests for the shared argv parser that names the branch a git command creates."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.git_branch_creation import created_branches


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
