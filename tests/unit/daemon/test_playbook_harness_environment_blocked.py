"""A probe refused by the repository's branch state says nothing about its handler.

The creation guard's cap and dormancy rules judge how many branches the
repository holds, which the harness does not control: in CI every remote
branch (Dependabot's included) counts. A probe for ANOTHER handler that
expected an allow and met one of those rules measured the repository, not its
handler, so it is reported as environment-blocked instead of failed. The
creation guard's own probes are never excused: their verdict is the point.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.daemon.playbook_harness import (
    ExecutableProbe,
    environment_blocked,
    plan_probe,
)

_ROOT = Path("/repo")
_CAP_DENY = "BLOCKED [R-BRANCH-WIP-CAP]: creating a branch while the open work branches are at cap"
_DORMANT_DENY = "BLOCKED [R-BRANCH-DORMANT]: creating a branch while a branch is dormant"


def _probe(handler: str, expected: str) -> ExecutableProbe:
    block = {
        "test_number": 365,
        "handler_name": handler,
        "title": "Agent spawned WITH worktree isolation (near-miss allow)",
        "event_type": "PreToolUse",
        "expected_decision": expected,
        "expected_message_patterns": [],
        "harness_cannot_produce": None,
        "tools_available": True,
        "tool_payload": {
            "tool_name": "Agent",
            "tool_input": {"description": "x", "prompt": "y", "isolation": "worktree"},
        },
    }
    probe = plan_probe(block, _ROOT)
    assert isinstance(probe, ExecutableProbe)
    return probe


def test_another_handlers_allow_probe_denied_by_the_cap_is_environment_blocked() -> None:
    reason = environment_blocked(_probe("AgentIsolationAdvisorHandler", "allow"), "deny", _CAP_DENY)
    assert reason is not None
    assert "R-BRANCH-WIP-CAP" in reason
    assert "#365 AgentIsolationAdvisorHandler" in reason


def test_dormancy_counts_as_branch_state_too() -> None:
    probe = _probe("AgentIsolationAdvisorHandler", "allow")
    assert environment_blocked(probe, "deny", _DORMANT_DENY) is not None


def test_the_creation_guards_own_probe_is_never_excused() -> None:
    probe = _probe("BranchCreationGuardHandler", "allow")
    assert environment_blocked(probe, "deny", _CAP_DENY) is None


def test_a_deny_for_any_other_rule_is_still_a_failure_to_score() -> None:
    probe = _probe("AgentIsolationAdvisorHandler", "allow")
    assert environment_blocked(probe, "deny", "BLOCKED [R-SOMETHING-ELSE]: no") is None


def test_an_allow_is_not_blocked() -> None:
    assert environment_blocked(_probe("AgentIsolationAdvisorHandler", "allow"), "allow", "") is None


def test_a_probe_expecting_a_deny_is_scored_as_usual() -> None:
    probe = _probe("AgentIsolationAdvisorHandler", "deny")
    assert environment_blocked(probe, "deny", _CAP_DENY) is None
