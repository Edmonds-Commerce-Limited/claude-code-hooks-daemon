"""root_recursion_guard reads the careless spellings of a whole-filesystem scan (ledger N385).

A careless agent wraps the scan (`bash -c`, `time`, `sudo`), clusters its
options (`-rm1`), or reaches for another walker (`du`, `ls -R`). The guard
judges the command that runs and the root it walks, not the first word.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use import root_recursion_guard as guard
from claude_code_hooks_daemon.handlers.pre_tool_use.root_recursion_guard import (
    RootRecursionGuardHandler,
)


def _denied(command: str) -> bool:
    event: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    return RootRecursionGuardHandler().matches(event)


WRAPPED = [
    "bash -c 'grep -r x /'",
    'sh -c "grep -rl x /"',
    "bash -lc 'grep -r x /'",
    "bash -c 'cd /tmp; grep -r x /'",
    "sudo bash -c 'find / -name x'",
    "time grep -r x /",
    "time -p find / -name x",
    "sudo find / -name x",
    "sudo -u bob grep -r x /",
    "env FOO=1 rg x /",
    "nice -n 5 find / -name x",
    "timeout 60 grep -r x /",
    "command find / -name x",
    "bash -c 'sudo find / -name x'",
    "true && time grep -r x /",
]

CLUSTERED = [
    "grep -rm1 x /",
    "grep -rn -m1 x /",
    "grep -rA3 x /",
    "grep -Rm 1 x /",
    "ugrep -rm1 x /",
]

OTHER_WALKERS = [
    "du -sh /",
    "du -sh /proc",
    "du -d 1 /",
    "du -h --max-depth=1 /",
    "sudo du -sh /",
    "ls -R /",
    "ls -lR /",
    "ls --recursive /",
    "ls -R /home",
    "bash -c 'ls -R /'",
]

ALLOWED = [
    "grep -r x .",
    "grep -r x /workspace/src",
    "find /workspace -name x",
    "du -sh /workspace",
    "du -sh .",
    "du -sh",
    "du -d 1 /workspace",
    "ls /",
    "ls -la /",
    "ls -r /",
    "ls -lr /",
    "ls -R src",
    "ls -R",
    "rg x src/",
    "grep -m1 x /etc/hosts",
    "grep -rm1 x src/",
    "grep -n -m1 x /etc/hosts",
    "bash -c 'grep -r x .'",
    "bash -c 'ls /'",
    "bash -c 'echo grep -r x /'",
    "time grep x /etc/hosts",
    "sudo ls /",
    "sudo find /workspace -name x",
    "bash script.sh /",
    "bash -c 'cd / && ls'",
]


@pytest.mark.parametrize("command", WRAPPED)
def test_a_wrapper_in_front_of_the_scan_does_not_hide_it(command: str) -> None:
    assert _denied(command)


@pytest.mark.parametrize("command", CLUSTERED)
def test_a_clustered_option_does_not_hide_the_recursive_flag(command: str) -> None:
    assert _denied(command)


@pytest.mark.parametrize("command", OTHER_WALKERS)
def test_du_and_recursive_ls_over_the_filesystem_root_are_denied(command: str) -> None:
    assert _denied(command)


@pytest.mark.parametrize("command", ALLOWED)
def test_scoped_or_non_recursive_spellings_stay_allowed(command: str) -> None:
    assert not _denied(command)


def test_the_current_users_home_directory_is_the_home_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    assert _denied("rg x /home/user")
    assert _denied("rg x /home/user/")
    assert _denied("grep -r x /home/user")
    assert _denied("find /home/user -name x")


def test_a_directory_below_the_home_directory_is_a_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    assert not _denied("rg x /home/user/proj")
    assert not _denied("rg x /home/other/proj")


def test_a_home_that_holds_the_project_root_is_not_a_scan_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When HOME is the project (a container), scanning the project is not a disk walk."""
    monkeypatch.setenv("HOME", "/workspace")
    monkeypatch.setattr(guard, "resolve_project_root", lambda: "/workspace")
    assert not _denied("grep -r x /workspace")
    assert not _denied("du -sh /workspace")
    assert not _denied("find /workspace -name x")
    assert _denied("grep -r x /")
    assert _denied("grep -r x ~")


def test_a_home_above_the_project_root_is_not_a_scan_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setattr(guard, "resolve_project_root", lambda: "/home/user/proj")
    assert not _denied("rg x /home/user")


def test_a_home_beside_the_project_root_is_still_the_home_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setattr(guard, "resolve_project_root", lambda: "/workspace")
    assert _denied("rg x /home/user")


CHILDREN_OF_A_ROOT = [
    "du -sh /*",
    "ls -R /*",
    "grep -r x /*",
    "find /*",
    "find /* -name x",
    "du -sh /home/*",
    "grep -r x ~/*",
    "du -sh $HOME/*",
]

CHILDREN_OF_A_PROJECT = [
    "du -sh /workspace/*",
    "grep -r x src/*",
    "ls -R ./*",
    "find /workspace/* -name x",
]


@pytest.mark.parametrize("command", CHILDREN_OF_A_ROOT)
def test_a_dangerous_root_followed_by_a_glob_is_that_root(command: str) -> None:
    assert _denied(command)


@pytest.mark.parametrize("command", CHILDREN_OF_A_PROJECT)
def test_a_glob_below_a_project_directory_stays_allowed(command: str) -> None:
    assert not _denied(command)


@pytest.mark.parametrize(
    "command",
    [
        "ionice -c 3 find / -name x",
        "ionice -n 7 grep -r x /",
        "sudo ionice -c3 du -sh /",
        "bash -c -- 'grep -r x /'",
        "bash -lc -- 'find / -name x'",
    ],
)
def test_ionice_and_a_double_dash_before_the_body_do_not_hide_the_scan(command: str) -> None:
    assert _denied(command)


def test_ionice_over_a_scoped_scan_stays_allowed() -> None:
    assert not _denied("ionice -c 3 find /workspace -name x")
    assert not _denied("bash -c -- 'grep -r x .'")


def test_an_unset_home_adds_no_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME", raising=False)
    assert not _denied("rg x /home/user")
    assert not _denied("find '' -name x")


def test_the_escape_hatch_covers_a_wrapped_scan() -> None:
    assert not _denied("MUST_SCAN_ROOT_BECAUSE=\"audit\"; bash -c 'grep -r x /'")


def test_a_scan_nested_in_shells_is_read_to_a_bounded_depth() -> None:
    assert _denied("bash -c \"bash -c 'grep -r x /'\"")
    deep = "grep -r x /"
    for _ in range(12):
        deep = "bash -c " + repr(deep)
    assert not _denied(deep)
