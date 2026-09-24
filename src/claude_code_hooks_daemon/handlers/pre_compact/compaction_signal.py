"""CompactionSignalHandler - drops a compaction-underway signal for the supervisor.

Plan 00135. When Claude Code fires PreCompact (a compaction is starting --
whether triggered by the PTY supervisor's ``/compact`` OR typed manually by the
human), this handler writes a small ``<session>.compacting`` marker into the
context-sidecar directory. The standalone ``claude-supervise`` PTY supervisor
reads that marker and injects ``continue`` to resume the post-compact session.

The marker filename deliberately ends in ``.compacting`` (NOT ``.json``) so the
supervisor's ``*.json`` context-sidecar reader never mistakes it for a sidecar.

Plan 00399: the marker also records WHOSE compaction it is (``origin``), from
PreCompact's ``trigger`` and ``custom_instructions``. This record is how the
supervisor recognises a human ``/compact`` that its keystroke match cannot see
(a Tab-completed ``/comp``), and it is written only when a compaction really
starts, so it cannot produce a false recognition. The human's own instruction
text is never written, only the verdict.

Opt-in (``get_default_enabled() -> False``): only useful when a supervisor is
watching. It is the DAEMON (sensor) half of the compaction-detect/auto-continue
feature; the supervisor is the separate actuator.
"""

import json
import logging
import re
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PreCompactHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.utils.ccy_supervisor import (
    CCY_SUPERVISOR_MARKER,
    supervisor_relevance,
)
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

# Must match the context_sidecar handler's subdir and the supervisor's reader.
_SIGNAL_SUBDIR = "context-sidecar"

# Deliberately NOT ``.json`` -- see module docstring.
_SIGNAL_SUFFIX = ".compacting"

# Filename stem used when the PreCompact payload carries no session id.
_SESSION_ID_FALLBACK = "unknown"

# Replace any filesystem-unsafe character in the session id with '_'.
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]")

# PreCompact ``trigger`` values (contracts/claude-code-hooks/PreCompact.json).
_TRIGGER_MANUAL = "manual"
_TRIGGER_AUTO = "auto"

# ``origin`` values the supervisor reads (``_COMPACTION_ORIGIN_LABELS`` in
# ``.claude/ccy/claude-supervise.py``). A manual compaction whose instructions
# do not carry the supervisor's own prefix was typed by the human.
_ORIGIN_HUMAN = "human"
_ORIGIN_SUPERVISOR = "supervisor"
_ORIGIN_AUTO = "auto"
_ORIGIN_UNKNOWN = "unknown"

# Signal payload keys.
_KEY_TS = "ts"
_KEY_SESSION_ID = "session_id"
_KEY_TRIGGER = "trigger"
_KEY_ORIGIN = "origin"


class CompactionSignalHandler(PreCompactHandlerBase):
    """Write a ``<session>.compacting`` signal on PreCompact for the supervisor."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.COMPACTION_SIGNAL,
            priority=Priority.COMPACTION_SIGNAL,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    def get_default_enabled(self) -> bool:
        """Opt-in: only useful when a PTY supervisor is watching."""
        return False

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only under an armed ccy supervisor (Plan 00330)."""
        return supervisor_relevance(context)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Signal on every compaction."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Write the compaction signal; never block compaction."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        raw_trigger = hook_input.get(HookInputField.TRIGGER)
        trigger = raw_trigger if isinstance(raw_trigger, str) else None
        origin = self._origin(trigger, hook_input.get(HookInputField.CUSTOM_INSTRUCTIONS))
        self._write_signal(session_id, trigger=trigger, origin=origin)
        return BlockingResult(decision=Decision.ALLOW)

    @staticmethod
    def _origin(trigger: str | None, custom_instructions: object) -> str:
        """Attribute the compaction: auto, the supervisor's own, or the human's."""
        if trigger == _TRIGGER_AUTO:
            return _ORIGIN_AUTO
        if trigger != _TRIGGER_MANUAL:
            return _ORIGIN_UNKNOWN
        if isinstance(custom_instructions, str) and custom_instructions.startswith(
            CCY_SUPERVISOR_MARKER
        ):
            return _ORIGIN_SUPERVISOR
        return _ORIGIN_HUMAN

    def _write_signal(self, session_id: str, *, trigger: str | None, origin: str) -> None:
        """Atomically write the compaction-signal marker file.

        Failures are logged, never swallowed silently, and never block the
        compaction (this is a best-effort observability signal).
        """
        try:
            target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
            target_dir.mkdir(parents=True, exist_ok=True)

            stem = self._safe_session_stem(session_id)
            final_path = target_dir / f"{stem}{_SIGNAL_SUFFIX}"
            tmp_path = unique_temp_path(final_path)

            payload = {
                _KEY_TS: self._now(),
                _KEY_SESSION_ID: session_id,
                _KEY_TRIGGER: trigger,
                _KEY_ORIGIN: origin,
            }
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(final_path)
        except RuntimeError as e:
            logger.warning("Skipping compaction signal (no project context): %s", e)
        except OSError as e:
            logger.warning("Failed to write compaction signal: %s", e)

    def _safe_session_stem(self, session_id: str) -> str:
        if not session_id:
            return _SESSION_ID_FALLBACK
        return _UNSAFE_SESSION_CHARS.sub("_", session_id)

    def _now(self) -> float:
        """Return the current epoch time (seam for deterministic tests)."""
        return time.time()

    def get_claude_md(self) -> str | None:
        # Observe-only writer; blocks nothing, injects nothing into the session.
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="compaction signal handler test",
                command='echo "test"',
                description="Tests that the compaction signal handler writes a marker",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Observe-only PreCompact writer - blocks nothing",
                test_type=TestType.CONTEXT,
                requires_event="PreCompact event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
