"""The shared result for a safety guard that could not decide (Plan 00478).

The owner's ruling is "warn dont block": a guard that cannot tell whether
something is dangerous allows it, with an advisory, and says so in the log. A
positively recognised finding still denies; this helper is only for the case
where the guard has no verdict.

Every conversion calls :func:`unknown_verdict_allow`, so the advisory has one
shape (guard, cause, how to rephrase) and every fallback leaves one log line
starting with :data:`UNKNOWN_VERDICT_LOG_PREFIX`, which is what lets a field
report count how often the guards fell back to warning.

Neither ``cause`` nor ``rephrase`` may carry protected text (a secret term, a
file's contents): both reach the transcript and the log.
"""

from __future__ import annotations

import logging
from typing import Final

from claude_code_hooks_daemon.core import Decision, GatingResult

logger = logging.getLogger(__name__)

#: Stable greppable prefix of the one log line each unknown verdict writes.
UNKNOWN_VERDICT_LOG_PREFIX: Final[str] = "UNKNOWN-VERDICT"


def unknown_verdict_line(guard: str, cause: str, rephrase: str) -> str:
    """The advisory text: which guard, why it could not decide, what to do."""
    return (
        f"⚠️ {guard} could not fully decide, so it allowed this call; "
        f"not checked: {cause}. {rephrase}"
    )


def unknown_verdict_allow(guard: str, cause: str, rephrase: str) -> GatingResult:
    """ALLOW with an advisory, and log one ``UNKNOWN-VERDICT`` line.

    Args:
        guard: The handler name, as an operator would grep for it.
        cause: Why no verdict was reached (no protected text).
        rephrase: How to rephrase or retry so the guard can decide.

    Raises:
        ValueError: If any argument is blank.
    """
    for name, value in (("guard", guard), ("cause", cause), ("rephrase", rephrase)):
        if not value.strip():
            raise ValueError(f"unknown verdict needs a non-blank {name}")
    logger.warning("%s %s %s", UNKNOWN_VERDICT_LOG_PREFIX, guard, cause)
    return GatingResult(
        decision=Decision.ALLOW, context=[unknown_verdict_line(guard, cause, rephrase)]
    )
