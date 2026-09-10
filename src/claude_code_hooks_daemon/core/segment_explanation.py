"""``SegmentExplanation``: a status-line handler's self-description (Plan 00369).

Every ``StatusLineHandlerBase`` subclass must answer "what does this icon
mean, and what does it currently show?" without an agent having to read the
handler's source. ``status-line-explained`` (the CLI verb this backs) renders
one of these per status-line segment.

Deliberately read-only in spirit: computing a ``SegmentExplanation`` must
never write to disk or mutate shared state -- unlike ``handle()``, which some
status-line handlers use to record sensor state (e.g. ``ContextSidecarHandler``,
``MultithreadIndicatorHandler``). See ``StatusLineSegmentHandler.explain_segment``
in ``core/handler_bases.py`` for the contract this dataclass backs.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fields whose emptiness is fail-fast checked, in declaration order so the
# error message always names the first offending field a caller wrote.
_REQUIRED_STRING_FIELDS = ("name", "what_it_is", "how_to_read", "current_value")


@dataclass(frozen=True, slots=True)
class SegmentExplanation:
    """A status-line segment's self-description, for a human reader.

    Attributes:
        glyphs: The literal character(s)/emoji this segment can render, e.g.
            ``("🕐",)``. May be an empty tuple for a handler that never
            renders a visible icon (a pure sensor, e.g. ``ContextSidecarHandler``).
        name: Short human name for the segment, e.g. "Current Time".
        what_it_is: One or two terse sentences: what this segment is, in
            general (not this project's current state).
        how_to_read: What the possible values/variants mean (colours, icon
            shapes, thresholds).
        current_value: The current value's meaning for THIS project right
            now, computed read-only, or an explanation of why it is not
            shown right now (e.g. "requires a live session").
    """

    glyphs: tuple[str, ...]
    name: str
    what_it_is: str
    how_to_read: str
    current_value: str

    def __post_init__(self) -> None:
        """Fail fast on a malformed explanation rather than rendering it broken.

        Raises:
            TypeError: If ``glyphs`` is not a tuple (a list would undermine
                the frozen-dataclass immutability contract).
            ValueError: If any required string field is empty or whitespace-only.
        """
        if not isinstance(self.glyphs, tuple):
            raise TypeError(
                f"SegmentExplanation.glyphs must be a tuple of strings, got {type(self.glyphs).__name__}"
            )
        for field_name in _REQUIRED_STRING_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"SegmentExplanation.{field_name} must be a non-empty string")
