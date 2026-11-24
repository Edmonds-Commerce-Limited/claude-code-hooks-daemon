"""Shared lane-command logic: judging a command, and each strategy's acceptance test."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Final

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.utils.long_running_command import (
    FindingKind,
    LongRunningPolicy,
    classify,
)

#: Any ``timeout`` counts as unbounded here, so a bounded test run is still judged:
#: the lane is about WHAT runs, not how long.
_LANE_THRESHOLD_SECONDS: Final[float] = 0.0
_POLICY_CACHE_SIZE: Final[int] = 32

_WORKER_SEAT_PATTERN: Final[str] = r"worker seat"
_HARNESS_CANNOT_PRODUCE: Final[str] = (
    "Arming needs a live teamchat runtime and a seat with duty host; the harness "
    "session holds no team seat, so the guard stays silent there."
)


@lru_cache(maxsize=_POLICY_CACHE_SIZE)
def _policy(patterns: tuple[str, ...]) -> LongRunningPolicy:
    return LongRunningPolicy(
        threshold_seconds=_LANE_THRESHOLD_SECONDS,
        slow_patterns=tuple(re.compile(pattern) for pattern in patterns),
    )


def runs_any(command: str, patterns: Sequence[str]) -> bool:
    """Whether ``command`` runs a program matching any of ``patterns``, anywhere in it.

    The shared classifier peels the common wrappers and reads ``sh -c`` bodies
    and backgrounded statements; text bash hands over as data (an ``echo``
    argument, a commit message) is never read as a command.
    """
    findings = classify(command, _policy(tuple(patterns)), include_background=True)
    return any(finding.kind is FindingKind.SLOW_COMMAND for finding in findings)


def lane_acceptance_test(language_name: str, command: str) -> Any:
    """A host seat's refusal of ``command``, which no harness session can drive."""
    from claude_code_hooks_daemon.core import (
        AcceptanceTest,
        Decision,
        RecommendedModel,
        TestType,
    )

    return AcceptanceTest(
        title=f"host seat lane guard ({language_name}) - {command} is a lane command",
        command=command,
        description=(
            f"Under mode: block a host-duty seat's {language_name} lane command is denied. "
            "Unit tests in tests/unit/strategies/lane_commands/ cover the list."
        ),
        expected_decision=Decision.DENY,
        expected_message_patterns=[RuleID.HOST_SEAT_LANE, _WORKER_SEAT_PATTERN],
        safety_notes="Never runs the command: it is denied before it starts.",
        test_type=TestType.BLOCKING,
        recommended_model=RecommendedModel.HAIKU,
        harness_cannot_produce=_HARNESS_CANNOT_PRODUCE,
    )
