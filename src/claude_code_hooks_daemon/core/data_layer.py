"""Daemon data layer - unified API for cross-event session data.

Single entry point for handlers to access session-wide data:
- SessionState: Model info and context usage from StatusLine events
- TranscriptReader: Conversation history from JSONL transcripts
- HandlerHistory: Previous handler decisions within the session
- UsageTracker: Latest subscription usage windows (Plan 00479); read via latest_usage()

Usage:
    from claude_code_hooks_daemon.core.data_layer import get_data_layer

    def handle(self, hook_input):
        dl = get_data_layer()
        if dl.session.is_opus(): ...
        if dl.history.was_blocked("Bash"): ...
"""

import logging
import time

from claude_code_hooks_daemon.core.disclosure_tracker import DisclosureTracker
from claude_code_hooks_daemon.core.handler_history import HandlerHistory
from claude_code_hooks_daemon.core.session_state import SessionState
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader
from claude_code_hooks_daemon.core.usage_snapshot import (
    UsageSnapshot,
    UsageTracker,
    resolve_usage_state_file,
)

logger = logging.getLogger(__name__)


class DaemonDataLayer:
    """Unified API facade for cross-event session data.

    Provides access to all session-wide data through a clean API.
    Each component is created once and reused for the session lifetime.
    """

    __slots__ = ("_disclosure", "_history", "_session", "_transcript", "_usage")

    def __init__(self) -> None:
        """Initialise with fresh component instances."""
        self._session = SessionState()
        self._usage = UsageTracker()
        self._transcript = TranscriptReader()
        self._history = HandlerHistory()
        self._disclosure = DisclosureTracker()

    @property
    def session(self) -> SessionState:
        """Access session state (model info, context usage).

        Returns:
            SessionState instance updated by StatusLine events
        """
        return self._session

    @property
    def usage(self) -> UsageTracker:
        """Access the subscription-usage tracker (Plan 00479).

        Returns:
            UsageTracker updated by StatusLine events; prefer latest_usage()
            for reading.
        """
        return self._usage

    @property
    def transcript(self) -> TranscriptReader:
        """Access conversation transcript reader.

        Returns:
            TranscriptReader for querying conversation history
        """
        return self._transcript

    @property
    def history(self) -> HandlerHistory:
        """Access handler decision history.

        Returns:
            HandlerHistory for querying previous handler decisions
        """
        return self._history

    @property
    def disclosure(self) -> DisclosureTracker:
        """Access per-agent rule disclosure state (Plan 00116).

        Returns:
            DisclosureTracker for querying/recording whether a rule's verbose
            block has already been delivered to a given agent this session.
        """
        return self._disclosure

    def reset(self) -> None:
        """Reset all data layer state.

        WARNING: Only use in testing or session cleanup.
        """
        self._session.reset()
        self._usage.reset()
        self._history.reset()
        self._transcript = TranscriptReader()
        self._disclosure = DisclosureTracker()


# Global singleton instance
_data_layer: DaemonDataLayer | None = None


def get_data_layer() -> DaemonDataLayer:
    """Get the global DaemonDataLayer singleton.

    Creates the instance on first access.

    Returns:
        Global DaemonDataLayer instance
    """
    global _data_layer
    if _data_layer is None:
        _data_layer = DaemonDataLayer()
    return _data_layer


def reset_data_layer() -> None:
    """Reset the global data layer (for testing).

    WARNING: Only use in test teardown.
    """
    global _data_layer
    _data_layer = None


def latest_usage(*, now: float | None = None) -> UsageSnapshot | None:
    """The latest live subscription usage windows, or None when there are none.

    Usage is account-wide, so this is not keyed by session. A window past its
    ``resets_at`` is absent. Falls back to the host-wide snapshot file when no
    Status event has been seen by this daemon yet.

    Args:
        now: Epoch seconds to judge expiry against; defaults to the wall clock.

    Returns:
        A frozen UsageSnapshot, or None when no window is live.
    """
    return get_data_layer().usage.latest(
        now=time.time() if now is None else now,
        state_file=resolve_usage_state_file(),
    )
