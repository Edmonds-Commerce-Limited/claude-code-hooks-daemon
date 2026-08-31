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

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.root_recursion_guard import (
    RootRecursionGuardHandler,
)

_BLOCKING_LIKE_DECISIONS = (Decision.DENY, Decision.ASK)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """get_data_layer() is a process-wide singleton (Plan 00116, Decision G).

    Without this, one test's ``mark_disclosed`` for a rule_id + transcript_path
    leaks into a later test that reuses the same pair, turning a genuine
    "first fire" into a stale "already disclosed".
    """
    reset_data_layer()
    yield
    reset_data_layer()


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

    def test_handle_reason_leads_with_rule_id(self, handler):
        result = handler.handle(_bash('grep -rl "x" /'))
        assert result.reason.startswith(f"BLOCKED [{RuleID.ROOT_RECURSION_CATASTROPHIC}]")


class TestRootRecursionGuardDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    def _hook_input(self, command: str, transcript_path: str | None = None) -> dict:
        hook_input: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self, handler):
        result = handler.handle(self._hook_input('grep -rl "x" /', "/tmp/agent-a/transcript.jsonl"))
        assert result.decision == Decision.DENY
        assert "115 minutes" in result.reason

    def test_second_fire_for_same_agent_is_terse(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input('grep -rl "x" /', transcript_path))
        result = handler.handle(self._hook_input("find / -name x", transcript_path))
        assert "115 minutes" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.ROOT_RECURSION_CATASTROPHIC}]")
        assert "Fix:" in result.reason

    def test_same_rule_different_agent_is_independently_verbose(self, handler):
        handler.handle(self._hook_input('grep -rl "x" /', "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(self._hook_input('grep -rl "x" /', "/tmp/agent-b/transcript.jsonl"))
        assert "115 minutes" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, handler):
        hook_input = self._hook_input('grep -rl "x" /')
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "115 minutes" in first.reason
        assert "115 minutes" in second.reason


class TestRootRecursionGuardGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return RootRecursionGuardHandler()

    def test_returns_one_rule(self, handler):
        rules = handler.get_rules()
        assert len(rules) == 1
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_id_matches_constant(self, handler):
        rules = handler.get_rules()
        assert rules[0].rule_id == RuleID.ROOT_RECURSION_CATASTROPHIC

    def test_rule_has_non_empty_verbose(self, handler):
        rules = handler.get_rules()
        assert rules[0].verbose


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

    def test_get_acceptance_tests_commands_actually_match_expected_decision(self, handler):
        """Each acceptance test's command must round-trip through matches()/handle().

        Regression test: the handler's own acceptance tests previously wrapped
        their dangerous command in ``echo "..."`` (the safety idiom most other
        blocking handlers use for raw substring-matching detection). But this
        handler tokenizes with ``shlex`` and inspects the first real command
        word of each shell segment, so wrapping the payload inside a quoted
        ``echo`` argument makes ``echo`` the detected command instead of
        ``grep``/``find`` — silently defeating detection and making the
        acceptance test pass/fail without ever exercising the real code path.
        """
        for test in handler.get_acceptance_tests():
            hook_input = {"tool_name": "Bash", "tool_input": {"command": test.command}}
            matched = handler.matches(hook_input)
            if test.expected_decision in _BLOCKING_LIKE_DECISIONS:
                assert matched is True, (
                    f"acceptance test {test.title!r} expects "
                    f"{test.expected_decision} but command {test.command!r} "
                    "does not match() this handler"
                )
            else:
                assert matched is False, (
                    f"acceptance test {test.title!r} expects "
                    f"{test.expected_decision} but command {test.command!r} "
                    "DOES match() this handler"
                )
