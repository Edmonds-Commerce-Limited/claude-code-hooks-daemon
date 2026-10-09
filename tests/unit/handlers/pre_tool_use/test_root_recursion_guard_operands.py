"""root_recursion_guard judges the ROOT of a scan, not every word of the command.

Plan 00483 Task 3.2, batch (c). A pattern operand (`rg "/home" src/`), a single
file (`grep -r foo /proc/self/status`), a scan bounded to one level
(`find / -maxdepth 1`) and a subdirectory of the home tree (`~/projects`) do
not walk the filesystem. Each is narrowed by the operand that is data; a scan
of the whole of `/`, `/proc`, `/sys`, `/home`, `/root`, `~` or `$HOME` is not.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.root_recursion_guard import (
    RootRecursionGuardHandler,
)


def _denied(command: str) -> bool:
    event: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    return RootRecursionGuardHandler().matches(event)


ORDINARY = [
    'rg "/home" src/',
    'grep -rn "/" src/ --include=*.py',
    "grep -rn / src/",
    "rg foo ~/.bashrc",
    "grep -r foo /proc/self/status",
    "find / -maxdepth 1 -name tmp",
    "find /sys/class/net -maxdepth 1",
    "find $HOME/proj -name x",
    "find ~/projects -name x",
    "grep -rl x --include=*.py ~/projects",
    'rg "x" "$HOME/proj"',
    "rg --max-depth 1 x /",
    "fd -d 1 pattern /",
    "find src -path '/home/*'",
    "find . -name '/'",
    "rg ~",
    "grep -r /root src/",
    "grep -r --include *.py x src/",
    "rg -g '*.py' x src/",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_a_pattern_a_single_file_a_bounded_scan_or_a_subdirectory_is_allowed(
    command: str,
) -> None:
    assert not _denied(command)


DANGEROUS = [
    "grep -r x /",
    "find / -name x",
    "rg x ~",
    "grep -rn x $HOME",
    "grep -rn x ${HOME}/",
    "grep -r -e x /",
    "grep -r --regexp x /",
    "rg -e x /",
    "rg --files /",
    "find ~ -name x",
    "find -L / -name x",
    "find / -maxdepth 3 -name x",
    "find / -name x -maxdepth 2",
    "find / -maxdepth deep -name x",
    "grep -r --include=*.py x /",
    "grep -r --include *.py x /",
    "rg -g '*.py' x /",
    "rg --max-depth 5 x /",
    "fd foo /",
    "fd --search-path / foo",
    "grep -rn x /proc",
    "grep -rn x /sys/devices",
    "grep -rl x ~/",
    "grep -rl x /home",
    "grep -rl x /root",
    "ugrep -r x /",
    "rgrep x /",
    "x && grep -r x /",
    "x ; find / -name y",
    "x || rg y ~",
    "ls | grep -r x /",
    "FOO=1 grep -r x /",
    "grep -r x . /",
    "grep -r x / --include=*.py",
    # Review r1 B2: a depth bound does not excuse what find hands on.
    "find / -maxdepth 1 -exec grep -r x {} +",
    "find / -maxdepth 1 -exec grep -r x {} \\;",
    "find / -maxdepth 1 -type d -exec rg x {} +",
    "find / -maxdepth 1 -execdir du -sh {} +",
    "find / -maxdepth 1 -ok du -sh {} \\;",
    "find / -maxdepth 1 -okdir du -sh {} \\;",
    "find / -maxdepth 1 -type d | xargs grep -r x",
    "find / -maxdepth 1 -exec find {} -name x \\;",
    "find /home -maxdepth 1 -exec grep -rl x {} +",
    "find /sys/class/net -maxdepth 1 | xargs rg x",
]


@pytest.mark.parametrize("command", DANGEROUS)
def test_a_scan_of_a_whole_root_stays_denied(command: str) -> None:
    assert _denied(command)
