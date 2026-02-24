"""ModeManager - Manages daemon operating mode state.

Holds the current daemon mode and optional custom message.
Validates transitions and serializes state for IPC responses.
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant

logger = logging.getLogger(__name__)


class ModeManager:
    """Manages the daemon's current operating mode.

    Holds mode state and optional custom message, validates transitions,
    and serializes to dict for IPC responses.

    Attributes:
        current_mode: The current daemon operating mode.
        custom_message: Optional user-provided message for the mode.
    """

    __slots__ = ("_custom_message", "_mode")

    def __init__(
        self,
        initial_mode: DaemonMode = DaemonMode.DEFAULT,
        custom_message: str | None = None,
    ) -> None:
        """Initialize ModeManager.

        Args:
            initial_mode: Starting mode for the daemon.
            custom_message: Optional extra message appended to block reasons.
        """
        self._mode = initial_mode
        self._custom_message = custom_message

    @property
    def current_mode(self) -> DaemonMode:
        """Get current daemon mode."""
        return self._mode

    @property
    def custom_message(self) -> str | None:
        """Get optional custom message for current mode."""
        return self._custom_message

    def set_mode(
        self,
        mode: DaemonMode,
        custom_message: str | None = None,
    ) -> bool:
        """Set the daemon mode.

        Args:
            mode: New daemon mode.
            custom_message: Optional custom message (replaces existing).

        Returns:
            True if mode changed, False if already in requested mode
            with same custom message.
        """
        changed = self._mode != mode or self._custom_message != custom_message
        self._mode = mode
        self._custom_message = custom_message

        if changed:
            logger.info(
                "Daemon mode changed to: %s%s",
                mode.value,
                f" (message: {custom_message})" if custom_message else "",
            )

        return changed

    def to_dict(self) -> dict[str, Any]:
        """Serialize mode state to dictionary.

        Returns:
            Dictionary with mode and custom_message fields.
        """
        return {
            ModeConstant.KEY_MODE: self._mode.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: self._custom_message,
        }
