"""Integration test: All handlers can be imported and instantiated.

CRITICAL: This test catches the exact bug that broke 5 handlers (wrong import path).
If ANY handler fails to import or instantiate, this test fails immediately.

This is the FIRST LINE OF DEFENSE against import errors, circular imports,
missing dependencies, and registration failures.
"""

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.handler import Handler


def _discover_handler_modules() -> list[tuple[str, str]]:
    """Discover all handler modules in the handlers directory.

    Returns list of (module_path, display_name) tuples.
    """
    handlers_dir = Path("src/claude_code_hooks_daemon/handlers")
    modules: list[tuple[str, str]] = []

    for event_dir in sorted(handlers_dir.iterdir()):
        if not event_dir.is_dir() or event_dir.name.startswith("_"):
            continue
        # Skip non-handler directories
        if event_dir.name in ("utils",):
            continue

        for py_file in sorted(event_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "hello_world.py":
                continue
            # Skip non-handler utility files
            if py_file.name == "stats_cache_reader.py":
                continue

            module_path = f"claude_code_hooks_daemon.handlers.{event_dir.name}.{py_file.stem}"
            display_name = f"{event_dir.name}/{py_file.stem}"
            modules.append((module_path, display_name))

    return modules


HANDLER_MODULES = _discover_handler_modules()


@pytest.mark.parametrize(
    "module_path,display_name",
    HANDLER_MODULES,
    ids=[m[1] for m in HANDLER_MODULES],
)
def test_handler_imports_and_instantiates(
    module_path: str, display_name: str, project_context: Any
) -> None:
    """Every handler module can be imported and its Handler class instantiated.

    This catches:
    - Import errors (wrong module paths)
    - Missing dependencies
    - Circular imports
    - ProjectContext not available at init time
    - Constructor errors
    """
    module = importlib.import_module(module_path)

    # Find Handler subclasses defined in this module
    handler_classes = [
        obj
        for _name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, Handler) and obj is not Handler and obj.__module__ == module_path
    ]

    assert len(handler_classes) > 0, f"No Handler subclass found in {module_path}"

    for handler_class in handler_classes:
        handler = handler_class()
        assert handler.name, f"{handler_class.__name__} has no name"
        assert handler.priority >= 0, f"{handler_class.__name__} has invalid priority"
        assert isinstance(handler.terminal, bool)
        assert isinstance(handler.tags, list)

        # Verify acceptance tests are defined
        acceptance_tests = handler.get_acceptance_tests()
        assert (
            len(acceptance_tests) > 0
        ), f"{handler_class.__name__} must define at least 1 acceptance test"


@pytest.mark.parametrize(
    "module_path,display_name",
    HANDLER_MODULES,
    ids=[m[1] for m in HANDLER_MODULES],
)
def test_handler_matches_returns_bool(
    module_path: str, display_name: str, project_context: Any
) -> None:
    """Every handler's matches() returns a boolean, not None or exception.

    Uses an empty hook_input to verify basic type safety.

    Note: Some handlers are "always-match" handlers that run on every event
    of their type (status_line, notification, session events, etc.). These
    legitimately return True for empty input. Only handlers for events with
    variable content (pre_tool_use, post_tool_use, permission_request) should
    return False for empty input.
    """
    module = importlib.import_module(module_path)

    handler_classes = [
        obj
        for _name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, Handler) and obj is not Handler and obj.__module__ == module_path
    ]

    # Event types that require specific input to match
    # (as opposed to always-match event types like status_line, notification, etc.)
    CONDITIONAL_EVENT_TYPES = {"pre_tool_use", "post_tool_use", "permission_request"}

    for handler_class in handler_classes:
        handler = handler_class()
        # Empty input should not crash
        result = handler.matches({})

        # Verify matches() returns a bool (not None, not exception)
        assert isinstance(
            result, bool
        ), f"{handler_class.__name__}.matches({{}}) returned {type(result)}, expected bool"

        # Extract event type from display_name (format: "event_type/handler_name")
        event_type = display_name.split("/")[0]

        # Only conditional event types should return False for empty input
        # Always-match handlers (status_line, notification, session events, etc.) can return True
        if event_type in CONDITIONAL_EVENT_TYPES:
            assert (
                result is False
            ), f"{handler_class.__name__}.matches({{}}) returned True for empty input (expected False for {event_type} handlers)"
