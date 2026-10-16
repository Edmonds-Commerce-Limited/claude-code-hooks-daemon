"""Tests for ReviewRoundAdvisorHandler (Plan 00471 Task 2.6, lever L9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.review_round_advisor import (
    ReviewRoundAdvisorHandler,
    review_key,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_events

SESSION = "s1"


@pytest.fixture
def handler(tmp_path: Path) -> ReviewRoundAdvisorHandler:
    instance = ReviewRoundAdvisorHandler()
    instance._untracked_override = tmp_path
    return instance


def dispatch(description: str, prompt: str = "", tool: str = "Agent") -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "tool_name": tool,
        "tool_input": {"description": description, "prompt": prompt},
    }


def run_round(handler: ReviewRoundAdvisorHandler, hook_input: dict[str, Any]) -> list[str]:
    result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW
    handler.commit_side_effects(hook_input, Decision.ALLOW)
    return result.context


@pytest.mark.parametrize(
    ("description", "prompt", "key"),
    [
        ("Review plan 00463 branch", "", "plan-463"),
        ("review", "Review the work for Plan 471.", "plan-471"),
        (
            "Code review",
            "branch worktree-p471-spend-levers is ready",
            "branch-worktree-p471-spend-levers",
        ),
        ("Opus reviewer round 2", "Plan 00463", "plan-463"),
        ("Implement plan 00463", "", None),
        ("Review the docs", "nothing names a plan", None),
        ("preview the page for plan 463", "", None),
    ],
)
def test_review_key(description: str, prompt: str, key: str | None) -> None:
    assert review_key(description, prompt) == key


def test_shipped_off_for_clients() -> None:
    assert ReviewRoundAdvisorHandler().get_default_enabled() is False


def test_advises_at_round_four_on_the_same_key(handler, tmp_path) -> None:
    rounds = [run_round(handler, dispatch("Review plan 00463")) for _ in range(5)]
    assert [bool(context) for context in rounds] == [False, False, False, True, True]
    advice = "\n".join(rounds[3])
    assert "round 4" in advice and "plan-463" in advice
    assert read_events(tmp_path, SESSION)[-1]["kind"] == "review-round-advisory"


def test_keys_are_counted_separately(handler) -> None:
    for _ in range(3):
        run_round(handler, dispatch("Review plan 00463"))
    assert not run_round(handler, dispatch("Review plan 00464"))


def test_a_denied_dispatch_does_not_count(handler) -> None:
    for _ in range(3):
        hook_input = dispatch("Review plan 00463")
        handler.handle(hook_input)
        handler.commit_side_effects(hook_input, Decision.DENY)
    assert not run_round(handler, dispatch("Review plan 00463"))


def test_a_denied_dispatch_records_no_advisory_event(handler, tmp_path) -> None:
    """Review N7: the ledger event is evidence, so it is written only for a dispatch that went."""
    for _ in range(3):
        run_round(handler, dispatch("Review plan 00463"))
    hook_input = dispatch("Review plan 00463")
    assert handler.handle(hook_input).context
    handler.commit_side_effects(hook_input, Decision.DENY)
    assert read_events(tmp_path, SESSION) == []


def test_matches_only_review_dispatches(handler) -> None:
    assert handler.matches(dispatch("Review plan 00463"))
    assert handler.matches(dispatch("Review plan 00463", tool="Task"))
    assert not handler.matches(dispatch("Implement plan 00463"))
    assert not handler.matches({"tool_name": "Bash", "tool_input": {"command": "review plan 463"}})


def test_advise_at_is_configurable(handler) -> None:
    handler._advise_at = 2
    assert not run_round(handler, dispatch("Review plan 00463"))
    assert run_round(handler, dispatch("Review plan 00463"))


def test_docs(handler) -> None:
    assert handler.get_claude_md() is None
    assert handler.get_acceptance_tests()
