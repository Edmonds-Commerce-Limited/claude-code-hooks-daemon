"""Tests for ``SegmentExplanation`` (Plan 00369).

A status-line handler's self-description: glyph(s), name, what it is, how to
read it, and its current value. Fail-fast validation on construction so a
handler that forgets a field crashes loudly at instantiation, not silently at
render time in ``status-line-explained``.
"""

from __future__ import annotations

import dataclasses

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


def _field_names() -> list[str]:
    """Every declared field, read from the dataclass itself.

    The list is derived rather than typed out so a field added later is
    covered without anyone remembering to add it here.
    """
    return [field.name for field in dataclasses.fields(SegmentExplanation)]


class TestSegmentExplanationConstruction:
    def test_valid_construction_holds_every_field(self) -> None:
        explanation = _make()
        assert explanation.glyphs == ("🕐",)
        assert explanation.name == "Current Time"
        assert explanation.what_it_is == "Shows the local wall-clock time."
        assert explanation.how_to_read == "24-hour HH:MM, no seconds."
        assert explanation.current_value == "Currently shows 14:32."

    @pytest.mark.parametrize("field_name", _field_names())
    def test_every_field_is_frozen(self, field_name: str) -> None:
        """Frozen means EVERY field, and the names come from the dataclass.

        Written as a real loop over real field names rather than one literal
        assignment: a literal `explanation.name = ...` is a violation pyright
        can prove without running anything, so it rejects the line on sight
        and the only ways to keep it are a suppression comment or a
        hand-obfuscated name. Iterating the declared fields makes the dynamism
        genuine, and buys wider coverage for it. `setattr` still routes
        through the dataclass's own `__setattr__`, which is what raises;
        `object.__setattr__` would bypass it and test nothing.
        """
        explanation = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(explanation, field_name, "mutated")

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
