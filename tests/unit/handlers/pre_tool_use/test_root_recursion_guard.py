"""Comprehensive tests for RootRecursionGuardHandler (Plan 00142, Layer A).

The handler blocks a recursive scanner (grep -r/-R/-rl, ugrep -r, find, fd, rg)
whose path argument resolves to a catastrophic root location (``/``, ``/proc``,
``/sys``, ``/home``, ``/root``, ``~``, ``$HOME``). It mirrors the incident in
``untracked/hooks-daemon-runaway-background-shell-harvester.md`` where
``grep -rl "class X" /`` ran for ~115 minutes at >1000% CPU.

Escape hatch: ``MUST_SCAN_ROOT_BECAUSE="reason"`` (mirrors git_stash's
``MUST_STASH_BECAUSE=``).
"""

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.root_recursion_guard import (
    RootRecursionGuardHandler,
)


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestRootRecursionGuardInit:
    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    def test_name(self, handler):
        assert handler.name == "root-recursion-guard"

    def test_priority(self, handler):
        assert handler.priority == 16

    def test_terminal(self, handler):
        assert handler.terminal is True


class TestRootRecursionGuardMatchesPositive:
    """Recursive scanners rooted at a catastrophic location must match (block)."""

    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    @pytest.mark.parametrize(
        "command",
        [
            'grep -rl "class X" /',
            'grep -R "pattern" /',
            "grep -rn foo /proc",
            "grep -rIl bar /sys",
            "ugrep -r baz /",
            'ugrep -G --ignore-files --hidden -I --exclude-dir=.git -rl "class X" /',
            "find / -type d -name phparkitect",
            "find /proc -name x",
            "fd pattern /",
            "fdfind pattern /home",
            "rg needle /",
            "rg --hidden needle /root",
            "grep -R thing ~",
            "grep -rl thing $HOME",
            "grep -rl thing ${HOME}",
            "grep -rl thing ~/",
            "grep -rl thing $HOME/",
            "rgrep pattern /",
            # the literal incident command (scanner segment + | head)
            'grep -rl "class MatchOneOfTheseNames" / 2>/dev/null | head',
        ],
    )
    def test_matches_dangerous(self, handler, command):
        assert handler.matches(_bash(command)) is True


class TestRootRecursionGuardMatchesNegative:
    """Scoped / non-recursive / safe commands must NOT match."""

    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    @pytest.mark.parametrize(
        "command",
        [
            # scoped to project / relative paths
            'grep -rl "class X" /workspace',
            'grep -rl "class X" "$CLAUDE_PROJECT_DIR"',
            "grep -rl foo src/",
            "grep -rl foo .",
            "rg needle /workspace/src",
            "find . -name x",
            "find /workspace -name x",
            "fd pattern src",
            # non-recursive grep at root (no -r/-R) is not this handler's concern
            "grep foo /etc/hosts",
            "grep 'x' /",
            # read-only pipeline transforming stdout, no recursive file scan
            "cat file | grep x",
            "echo / | grep -r x .",
            # not a scanner
            "ls -la /",
            "rm -rf /tmp/foo",
            # escape hatch present
            'MUST_SCAN_ROOT_BECAUSE="auditing whole disk for a CVE" grep -rl x /',
            # pattern contains a slash but path is scoped
            "grep -rl 'a/b' /workspace",
            # empty / non-bash
            "",
        ],
    )
    def test_does_not_match_safe(self, handler, command):
        assert handler.matches(_bash(command)) is False

    def test_non_bash_tool_ignored(self, handler):
        assert handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/"}}) is False


class TestRootRecursionGuardHandle:
    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    def test_handle_denies(self, handler):
        result = handler.handle(_bash('grep -rl "x" /'))
        assert result.decision == Decision.DENY

    def test_handle_reason_mentions_scoped_search(self, handler):
        result = handler.handle(_bash("find / -name x"))
        assert "workspace" in result.reason.lower() or "project" in result.reason.lower()

    def test_handle_reason_mentions_head_misconception(self, handler):
        result = handler.handle(_bash('grep -rl "x" / | head'))
        assert "head" in result.reason.lower()

    def test_handle_reason_mentions_escape_hatch(self, handler):
        result = handler.handle(_bash("find / -name x"))
        assert "MUST_SCAN_ROOT_BECAUSE" in result.reason


class TestRootRecursionGuardMetadata:
    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    def test_get_claude_md_present(self, handler):
        md = handler.get_claude_md()
        assert md is not None
        assert "root_recursion_guard" in md
        assert "MUST_SCAN_ROOT_BECAUSE" in md

    def test_get_acceptance_tests_nonempty(self, handler):
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
