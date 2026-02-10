"""Project handler loader for convention-based discovery.

This module provides the ProjectHandlerLoader class that discovers and loads
project-level handlers from a convention-based directory structure, mirroring
the built-in handler event-type subdirectories.

Directory structure:
    project-handlers/
        pre_tool_use/
            vendor_reminder.py
            test_vendor_reminder.py  (skipped)
            _helpers.py              (skipped)
        post_tool_use/
            build_checker.py
        session_start/
            branch_enforcer.py
"""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

logger = logging.getLogger(__name__)


class ProjectHandlerLoader:
    """Load project-level handlers from convention-based directory structure.

    Discovers handlers by scanning event-type subdirectories (pre_tool_use/,
    post_tool_use/, etc.) and dynamically loading Python files that contain
    Handler subclasses.

    Files starting with '_' or 'test_' are skipped. Only concrete Handler
    subclasses are loaded.
    """

    @staticmethod
    def load_handler_from_file(file_path: Path) -> Handler | None:
        """Load a single handler from a Python file.

        Uses importlib.util.spec_from_file_location to dynamically load
        the module and find concrete Handler subclasses.

        Args:
            file_path: Absolute path to a Python file containing a Handler subclass

        Returns:
            Handler instance if successful, None otherwise
        """
        if not file_path.exists():
            logger.warning("Project handler file not found: %s", file_path)
            return None

        module_name = f"project_handler_{file_path.stem}_{id(file_path)}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                logger.warning("Failed to create module spec for project handler: %s", file_path)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning("Failed to import project handler %s: %s", file_path.name, e)
            return None

        # Find concrete Handler subclasses in the module
        handler_classes: list[type[Handler]] = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Handler)
                and attr is not Handler
                and not attr.__name__.startswith("_")
                and not inspect.isabstract(attr)
            ):
                handler_classes.append(attr)

        if len(handler_classes) > 1:
            class_names = [cls.__name__ for cls in handler_classes]
            logger.warning(
                "Multiple Handler subclasses found in %s: %s. Using first: %s",
                file_path.name,
                ", ".join(class_names),
                class_names[0],
            )

        handler_class = handler_classes[0] if handler_classes else None

        if handler_class is None:
            logger.warning("No Handler subclass found in project handler file: %s", file_path.name)
            return None

        # Instantiate the handler
        try:
            handler = handler_class()
        except Exception as e:
            logger.warning(
                "Failed to instantiate project handler from %s: %s",
                file_path.name,
                e,
            )
            return None

        # Validate acceptance tests (warn but don't fail)
        try:
            acceptance_tests = handler.get_acceptance_tests()
            if not acceptance_tests:
                logger.warning(
                    "Project handler '%s' from %s does not define acceptance tests",
                    handler.name,
                    file_path.name,
                )
        except Exception as e:
            logger.warning(
                "Project handler '%s' from %s failed to return acceptance tests: %s",
                handler.name,
                file_path.name,
                e,
            )

        logger.info(
            "Loaded project handler '%s' from %s (priority=%d, terminal=%s)",
            handler.name,
            file_path.name,
            handler.priority,
            handler.terminal,
        )
        return handler

    @staticmethod
    def discover_handlers(
        project_handlers_path: Path,
    ) -> list[tuple[EventType, Handler]]:
        """Discover project handlers from convention-based directory structure.

        Scans event-type subdirectories (pre_tool_use/, post_tool_use/, etc.)
        for Python files containing Handler subclasses. Skips files starting
        with '_' or 'test_'.

        Args:
            project_handlers_path: Path to the project handlers root directory

        Returns:
            List of (EventType, Handler) tuples for discovered handlers
        """
        if not project_handlers_path.exists() or not project_handlers_path.is_dir():
            logger.debug("Project handlers directory does not exist: %s", project_handlers_path)
            return []

        results: list[tuple[EventType, Handler]] = []

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = project_handlers_path / dir_name
            if not event_dir.is_dir():
                continue

            for py_file in sorted(event_dir.glob("*.py")):
                # Skip files starting with '_' (includes __init__.py)
                if py_file.name.startswith("_"):
                    continue

                # Skip test files
                if py_file.name.startswith("test_"):
                    continue

                handler = ProjectHandlerLoader.load_handler_from_file(py_file)
                if handler is not None:
                    results.append((event_type, handler))

        logger.info(
            "Discovered %d project handlers from %s",
            len(results),
            project_handlers_path,
        )
        return results
