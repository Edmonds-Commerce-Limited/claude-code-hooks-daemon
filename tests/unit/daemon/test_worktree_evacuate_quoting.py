"""Commands printed for a human to paste quote every outside name (Plan 00627, D-EXEC L1)."""

from __future__ import annotations

import shlex

import pytest

from claude_code_hooks_daemon.daemon.worktree_evacuate import human_command

_NAMES = ["plain-name", "my wt", "wt $(touch pwned)", "a;b", "it's"]


@pytest.mark.parametrize("name", _NAMES)
def test_the_reap_command_splits_back_to_exactly_the_name(name: str) -> None:
    words = shlex.split(human_command(name))
    assert words[-4:] == ["worktree-reap", "--reap", "--only", name]


def test_a_plain_name_is_printed_unchanged() -> None:
    assert human_command("agent-x").endswith("worktree-reap --reap --only agent-x")
