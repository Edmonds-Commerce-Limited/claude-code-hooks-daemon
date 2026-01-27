"""Centralised handler registry for discovering and loading handlers.

This module provides functionality for discovering handler classes
in the handlers directory and registering them with the event router.
"""

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.router import EventRouter

logger = logging.getLogger(__name__)

# Mapping from directory name to EventType
EVENT_TYPE_MAPPING: dict[str, EventType] = {
    "pre_tool_use": EventType.PRE_TOOL_USE,
    "post_tool_use": EventType.POST_TOOL_USE,
    "session_start": EventType.SESSION_START,
    "session_end": EventType.SESSION_END,
    "pre_compact": EventType.PRE_COMPACT,
    "user_prompt_submit": EventType.USER_PROMPT_SUBMIT,
    "permission_request": EventType.PERMISSION_REQUEST,
    "notification": EventType.NOTIFICATION,
    "stop": EventType.STOP,
    "subagent_stop": EventType.SUBAGENT_STOP,
}


class HandlerRegistry:
    """Registry for discovering and managing handlers.

    Discovers handler classes from the handlers package and
    registers them with the event router.
    """

    __slots__ = ("_disabled_handlers", "_handlers")

    def __init__(self) -> None:
        """Initialise empty registry."""
        self._handlers: dict[str, type[Handler]] = {}
        self._disabled_handlers: set[str] = set()

    def discover(self, package_path: str = "claude_code_hooks_daemon.handlers") -> int:
        """Discover all handler classes in the handlers package.

        Scans all subpackages (pre_tool_use, post_tool_use, etc.) and
        loads all Handler subclasses found.

        Args:
            package_path: Python package path to scan

        Returns:
            Number of handlers discovered
        """
        try:
            package = importlib.import_module(package_path)
        except ImportError:
            logger.warning("Could not import handlers package: %s", package_path)
            return 0

        if not hasattr(package, "__path__"):
            logger.warning("Package %s has no __path__", package_path)
            return 0

        count = 0
        for _importer, modname, ispkg in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{package_path}.",
        ):
            if ispkg:
                continue

            # Skip __init__ modules and test files
            if modname.endswith("__init__") or "test" in modname:
                continue

            try:
                module = importlib.import_module(modname)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Handler)
                        and attr is not Handler
                        and not attr.__name__.startswith("_")
                    ):
                        self._handlers[attr.__name__] = attr
                        count += 1
                        logger.debug("Discovered handler: %s", attr.__name__)
            except Exception as e:
                logger.warning("Failed to load module %s: %s", modname, e)

        logger.info("Discovered %d handlers", count)
        return count

    def disable(self, handler_name: str) -> None:
        """Disable a handler by name.

        Disabled handlers will not be registered with the router.

        Args:
            handler_name: Name of handler class to disable
        """
        self._disabled_handlers.add(handler_name)

    def enable(self, handler_name: str) -> None:
        """Enable a previously disabled handler.

        Args:
            handler_name: Name of handler class to enable
        """
        self._disabled_handlers.discard(handler_name)

    def is_disabled(self, handler_name: str) -> bool:
        """Check if a handler is disabled.

        Args:
            handler_name: Name of handler class

        Returns:
            True if handler is disabled
        """
        return handler_name in self._disabled_handlers

    def get_handler_class(self, name: str) -> type[Handler] | None:
        """Get a handler class by name.

        Args:
            name: Handler class name

        Returns:
            Handler class or None if not found
        """
        return self._handlers.get(name)

    def list_handlers(self) -> list[str]:
        """List all discovered handler class names.

        Returns:
            List of handler class names
        """
        return list(self._handlers.keys())

    def register_all(
        self,
        router: "EventRouter",
        *,
        config: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> int:
        """Register all discovered handlers with the router.

        Args:
            router: Event router to register handlers with
            config: Optional handler configuration from hooks-daemon.yaml

        Returns:
            Number of handlers registered
        """
        count = 0
        handlers_dir = Path(__file__).parent

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            if not event_dir.is_dir():
                continue

            # Get configuration for this event type
            event_config = (config or {}).get(dir_name) or {}

            # Extract tag filters from event config
            enable_tags = event_config.get("enable_tags")
            disable_tags = event_config.get("disable_tags", [])

            # Find all Python files in the directory
            for py_file in event_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                module_name = f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"

                try:
                    module = importlib.import_module(module_name)
                except Exception as e:
                    logger.warning("Failed to import %s: %s", module_name, e)
                    continue

                # Find Handler subclasses in the module
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Handler)
                        and attr is not Handler
                        and not attr.__name__.startswith("_")
                    ):
                        # Check handler-specific config
                        handler_config = event_config.get(_to_snake_case(attr.__name__), {})

                        # Skip disabled handlers
                        if not handler_config.get("enabled", True):
                            logger.debug("Handler %s is disabled", attr.__name__)
                            continue

                        if self.is_disabled(attr.__name__):
                            logger.debug("Handler %s is disabled in registry", attr.__name__)
                            continue

                        try:
                            # Instantiate and register
                            # Handler subclasses override __init__ with no args
                            instance = attr()  # type: ignore[call-arg]

                            # Tag-based filtering
                            if enable_tags and not any(tag in instance.tags for tag in enable_tags):
                                logger.debug(
                                    "Handler %s skipped - no matching tags in enable_tags %s",
                                    attr.__name__,
                                    enable_tags,
                                )
                                continue

                            if disable_tags and any(tag in instance.tags for tag in disable_tags):
                                logger.debug(
                                    "Handler %s skipped - has tag in disable_tags %s",
                                    attr.__name__,
                                    disable_tags,
                                )
                                continue

                            # Override priority from config if specified
                            if "priority" in handler_config:
                                instance.priority = handler_config["priority"]

                            router.register(event_type, instance)
                            count += 1
                            logger.debug(
                                "Registered %s for %s (priority=%d, tags=%s)",
                                attr.__name__,
                                event_type.value,
                                instance.priority,
                                instance.tags,
                            )
                        except Exception as e:
                            logger.warning("Failed to instantiate %s: %s", attr.__name__, e)

        logger.info("Registered %d handlers with router", count)
        return count


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case.

    Args:
        name: CamelCase string

    Returns:
        snake_case string
    """
    import re

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# Global registry instance
_registry: HandlerRegistry | None = None


def get_registry() -> HandlerRegistry:
    """Get the global handler registry.

    Creates the registry on first access and discovers handlers.

    Returns:
        Global HandlerRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = HandlerRegistry()
        _registry.discover()
    return _registry
