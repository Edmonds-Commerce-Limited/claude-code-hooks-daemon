"""Session state cache for StatusLine event data.

Lightweight in-memory cache updated on every StatusLine event.
Provides cross-event access to model info and context usage
for any handler via the DaemonDataLayer.

Usage:
    state = SessionState()
    state.update_from_status_event(hook_input)
    if state.is_opus():
        ...
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class SessionState:
    """In-memory cache of StatusLine event data.

    Updated on every StatusLine event by DaemonController.
    Provides model info and context usage to any handler.

    Attributes:
        model_id: Current model identifier (e.g. "claude-opus-4-6")
        model_display_name: Human-readable model name (e.g. "Claude Opus 4.6")
        context_used_percentage: Context window usage as percentage (0.0-100.0)
        last_updated: Timestamp of last StatusLine event
    """

    __slots__ = (
        "_context_used_percentage",
        "_last_updated",
        "_model_display_name",
        "_model_id",
    )

    def __init__(self) -> None:
        """Initialise with empty state."""
        self._model_id: str | None = None
        self._model_display_name: str | None = None
        self._context_used_percentage: float = 0.0
        self._last_updated: datetime | None = None

    @property
    def model_id(self) -> str | None:
        """Current model identifier."""
        return self._model_id

    @property
    def model_display_name(self) -> str | None:
        """Human-readable model name."""
        return self._model_display_name

    @property
    def context_used_percentage(self) -> float:
        """Context window usage as percentage (0.0-100.0)."""
        return self._context_used_percentage

    @property
    def last_updated(self) -> datetime | None:
        """Timestamp of last StatusLine event update."""
        return self._last_updated

    @property
    def is_populated(self) -> bool:
        """Whether state has been populated by at least one StatusLine event."""
        return self._last_updated is not None

    def update_from_status_event(self, hook_input: dict[str, Any]) -> None:
        """Update state from a StatusLine event's hook_input.

        Extracts model info and context window data. Handles missing
        fields gracefully with safe defaults.

        Args:
            hook_input: Hook input dictionary from StatusLine event
        """
        # Extract model data
        model_data = hook_input.get("model", {})
        if model_data:
            self._model_id = model_data.get("id")
            self._model_display_name = model_data.get("display_name")

        # Extract context window data
        ctx_data = hook_input.get("context_window", {})
        if ctx_data:
            self._context_used_percentage = ctx_data.get("used_percentage") or 0.0

        self._last_updated = datetime.now()

        logger.debug(
            "SessionState updated: model=%s, context=%.1f%%",
            self._model_id,
            self._context_used_percentage,
        )

    def is_opus(self) -> bool:
        """Check if current model is an Opus model.

        Returns:
            True if model ID contains 'opus'
        """
        if self._model_id is None:
            return False
        return "opus" in self._model_id.lower()

    def is_sonnet(self) -> bool:
        """Check if current model is a Sonnet model.

        Returns:
            True if model ID contains 'sonnet'
        """
        if self._model_id is None:
            return False
        return "sonnet" in self._model_id.lower()

    def is_haiku(self) -> bool:
        """Check if current model is a Haiku model.

        Returns:
            True if model ID contains 'haiku'
        """
        if self._model_id is None:
            return False
        return "haiku" in self._model_id.lower()

    def model_name_short(self) -> str:
        """Get short human-readable model name.

        Returns:
            'Opus', 'Sonnet', 'Haiku', display name, or 'Unknown'
        """
        if self._model_id is None:
            return "Unknown"
        model_lower = self._model_id.lower()
        if "opus" in model_lower:
            return "Opus"
        if "sonnet" in model_lower:
            return "Sonnet"
        if "haiku" in model_lower:
            return "Haiku"
        return self._model_display_name or "Unknown"

    def reset(self) -> None:
        """Reset all state to initial values.

        WARNING: Only use in testing or session cleanup.
        """
        self._model_id = None
        self._model_display_name = None
        self._context_used_percentage = 0.0
        self._last_updated = None
