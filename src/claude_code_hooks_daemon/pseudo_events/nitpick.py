"""Nitpick pseudo-event setup function.

Reads the conversation transcript incrementally and extracts new assistant
messages since the last audit. This shared setup runs ONCE per pseudo-event
fire, then all nitpick handlers receive the prepared data.

The setup function is registered with PseudoEventDispatcher and called
when a nitpick trigger fires.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader
from claude_code_hooks_daemon.nitpick.protocol import NitpickState

logger = logging.getLogger(__name__)

# Pseudo-event name constant
PSEUDO_EVENT_NAME = "nitpick"

# Transcript entry field holding an ISO-8601 timestamp, e.g.
# "2026-08-07T06:52:34.866Z". Present on real Claude Code transcript entries;
# absent from some fixtures, which is handled fail-open below.
_TIMESTAMP_FIELD = "timestamp"

# Suffix real transcripts use for UTC, which datetime.fromisoformat() did not
# accept before 3.11 and which is cheaper to normalise than to special-case.
_UTC_SUFFIX = "Z"
_UTC_OFFSET = "+00:00"


class NitpickSetup:
    """Callable setup for the nitpick pseudo-event.

    Maintains per-session NitpickState and uses TranscriptReader for
    incremental transcript reading. Returns enriched hook_input with
    assistant_messages, or None if no new messages to audit.
    """

    __slots__ = ("_reader", "_started_at", "_states")

    def __init__(self, started_at: datetime | None = None) -> None:
        """Initialise with shared transcript reader and empty state map.

        Args:
            started_at: When this daemon process came up. Defaults to now,
                which is correct in production because the dispatcher builds
                this at daemon startup. Injectable so tests need not freeze
                the clock.
        """
        self._reader = TranscriptReader()
        self._states: dict[str, NitpickState] = {}
        self._started_at = started_at or datetime.now(UTC)

    def __call__(self, hook_input: dict[str, Any], session_id: str) -> dict[str, Any] | None:
        """Read transcript and return enriched hook_input.

        Args:
            hook_input: Original hook input from the real event
            session_id: Current session identifier

        Returns:
            Enriched hook_input with pseudo_event and assistant_messages,
            or None if no new assistant messages to audit.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH, "")
        if not transcript_path:
            return None

        state = self._get_or_create_state(session_id)

        # Read new messages incrementally from last byte offset
        new_messages, new_offset = self._reader.read_incremental(
            transcript_path, state.last_byte_offset
        )

        # Update byte offset
        state.last_byte_offset = new_offset

        # Filter to assistant messages only
        assistant_messages = TranscriptReader.filter_assistant_messages(new_messages)

        # Drop anything written before this daemon process started (Plan 00224).
        # NitpickState is in-memory, so a restart resets last_byte_offset to 0
        # and this setup would otherwise re-audit the WHOLE transcript and
        # replay every finding the previous daemon already reported. The offset
        # alone cannot prevent that: a genuinely NEW session also starts at 0,
        # and its existing messages SHOULD be audited. The message timestamp
        # against our own start time is what separates the two.
        assistant_messages = [
            message for message in assistant_messages if self._is_after_start(message)
        ]

        if not assistant_messages:
            return None

        # Update last audited UUID
        last_msg = assistant_messages[-1]
        if last_msg.uuid:
            state.last_audited_uuid = last_msg.uuid

        # Build enriched hook_input
        enriched: dict[str, Any] = {
            **hook_input,
            "pseudo_event": PSEUDO_EVENT_NAME,
            "assistant_messages": [
                {"uuid": msg.uuid or "", "content": msg.content} for msg in assistant_messages
            ],
        }

        return enriched

    def _is_after_start(self, message: Any) -> bool:
        """Whether ``message`` was written at or after this daemon started.

        Fails OPEN. An entry with no timestamp, or one that cannot be parsed,
        is audited — a redundant advisory is a far smaller harm than a finding
        silently dropped, and some fixtures carry no timestamp at all.
        """
        raw = getattr(message, "raw", None) or {}
        stamp = raw.get(_TIMESTAMP_FIELD)
        if not isinstance(stamp, str) or not stamp:
            return True

        try:
            written_at = datetime.fromisoformat(stamp.replace(_UTC_SUFFIX, _UTC_OFFSET))
        except ValueError:
            logger.debug("NitpickSetup: unparseable transcript timestamp %r — auditing", stamp)
            return True

        if written_at.tzinfo is None:
            written_at = written_at.replace(tzinfo=UTC)

        return written_at >= self._started_at

    def get_state(self, session_id: str) -> NitpickState | None:
        """Get the NitpickState for a session (for testing/inspection).

        Args:
            session_id: Session identifier

        Returns:
            NitpickState if exists, None otherwise
        """
        return self._states.get(session_id)

    def _get_or_create_state(self, session_id: str) -> NitpickState:
        """Get or create NitpickState for a session.

        Args:
            session_id: Session identifier

        Returns:
            NitpickState for the session
        """
        if session_id not in self._states:
            self._states[session_id] = NitpickState()
        return self._states[session_id]
