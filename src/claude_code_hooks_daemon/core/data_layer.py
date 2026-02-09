"""Daemon data layer - unified API for cross-event session data.

Single entry point for handlers to access session-wide data:
- SessionState: Model info and context usage from StatusLine events
- TranscriptReader: Conversation history from JSONL transcripts
- HandlerHistory: Previous handler decisions within the session

Usage:
    from claude_code_hooks_daemon.core.data_layer import get_data_layer

    def handle(self, hook_input):
        dl = get_data_layer()
        if dl.session.is_opus(): ...
        if dl.history.was_blocked("Bash"): ...
"""

import logging

from claude_code_hooks_daemon.core.handler_history import HandlerHistory
from claude_code_hooks_daemon.core.session_state import SessionState
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

logger = logging.getLogger(__name__)


class DaemonDataLayer:
    """Unified API facade for cross-event session data.

    Provides access to all session-wide data through a clean API.
    Each component is created once and reused for the session lifetime.
    """

    __slots__ = ("_history", "_session", "_transcript")

    def __init__(self) -> None:
        """Initialise with fresh component instances."""
        self._session = SessionState()
        self._transcript = TranscriptReader()
        self._history = HandlerHistory()

    @property
    def session(self) -> SessionState:
        """Access session state (model info, context usage).

        Returns:
            SessionState instance updated by StatusLine events
        """
        return self._session

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

    def reset(self) -> None:
        """Reset all data layer state.

        WARNING: Only use in testing or session cleanup.
        """
        self._session.reset()
        self._history.reset()
        self._transcript = TranscriptReader()


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
