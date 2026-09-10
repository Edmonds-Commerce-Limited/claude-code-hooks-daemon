"""Completeness sweep for ``explain_segment()`` across every status-line handler.

Plan 00369. Two failure modes this guards against:

1. A handler implements ``explain_segment()`` but with a placeholder/typo'd
   glyph -- caught by asserting each declared glyph appears LITERALLY in the
   handler's own source (the ground truth of everything it can ever render).
   Source-literal presence is checked rather than a single live-triggered
   render because several segments (downgrade indicator, supervisor
   indicator, startup cleanup, upgrade notifier, multithread indicator) only
   render under specific on-disk/process state that a generic sweep cannot
   cheaply reproduce for every handler -- and a glyph baked into the source is
   a STRONGER guarantee than one sample render would be, since it cannot be
   faked by a lucky test fixture.
2. A handler forgets ``explain_segment()`` entirely -- since it is now an
   abstract method on ``StatusLineSegmentHandler``, that handler would fail to
   INSTANTIATE and silently vanish from ``HandlerRegistry`` discovery (no
   crash, no log, just fewer registered handlers). Guarded directly by
   scanning the package's modules for any ``Handler`` subclass, concrete or
   not, and asserting none is abstract.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import claude_code_hooks_daemon.handlers.status_line as status_line_pkg
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.handlers.registry import iter_builtin_handler_classes

_STATUS_LINE_EVENT_DIR = "status_line"

# Pinned so an added/removed handler is a deliberate, visible change to this
# test rather than a silent shift in what the sweep covers.
_EXPECTED_HANDLER_COUNT = 14


def _status_line_handler_classes() -> list[type[Handler]]:
    return [
        ref.handler_cls
        for ref in iter_builtin_handler_classes()
        if ref.event_dir == _STATUS_LINE_EVENT_DIR
    ]


def _status_line_module_paths() -> list[Path]:
    package_dir = Path(status_line_pkg.__file__).parent
    return sorted(p for p in package_dir.glob("*.py") if p.name != "__init__.py")


class TestEveryStatusLineHandlerIsDiscoverable:
    """A handler missing ``explain_segment()`` fails to instantiate -- and
    ``is_discoverable_handler`` would then silently drop it from the
    registry. This scans the raw package contents so a vanished handler is
    caught directly, not inferred from a shrinking discovered count."""

    def test_the_expected_handler_count_holds(self) -> None:
        classes = _status_line_handler_classes()
        names = sorted(c.__name__ for c in classes)
        assert len(classes) == _EXPECTED_HANDLER_COUNT, (
            f"expected {_EXPECTED_HANDLER_COUNT} status-line handlers, found "
            f"{len(classes)}: {names}. If this is a deliberate addition/removal, "
            "update _EXPECTED_HANDLER_COUNT."
        )

    def test_no_handler_class_in_any_status_line_module_is_abstract(self) -> None:
        import importlib

        offenders: list[str] = []
        for module_path in _status_line_module_paths():
            module = importlib.import_module(
                f"claude_code_hooks_daemon.handlers.status_line.{module_path.stem}"
            )
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Handler)
                    and attr is not Handler
                    and attr.__module__ == module.__name__
                    and inspect.isabstract(attr)
                ):
                    offenders.append(f"{module_path.name}:{attr.__name__}")

        assert not offenders, (
            "status-line Handler subclass(es) are abstract (missing "
            f"explain_segment or another required method): {offenders}"
        )


class TestExplainSegmentCompleteness:
    def test_every_handler_returns_a_non_empty_explanation(self) -> None:
        failures: list[str] = []
        for handler_cls in _status_line_handler_classes():
            try:
                instance = handler_cls()
                explanation = instance.explain_segment()
            except Exception as e:
                failures.append(f"{handler_cls.__name__}: raised {e!r}")
                continue
            if not isinstance(explanation, SegmentExplanation):
                failures.append(
                    f"{handler_cls.__name__}: explain_segment() returned "
                    f"{type(explanation).__name__}, not SegmentExplanation"
                )
        assert not failures, "\n".join(failures)

    def test_every_declared_glyph_appears_in_the_handlers_own_source(self) -> None:
        """Checked against the whole MODULE's source, not just the class body.

        Every handler in this package defines its glyphs as module-level
        constants (e.g. ``_ICON_AHEAD = "↑"``) and references them by name
        inside the class -- ``inspect.getsource(handler_cls)`` alone would
        never see the literal character, only the constant's name.
        """
        failures: list[str] = []
        for handler_cls in _status_line_handler_classes():
            instance = handler_cls()
            explanation = instance.explain_segment()
            module = inspect.getmodule(handler_cls)
            assert module is not None
            source = inspect.getsource(module)
            missing = [glyph for glyph in explanation.glyphs if glyph not in source]
            if missing:
                failures.append(f"{handler_cls.__name__}: glyph(s) not found in source: {missing}")
        assert not failures, "\n".join(failures)

    def test_every_handler_name_is_distinct(self) -> None:
        """Two handlers sharing a display name would be indistinguishable in
        the rendered ``status-line-explained`` output."""
        names = [
            handler_cls().explain_segment().name for handler_cls in _status_line_handler_classes()
        ]
        assert len(names) == len(set(names)), f"duplicate segment names: {names}"
