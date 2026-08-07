"""Tests for find_deny_capable_handlers_without_allow_case (Plan 00200, Task 6.4).

Six handler false positives (EnforceLlmQaHandler, destructive_git, pipe_blocker,
lsp_enforcement, plan_qa_commit_gate, plan_number_helper) share one structural
gap: every handler's get_acceptance_tests() declares what it blocks and nothing
declares what it must NOT block. A positive-only acceptance-test suite cannot
catch over-broad matching by construction.

This module tests the pure function that detects the gap: a handler is
"DENY-capable" when any of its OWN declared acceptance tests expects DENY: such
a handler must ALSO declare at least one test expecting ALLOW (a near-miss case
proving the matcher isn't over-broad). The function consumes the same
dict shape PlaybookGenerator.generate_json() already produces, so it sees
library, plugin, and project handlers uniformly with zero extra plumbing.
"""

from typing import Any

from claude_code_hooks_daemon.daemon.playbook_generator import (
    find_deny_capable_handlers_without_allow_case,
)


def _entry(
    handler_name: str,
    expected_decision: str,
    source: str = "library",
    event_type: str = "PreToolUse",
) -> dict[str, Any]:
    return {
        "handler_name": handler_name,
        "source": source,
        "event_type": event_type,
        "expected_decision": expected_decision,
    }


class TestFindDenyCapableHandlersWithoutAllowCase:
    def test_empty_input_returns_empty(self) -> None:
        assert find_deny_capable_handlers_without_allow_case([]) == []

    def test_deny_only_handler_is_flagged(self) -> None:
        tests = [_entry("DestructiveGitHandler", "deny")]
        result = find_deny_capable_handlers_without_allow_case(tests)
        assert result == ["library:PreToolUse/DestructiveGitHandler"]

    def test_deny_and_allow_handler_is_not_flagged(self) -> None:
        tests = [
            _entry("LspEnforcementHandler", "deny"),
            _entry("LspEnforcementHandler", "allow"),
        ]
        assert find_deny_capable_handlers_without_allow_case(tests) == []

    def test_allow_only_handler_is_not_flagged(self) -> None:
        """A handler that only ever ALLOWs (advisory/context) has nothing to prove."""
        tests = [_entry("GitContextInjectorHandler", "allow")]
        assert find_deny_capable_handlers_without_allow_case(tests) == []

    def test_multiple_deny_tests_still_needs_one_allow(self) -> None:
        tests = [
            _entry("SedBlockerHandler", "deny"),
            _entry("SedBlockerHandler", "deny"),
            _entry("SedBlockerHandler", "deny"),
        ]
        result = find_deny_capable_handlers_without_allow_case(tests)
        assert result == ["library:PreToolUse/SedBlockerHandler"]

    def test_cli_entries_without_handler_name_are_ignored(self) -> None:
        """generate_json() also emits CLI-feature dicts with no handler_name key."""
        tests: list[dict[str, Any]] = [
            {"source": "cli", "expected_decision": "deny", "title": "some CLI test"},
            _entry("PipeBlockerHandler", "deny"),
        ]
        result = find_deny_capable_handlers_without_allow_case(tests)
        assert result == ["library:PreToolUse/PipeBlockerHandler"]

    def test_distinguishes_same_named_handler_across_sources(self) -> None:
        """A library and project handler sharing a bare class name stay distinct."""
        tests = [
            _entry("SharedName", "deny", source="library"),
            _entry("SharedName", "deny", source="project"),
            _entry("SharedName", "allow", source="project"),
        ]
        result = find_deny_capable_handlers_without_allow_case(tests)
        assert result == ["library:PreToolUse/SharedName"]

    def test_result_is_sorted(self) -> None:
        tests = [
            _entry("ZHandler", "deny"),
            _entry("AHandler", "deny"),
            _entry("MHandler", "deny"),
        ]
        result = find_deny_capable_handlers_without_allow_case(tests)
        assert result == sorted(result)
