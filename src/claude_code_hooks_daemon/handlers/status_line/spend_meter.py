"""SpendMeterHandler - the subagent spend segment (Plan 00471 L7, shared with Plan 00472).

``| Σ⚙ 1.66G ite · 3 live (2 opus, 1 sonnet) · max 412k · 2 unmeasured``

- **Σ⚙ ite**: summed input-token equivalents of every subagent that has stopped
  in this session, from the spend ledger rows ``subagent_cache_aggregator``
  writes (one memoised ``stat`` per render, see ``read_subagent_cache_totals``).
- **live**: the live-agent count with its per-model-family split, and the
  largest live context, from the snapshot the Stop/SubagentStop sensors and the
  spawn advisory refresh. A snapshot older than ``_FRESH_SECONDS`` is not shown:
  a stale count is worse than none.
- **unmeasured**: gate calls that could not read an agent's transcript and so
  failed open (RULINGS-fable.md Q2); shown only when non-zero.

Every read is mtime-gated or memoised (this package's no-ungated-reads rule),
and every read fails silent: a broken segment must never break the bar.
"""

from __future__ import annotations

import json
import logging
import time
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
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_cache_aggregator import (
    read_subagent_cache_totals,
)
from claude_code_hooks_daemon.utils.session_load import live_snapshot_path

logger = logging.getLogger(__name__)

_ICON: Final[str] = "Σ⚙"
_SEPARATOR: Final[str] = " · "

#: A live snapshot older than this is not shown.
_FRESH_SECONDS: Final[int] = 900

_SCALES: Final[tuple[tuple[float, str, int], ...]] = (
    (1e9, "G", 2),
    (1e6, "M", 1),
    (1e3, "k", 1),
)


def compact(value: float) -> str:
    """``1.66G``, ``2.5M``, ``412k`` or the plain number below a thousand."""
    for scale, suffix, digits in _SCALES:
        if value >= scale:
            return f"{value / scale:.{digits}f}".rstrip("0").rstrip(".") + suffix
    return str(round(value))


def _parse_snapshot(text: str) -> dict[str, Any]:
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class SpendMeterHandler(StatusLineHandlerBase):
    """Render the session's subagent spend, live agents and unmeasured count."""

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
        """Render the segment, or nothing when the session has no subagent activity."""
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        try:
            untracked = self._untracked_dir()
            ite = _int(read_subagent_cache_totals(session, root=untracked).get("ite"))
            snapshot = self._snapshots.read(live_snapshot_path(untracked, session))
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("spend meter has nothing to read: %s", exc)
            return AdvisoryResult(context=[])

        stamp = snapshot.get("ts")
        fresh = isinstance(stamp, (int, float)) and time.time() - stamp <= _FRESH_SECONDS
        if not ite and not fresh:
            return AdvisoryResult(context=[])

        parts = [f"{_ICON} {compact(ite)} ite"]
        if fresh:
            count = _int(snapshot.get("count"))
            families = snapshot.get("families")
            split = (
                ", ".join(
                    f"{_int(number)} {family}"
                    for family, number in sorted(
                        families.items(), key=lambda item: (-_int(item[1]), item[0])
                    )
                )
                if isinstance(families, dict) and count
                else ""
            )
            parts.append(f"{count} live" + (f" ({split})" if split else ""))
            largest = _int(snapshot.get("largest_context"))
            if count and largest:
                parts.append(f"max {compact(largest)}")
            unmeasured = _int(snapshot.get("unmeasured"))
            if unmeasured:
                parts.append(f"{unmeasured} unmeasured")
        return AdvisoryResult(context=[f"| {_SEPARATOR.join(parts)}"])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment (read-only, no I/O)."""
        return SegmentExplanation(
            glyphs=(_ICON,),
            name="Subagent Spend",
            what_it_is=(
                "What this session's subagents have cost and how many are running now, "
                "from the spend ledger (Plan 00471)."
            ),
            how_to_read=(
                "`Σ⚙ 1.66G ite` is the summed input-token equivalents of every subagent "
                "that has stopped (input 1, cache write 1.25, cache read 0.1, output 5: a "
                "proxy, so compare shares rather than absolute values). `3 live (2 opus, 1 "
                "sonnet)` counts agents working now by model family, `max 412k` is the "
                "largest live context, and `2 unmeasured` counts gate calls that could not "
                "read an agent's transcript and so let the call through. The live part is "
                f"hidden when the count is older than {_FRESH_SECONDS // 60} minutes. "
                "`hooks-daemon spend` prints the full ledger."
            ),
            current_value=(
                "Rendered per session from the ledger and live snapshot; there is no value "
                "outside a status-line render."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="spend meter renders subagent spend",
                command='echo "test"',
                description=(
                    "Verify the status line carries a 'Σ⚙ <n> ite' segment once a subagent "
                    "has stopped in the session, with the live count while it is fresh."
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
