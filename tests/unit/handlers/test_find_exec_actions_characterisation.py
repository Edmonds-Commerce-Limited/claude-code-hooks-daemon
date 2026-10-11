"""Characterisation of every reader of a `find -exec` action (ledger N397).

Five modules each kept their own list of `find`'s command-running actions and
their own reading of the `;`/`+` terminator. These rows pin the verdict of each
over `-exec`, `-execdir`, `-ok`, `-okdir`, both terminators and the shapes that
leave the terminator out, so that one shared helper changes none of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.root_recursion_guard import (
    RootRecursionGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_full_qa_blocker import (
    find_full_qa_invocation,
    parse_full_qa_patterns,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.write_protected_paths import (
    WriteProtectedPathsHandler,
)
from claude_code_hooks_daemon.handlers.registry import apply_handler_options
from claude_code_hooks_daemon.utils import recursive_search

ACTIONS = ("-exec", "-execdir", "-ok", "-okdir")
WT = "/workspace/.claude/worktrees/agent-x"
PROTECTED = ".claude/ccy/ccy.env.local"


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestRootRecursionGuard:
    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize("end", [";", "\\;", "+", ""])
    def test_a_bounded_find_that_runs_a_command_is_still_a_root_scan(
        self, action: str, end: str
    ) -> None:
        command = f"find / -maxdepth 1 {action} ls {{}} {end}".strip()
        assert RootRecursionGuardHandler().matches(_event(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "find / -maxdepth 1 -name x",
            "find /tmp -maxdepth 1 -exec ls {} ;",
            "find src -exec ls {} +",
        ],
    )
    def test_bounded_or_scoped_finds_stay_allowed(self, command: str) -> None:
        assert RootRecursionGuardHandler().matches(_event(command)) is False


class TestWorktreeFileCopy:
    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize(
        ("end", "denied"), [(";", True), ("\\;", True), ("+", True), ("", True)]
    )
    def test_a_copy_run_by_find_is_judged(self, action: str, end: str, denied: bool) -> None:
        command = f"find {WT}/src {action} cp {{}} src/ {end}".strip()
        assert WorktreeFileCopyHandler().matches(_event(command)) is denied

    @pytest.mark.parametrize(
        "command",
        [
            f"find {WT}/src -name x -exec ls {{}} \\;",
            f"find {WT}/src -exec echo hi \\; -exec cp {{}} src/ \\;",
            f"find {WT}/src -exec echo hi + -exec cp {{}} src/ +",
            "find src -exec cp {} other/ \\;",
            f"find {WT}/src -exec cp {{}} /tmp/x/ \\;",
            f"find {WT}/src -exec cp {{}} src/ ;",
        ],
    )
    def test_the_terminator_ends_one_action_and_the_next_is_read(self, command: str) -> None:
        verdicts = {
            f"find {WT}/src -name x -exec ls {{}} \\;": False,
            f"find {WT}/src -exec echo hi \\; -exec cp {{}} src/ \\;": True,
            f"find {WT}/src -exec echo hi + -exec cp {{}} src/ +": True,
            "find src -exec cp {} other/ \\;": False,
            f"find {WT}/src -exec cp {{}} /tmp/x/ \\;": False,
            f"find {WT}/src -exec cp {{}} src/ ;": True,
        }
        assert WorktreeFileCopyHandler().matches(_event(command)) is verdicts[command]


class TestRecursiveSearch:
    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize("end", [";", "+", None])
    def test_a_grep_run_by_find_is_a_search(self, action: str, end: str | None) -> None:
        words = ["find", ".", action, "grep", "-r", "x", "{}"]
        if end is not None:
            words.append(end)
        assert recursive_search._find_execs_a_search(words) is True

    @pytest.mark.parametrize(
        ("words", "expected"),
        [
            (["find", ".", "-exec", "ls", "{}", ";"], False),
            (["find", ".", "-exec", "ls", "{}", ";", "-exec", "grep", "x", "{}", "+"], True),
            (["find", ".", "-exec", ";"], False),
            (["find", ".", "-exec"], False),
            (["find", ".", "-name", "x"], False),
            (["find", ".", "-exec", "grep", "x", "{}", "\\;"], True),
        ],
    )
    def test_each_action_is_read_up_to_its_own_terminator(
        self, words: list[str], expected: bool
    ) -> None:
        assert recursive_search._find_execs_a_search(words) is expected


class TestSubagentFullQaBlocker:
    @pytest.fixture
    def patterns(self) -> list[Any]:
        patterns, problems = parse_full_qa_patterns([{"id": "x", "command": "make-check"}])
        assert not problems, problems
        return patterns

    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize("end", [";", "\\;", "+", ""])
    def test_a_full_run_launched_by_find_is_seen(
        self, patterns: list[Any], action: str, end: str
    ) -> None:
        command = f"find src {action} make-check {{}} {end}".strip()
        assert find_full_qa_invocation(command, patterns) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "find src -exec echo {} \\;",
            "find src -name x",
            "find src -exec echo {} \\; -exec ls {} +",
        ],
    )
    def test_a_find_that_runs_no_full_run_is_not_one(
        self, patterns: list[Any], command: str
    ) -> None:
        assert find_full_qa_invocation(command, patterns) is None

    def test_the_second_action_after_a_terminator_is_read(self, patterns: list[Any]) -> None:
        command = "find src -exec echo {} \\; -execdir make-check {} +"
        assert find_full_qa_invocation(command, patterns) is not None


class TestWriteProtectedPaths:
    @pytest.fixture
    def handler(self, tmp_path: Path) -> WriteProtectedPathsHandler:
        (tmp_path / ".claude" / "ccy").mkdir(parents=True)
        handler = WriteProtectedPathsHandler(project_root=tmp_path)
        apply_handler_options(handler, {"paths": [PROTECTED]})
        return handler

    def _denied(self, handler: WriteProtectedPathsHandler, root: Path, command: str) -> bool:
        event = _event(command)
        event["cwd"] = str(root)
        return handler.matches(event)

    @pytest.mark.parametrize("action", ACTIONS)
    @pytest.mark.parametrize(("verb", "denied"), [("rm", True), ("cat", False), ("grep", False)])
    def test_a_changing_command_run_by_find_is_denied(
        self,
        handler: WriteProtectedPathsHandler,
        tmp_path: Path,
        action: str,
        verb: str,
        denied: bool,
    ) -> None:
        command = f"find .claude/ccy {action} {verb} {{}} \\;"
        assert self._denied(handler, tmp_path, command) is denied

    @pytest.mark.parametrize(
        ("command", "denied"),
        [
            ("find .claude/ccy -exec", False),
            ("find .claude/ccy -exec /bin/rm {} +", True),
            ("find .claude/ccy -exec 'rm' {} +", True),
            ("find .claude/ccy -name x -print", False),
        ],
    )
    def test_shapes_around_the_action(
        self, handler: WriteProtectedPathsHandler, tmp_path: Path, command: str, denied: bool
    ) -> None:
        assert self._denied(handler, tmp_path, command) is denied
