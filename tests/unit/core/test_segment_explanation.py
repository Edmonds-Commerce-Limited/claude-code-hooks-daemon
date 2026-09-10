"""Tests for ``SegmentExplanation`` (Plan 00369).

A status-line handler's self-description: glyph(s), name, what it is, how to
read it, and its current value. Fail-fast validation on construction so a
handler that forgets a field crashes loudly at instantiation, not silently at
render time in ``status-line-explained``.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation


def _make(
    *,
    glyphs: tuple[str, ...] = ("🕐",),
    name: str = "Current Time",
    what_it_is: str = "Shows the local wall-clock time.",
    how_to_read: str = "24-hour HH:MM, no seconds.",
    current_value: str = "Currently shows 14:32.",
) -> SegmentExplanation:
    return SegmentExplanation(
        glyphs=glyphs,
        name=name,
        what_it_is=what_it_is,
        how_to_read=how_to_read,
        current_value=current_value,
    )


def _set_name(explanation: SegmentExplanation) -> None:
    """Exercise the frozen dataclass's own ``__setattr__`` override.

    ``explanation.name = ...`` is a real, permanent runtime violation this
    function exists to trigger (``FrozenInstanceError``, a subclass of
    ``AttributeError``) -- but it is ALSO a violation pyright's static
    read-only-attribute check correctly rejects on sight, since it can prove
    the field is frozen without running anything. ``setattr()`` with a
    NON-literal name goes through the exact same ``__setattr__`` override at
    runtime (unlike ``object.__setattr__``, which bypasses it and would defeat
    this test), while being opaque to that static check.
    """
    field_name = "name"
    setattr(explanation, field_name, "renamed")


class TestSegmentExplanationConstruction:
    def test_valid_construction_holds_every_field(self) -> None:
        explanation = _make()
        assert explanation.glyphs == ("🕐",)
        assert explanation.name == "Current Time"
        assert explanation.what_it_is == "Shows the local wall-clock time."
        assert explanation.how_to_read == "24-hour HH:MM, no seconds."
        assert explanation.current_value == "Currently shows 14:32."

    def test_is_frozen(self) -> None:
        explanation = _make()
        with pytest.raises(AttributeError):
            _set_name(explanation)

    def test_glyphs_may_be_empty_for_a_silent_handler(self) -> None:
        """A sensor handler (e.g. context_sidecar) never renders a visible icon."""
        explanation = _make(glyphs=())
        assert explanation.glyphs == ()


class TestSegmentExplanationFailsFast:
    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            _make(name="")

    def test_empty_what_it_is_raises(self) -> None:
        with pytest.raises(ValueError, match="what_it_is"):
            _make(what_it_is="")

    def test_empty_how_to_read_raises(self) -> None:
        with pytest.raises(ValueError, match="how_to_read"):
            _make(how_to_read="")

    def test_empty_current_value_raises(self) -> None:
        with pytest.raises(ValueError, match="current_value"):
            _make(current_value="")

    def test_whitespace_only_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name"):
            _make(name="   ")

    def test_whitespace_only_current_value_raises(self) -> None:
        with pytest.raises(ValueError, match="current_value"):
            _make(current_value="\n\t")
