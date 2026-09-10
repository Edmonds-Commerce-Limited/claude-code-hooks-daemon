"""Tests for ``StatusLineSegmentHandler`` (Plan 00369).

``StatusLineHandlerBase`` now points at a subclass of ``AdvisoryHandler`` that
adds an abstract ``explain_segment()`` -- every concrete status-line handler
must be able to describe itself. This must not weaken or alter the existing
Status-tier contract (``handle()`` still returns ``AdvisoryResult``, still
abstract) -- ``test_handler_bases.py``'s sweep already pins that; this file
pins the NEW contract specifically.
"""

from __future__ import annotations

import inspect
from typing import Any

from claude_code_hooks_daemon.core.handler_bases import (
    AdvisoryHandler,
    StatusLineHandlerBase,
    StatusLineSegmentHandler,
)
from claude_code_hooks_daemon.core.result_types import AdvisoryResult
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation


class TestStatusLineHandlerBaseIsStatusLineSegmentHandler:
    def test_status_line_handler_base_is_the_segment_handler(self) -> None:
        assert StatusLineHandlerBase is StatusLineSegmentHandler

    def test_status_line_segment_handler_descends_from_advisory_handler(self) -> None:
        """The Status tier constraint (no deny/ask) must still apply."""
        assert issubclass(StatusLineSegmentHandler, AdvisoryHandler)


class TestExplainSegmentIsAbstract:
    def test_explain_segment_is_abstract(self) -> None:
        assert "explain_segment" in getattr(
            StatusLineSegmentHandler, "__abstractmethods__", frozenset()
        )

    def test_handle_is_still_abstract(self) -> None:
        """Adding explain_segment must not accidentally supply a handle() stub."""
        assert "handle" in getattr(StatusLineSegmentHandler, "__abstractmethods__", frozenset())


class _Incomplete(StatusLineSegmentHandler):
    """Deliberately omits ``explain_segment`` -- must stay non-instantiable.

    This is exactly the failure mode ``registry.is_discoverable_handler``
    guards against via ``inspect.isabstract``: a handler that forgets
    ``explain_segment`` must not silently vanish from discovery, it must be
    impossible to construct.
    """

    def __init__(self) -> None:
        super().__init__(handler_id="incomplete_test_handler", priority=50, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult(context=[])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _Complete(StatusLineSegmentHandler):
    """Implements everything, including ``explain_segment``."""

    def __init__(self) -> None:
        super().__init__(handler_id="complete_test_handler", priority=50, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult(context=["| 🧪 ok"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def explain_segment(self) -> SegmentExplanation:
        return SegmentExplanation(
            glyphs=("🧪",),
            name="Test Segment",
            what_it_is="A test-only segment.",
            how_to_read="Always shows 🧪 ok.",
            current_value="Currently shows: 🧪 ok.",
        )


class TestAHandlerMissingExplainSegmentCannotBeInstantiated:
    def test_incomplete_handler_is_abstract(self) -> None:
        """Mirrors the exact check ``registry.is_discoverable_handler`` runs."""
        assert inspect.isabstract(_Incomplete)

    def test_incomplete_handler_is_missing_only_explain_segment(self) -> None:
        assert getattr(_Incomplete, "__abstractmethods__", frozenset()) == frozenset(
            {"explain_segment"}
        )


class TestAConformingHandlerWorks:
    def test_complete_handler_is_not_abstract(self) -> None:
        assert not inspect.isabstract(_Complete)

    def test_a_handler_implementing_everything_instantiates_and_explains(self) -> None:
        instance = _Complete()
        explanation = instance.explain_segment()
        assert explanation.name == "Test Segment"
        assert explanation.glyphs == ("🧪",)
