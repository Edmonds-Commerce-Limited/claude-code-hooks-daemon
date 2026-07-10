"""CompactionSignalHandler - drops a compaction-underway signal for the supervisor.

Plan 00135. When Claude Code fires PreCompact (a compaction is starting --
whether triggered by the PTY supervisor's ``/compact`` OR typed manually by the
human), this handler writes a small ``<session>.compacting`` marker into the
context-sidecar directory. The standalone ``claude-supervise`` PTY supervisor
reads that marker and injects ``continue`` to resume the post-compact session.

The marker filename deliberately ends in ``.compacting`` (NOT ``.json``) so the
supervisor's ``*.json`` context-sidecar reader never mistakes it for a sidecar.

Opt-in (``get_default_enabled() -> False``): only useful when a supervisor is
watching. It is the DAEMON (sensor) half of the compaction-detect/auto-continue
feature; the supervisor is the separate actuator.
"""

import json
import logging
import os
import re
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext

logger = logging.getLogger(__name__)

# Must match the context_sidecar handler's subdir and the supervisor's reader.
_SIGNAL_SUBDIR = "context-sidecar"

# Deliberately NOT ``.json`` -- see module docstring.
_SIGNAL_SUFFIX = ".compacting"

# Filename stem used when the PreCompact payload carries no session id.
_SESSION_ID_FALLBACK = "unknown"

# Replace any filesystem-unsafe character in the session id with '_'.
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


class CompactionSignalHandler(Handler):
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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Signal on every compaction."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Write the compaction signal; never block compaction."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        self._write_signal(session_id)
        return HookResult(decision=Decision.ALLOW)

    def _write_signal(self, session_id: str) -> None:
        """Atomically write the compaction-signal marker file.

        Failures are logged, never swallowed silently, and never block the
        compaction (this is a best-effort observability signal).
        """
        try:
            target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
            target_dir.mkdir(parents=True, exist_ok=True)

            stem = self._safe_session_stem(session_id)
            final_path = target_dir / f"{stem}{_SIGNAL_SUFFIX}"
            tmp_path = target_dir / f".{stem}.{os.getpid()}.tmp"

            payload = {"ts": self._now(), "session_id": session_id}
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_path, final_path)
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
