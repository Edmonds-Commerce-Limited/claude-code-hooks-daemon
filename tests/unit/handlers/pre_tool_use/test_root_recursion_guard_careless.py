"""root_recursion_guard reads the careless spellings of a whole-filesystem scan (ledger N385).

A careless agent wraps the scan (`bash -c`, `time`, `sudo`), clusters its
options (`-rm1`), or reaches for another walker (`du`, `ls -R`). The guard
judges the command that runs and the root it walks, not the first word.
"""

from typing import Any

import pytest

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
