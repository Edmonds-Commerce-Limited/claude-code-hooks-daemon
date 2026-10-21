"""SpendMeterHandler - the running-subagents segment (Plan 00471 L7, reshaped by issue #133).

``| ⚙ 2 agents (opus, sonnet) · 140k``

- Shown ONLY while sub-agents are running: the count, the model families and the
  largest live context, from the snapshot the Stop/SubagentStop sensors and the
  spawn advisory refresh. A snapshot older than ``_FRESH_SECONDS`` is not shown:
  a stale count is worse than none. With no agent running the segment is empty.
- **unmeasured** (red, only when non-zero): gate calls that failed open because
  they could not measure an agent (RULINGS-fable.md Q2). A start-up agent whose
  transcript holds no assistant record yet is not one (``read_tail`` returns None
  for it). Failures show alone, still red, when no agent is running.
- The cumulative total is not on the bar: ``hooks-daemon spend`` prints the ledger.

Every read is mtime-gated (this package's no-ungated-reads rule), and every
read fails silent: a broken segment must never break the bar.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile
from claude_code_hooks_daemon.utils.session_load import live_snapshot_path

logger = logging.getLogger(__name__)

_ICON: Final[str] = "⚙"
_SEPARATOR: Final[str] = " · "
_RED: Final[str] = "\033[31m"
_RESET: Final[str] = "\033[0m"

#: A live snapshot older than this is not shown.
_FRESH_SECONDS: Final[int] = 900

#: ``(scale, suffix, decimals)`` from smallest to largest. A decimal is kept
#: only where it carries information: none for k, one for M, two for G.
_SCALES: Final[tuple[tuple[int, str, int], ...]] = (
    (1, "", 0),
    (1_000, "k", 0),
    (1_000_000, "M", 1),
    (1_000_000_000, "G", 2),
)

#: A scaled figure that rounds to this moves to the next scale (``1M``, never ``1000k``).
_ROLLOVER: Final[int] = 1_000


def compact(value: float) -> str:
    """``1.66G``, ``2.5M``, ``412k`` or the plain number below a thousand.

    Rounds half up, and a trailing zero decimal is dropped (``3M``, ``1.6G``).
    """
    text = "0"
    for scale, suffix, decimals in _SCALES:
        rounded = Decimal(str(value / scale)).quantize(
            Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP
        )
        text = format(rounded, "f")
        if decimals:
            text = text.rstrip("0").rstrip(".")
        text += suffix
        if rounded < _ROLLOVER:
            break
    return text


def _parse_snapshot(text: str) -> dict[str, Any]:
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _agents_text(count: int, families: object) -> str:
    """``⚙ 2 agents (opus, sonnet)``: families by count then name, without their numbers."""
    names = (
        [
            family
            for family, number in sorted(
                families.items(), key=lambda item: (-_int(item[1]), item[0])
            )
            if _int(number)
        ]
        if isinstance(families, dict)
        else []
    )
    noun = "agent" if count == 1 else "agents"
    return f"{_ICON} {count} {noun}" + (f" ({', '.join(names)})" if names else "")


class SpendMeterHandler(StatusLineHandlerBase):
    """Render the running sub-agents, and any measurement failures in red."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SPEND_METER,
            priority=Priority.SPEND_METER,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None
        self._snapshots: MtimeCachedFile[dict[str, Any]] = MtimeCachedFile(_parse_snapshot, {})

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run; `handle` decides whether there is anything to show."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Render the segment, or nothing when no agent runs and nothing failed."""
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        try:
            snapshot = self._snapshots.read(live_snapshot_path(self._untracked_dir(), session))
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("spend meter has nothing to read: %s", exc)
            return AdvisoryResult(context=[])

        stamp = snapshot.get("ts")
        if not (isinstance(stamp, (int, float)) and time.time() - stamp <= _FRESH_SECONDS):
            return AdvisoryResult(context=[])

        parts: list[str] = []
        count = _int(snapshot.get("count"))
        if count:
            parts.append(_agents_text(count, snapshot.get("families")))
            largest = _int(snapshot.get("largest_context"))
            if largest:
                parts.append(compact(largest))
        unmeasured = _int(snapshot.get("unmeasured"))
        if unmeasured:
            parts.append(f"{_RED}{unmeasured} unmeasured{_RESET}")
        if not parts:
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {_SEPARATOR.join(parts)}"])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment (read-only, no I/O)."""
        return SegmentExplanation(
            glyphs=(_ICON,),
            name="Running Subagents",
            what_it_is=(
                "The sub-agents running right now, from the live snapshot the Stop and "
                "SubagentStop sensors refresh (Plan 00471). It is absent when none run."
            ),
            how_to_read=(
                "`⚙ 2 agents (opus, sonnet) · 140k` is the number of sub-agents running, "
                "their model families, and the largest context any of them holds, in "
                "tokens. A red `2 unmeasured` is added only when that many context-budget "
                "or resume-guard calls could not read an agent's transcript and so let the "
                "call through (a missing or unreadable transcript, a usage-less tail, a "
                "handler error); an agent that has not written its first reply yet is not "
                "counted. Failures show alone when no agent is running. The segment is "
                f"hidden when the snapshot is older than {_FRESH_SECONDS // 60} minutes. "
                "The cumulative spend is not on the bar: `hooks-daemon spend` prints the "
                "ledger."
            ),
            current_value=(
                "Rendered per session from the live snapshot; there is no value outside a "
                "status-line render."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="spend meter renders running subagents",
                command='echo "test"',
                description=(
                    "Verify the status line carries a '⚙ <n> agents (<families>) · <context>' "
                    "segment while a subagent runs, and nothing once none does."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Display-only status-line segment; renders nothing it cannot source",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
