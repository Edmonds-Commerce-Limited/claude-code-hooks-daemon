"""Deliberately-invalid code that mypy MUST reject. Excluded from QA linting.

Every statement below is a defect the narrowed result types exist to prevent.
``tests/integration/test_static_type_safety_is_enforced.py`` runs mypy over this
file and asserts each one is caught, which is the only way to know the STATIC
half of the guarantee still works — the runtime tests would keep passing even if
mypy stopped enforcing anything.

Each violation carries a ``VIOLATION: <error-code>`` marker naming what mypy
must report for that line.

**Keep every violation on ONE line.** mypy reports a multi-line call at its
first line, which is not where a trailing marker ends up — so a wrapped call
silently decouples the marker from the error. This file is excluded from black
(as well as ruff and mypy) in ``pyproject.toml`` so a formatter cannot wrap it
back; black had done exactly that and moved a marker two lines away from its
error. If it does drift, the test fails loudly in both directions at once —
"expected, not reported" AND "reported, not claimed" — rather than quietly
passing.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import (
    SessionStartHandlerBase,
    StopHandlerBase,
)
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.result_types import (
    AdvisoryResult,
    BlockingResult,
    GatingResult,
)


def deny_on_an_advisory_result() -> AdvisoryResult:
    """SessionStart and friends cannot refuse anything."""
    return AdvisoryResult(decision=Decision.DENY, reason="no block")  # VIOLATION: arg-type


def ask_on_an_advisory_result() -> AdvisoryResult:
    """Nor can they ask."""
    return AdvisoryResult(decision=Decision.ASK, reason="nothing will ask")  # VIOLATION: arg-type


def ask_on_a_blocking_result() -> BlockingResult:
    """Stop and PostToolUse express `block`, but have no `ask`."""
    return BlockingResult(decision=Decision.ASK, reason="nothing will ask")  # VIOLATION: arg-type


def mutate_a_deny_into_an_advisory_result() -> AdvisoryResult:
    """The path `merge_pseudo_results` uses — construction is not the only way in."""
    result = AdvisoryResult()
    result.decision = Decision.DENY  # VIOLATION: assignment
    return result


def widen_an_advisory_result_back() -> AdvisoryResult:
    """Returning a wider tier where a narrow one is declared."""
    return GatingResult(decision=Decision.DENY, reason="wrong tier")  # VIOLATION: return-value


class DenyingSessionStartHandler(SessionStartHandlerBase):
    """The whole point: the constraint is INHERITED, nothing was declared."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult(decision=Decision.DENY, reason="no block")  # VIOLATION: arg-type

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class WideningSessionStartHandler(SessionStartHandlerBase):
    """Escaping by widening the signature must not work either."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:  # VIOLATION: override
        return HookResult(decision=Decision.DENY, reason="smuggled past the tier")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class AskingStopHandler(StopHandlerBase):
    """Stop expresses `block` but has no `ask`."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        return BlockingResult(decision=Decision.ASK, reason="cannot ask")  # VIOLATION: arg-type

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []
