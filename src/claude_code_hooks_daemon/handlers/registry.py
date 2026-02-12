"""Centralised handler registry for discovering and loading handlers.

This module provides functionality for discovering handler classes
in the handlers directory and registering them with the event router.
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import ConfigKey
from claude_code_hooks_daemon.constants.handlers import HandlerID
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
    "status_line": EventType.STATUS_LINE,
}


class HandlerRegistry:
    """Registry for discovering and managing handlers.

    Discovers handler classes from the handlers package and
    registers them with the event router.
    """

    __slots__ = ("_disabled_handlers", "_handlers", "_workspace_root")

    def __init__(self) -> None:
        """Initialise empty registry."""
        self._handlers: dict[str, type[Handler]] = {}
        self._disabled_handlers: set[str] = set()
        self._workspace_root: Path | None = None

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
                        and not inspect.isabstract(attr)
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
        workspace_root: Path | None = None,
        project_languages: list[str] | None = None,
    ) -> int:
        """Register all discovered handlers with the router.

        Uses a two-pass algorithm to support handler options inheritance:
        1. First pass: collect all handler options into options_registry
        2. Second pass: instantiate handlers and apply inherited options

        Args:
            router: Event router to register handlers with
            config: Optional handler configuration from hooks-daemon.yaml
            workspace_root: Optional workspace root path for handlers
            project_languages: Project-level language filter from daemon.languages config

        Returns:
            Number of handlers registered
        """
        # Store workspace_root for handler initialization
        if workspace_root:
            self._workspace_root = workspace_root

        # PASS 1: Collect all handler options
        options_registry: dict[str, dict[str, Any]] = {}
        handlers_dir = Path(__file__).parent

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            if not event_dir.is_dir():
                continue

            event_config = (config or {}).get(dir_name) or {}

            for py_file in event_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                module_name = f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"

                # FAIL FAST: If a production handler fails to import, that's a critical error
                # Test fixtures are loaded separately via plugins, not through this path
                module = importlib.import_module(module_name)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Handler)
                        and attr is not Handler
                        and not attr.__name__.startswith("_")
                        and not inspect.isabstract(attr)
                    ):
                        config_key = _get_config_key(attr.__name__)
                        handler_config = event_config.get(config_key, {})
                        if handler_config.get(ConfigKey.ENABLED, True):
                            # Use config key from HandlerID constant
                            try:
                                registry_key = f"{event_type.value}.{config_key}"
                                options = handler_config.get(ConfigKey.OPTIONS, {})
                                # Include workspace_root in options if available
                                if self._workspace_root:
                                    options["workspace_root"] = self._workspace_root
                                options_registry[registry_key] = options
                            except Exception:
                                logger.debug(
                                    "Failed to collect options for handler '%s': %s",
                                    config_key,
                                    exc_info=True,
                                )

        # PASS 2: Register handlers with inherited options
        count = 0

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            if not event_dir.is_dir():
                continue

            # Get configuration for this event type
            event_config = (config or {}).get(dir_name) or {}

            # Extract tag filters from event config
            enable_tags = event_config.get(ConfigKey.ENABLE_TAGS)
            disable_tags_raw: Any = event_config.get(ConfigKey.DISABLE_TAGS, [])
            disable_tags: list[str] = disable_tags_raw if isinstance(disable_tags_raw, list) else []

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
                        and not inspect.isabstract(attr)
                    ):
                        # Check handler-specific config (use config key from HandlerID constant)
                        config_key = _get_config_key(attr.__name__)
                        handler_config = event_config.get(config_key, {})

                        # Skip disabled handlers
                        if not handler_config.get(ConfigKey.ENABLED, True):
                            logger.debug("Handler %s is disabled", attr.__name__)
                            continue

                        if self.is_disabled(attr.__name__):
                            logger.debug("Handler %s is disabled in registry", attr.__name__)
                            continue

                        try:
                            # Instantiate and register
                            # Handler subclasses override __init__ with no args
                            instance = attr()

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
                            if ConfigKey.PRIORITY in handler_config:
                                instance.priority = handler_config[ConfigKey.PRIORITY]

                            # Apply options inheritance if handler shares options with parent
                            registry_key = f"{event_type.value}.{config_key}"
                            handler_options = options_registry.get(registry_key, {})

                            if instance.shares_options_with:
                                # Get parent options
                                parent_key = f"{event_type.value}.{instance.shares_options_with}"
                                parent_options = options_registry.get(parent_key, {})
                                # Merge: parent options + child overrides
                                merged_options = {**parent_options, **handler_options}
                            else:
                                merged_options = handler_options

                            # Apply all options as private attributes (generic for all handlers)
                            for option_key, option_value in merged_options.items():
                                setattr(instance, f"_{option_key}", option_value)

                            # Inject project-level language filter (via setattr like other options)
                            instance._project_languages = project_languages

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
        snake_case string with _handler suffix stripped
    """
    import re

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Strip _handler suffix to match config keys
    if snake.endswith("_handler"):
        snake = snake[:-8]  # Remove "_handler"

    return snake


def _get_config_key_from_constant(class_name: str) -> str | None:
    """Look up config_key from HandlerID constant by class name.

    Args:
        class_name: Handler class name (e.g., "DestructiveGitHandler")

    Returns:
        config_key from HandlerID constant, or None if not found
    """
    from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

    # Build reverse mapping: class_name -> HandlerID constant
    for attr_name in dir(HandlerID):
        if attr_name.startswith("_"):
            continue

        attr = getattr(HandlerID, attr_name)
        if isinstance(attr, HandlerIDMeta) and attr.class_name == class_name:
            return str(attr.config_key)

    return None


def _get_config_key(class_name: str) -> str:
    """Get config key for a handler class.

    Uses HandlerID constants as single source of truth, with fallback to
    auto-generation for backward compatibility.

    Args:
        class_name: Handler class name (e.g., "DestructiveGitHandler")

    Returns:
        config_key for use in YAML config
    """
    # PRIMARY: Look up in HandlerID constants (single source of truth)
    constant_key = _get_config_key_from_constant(class_name)
    if constant_key is not None:
        return constant_key

    # FALLBACK: Auto-generate with deprecation warning
    auto_key = _to_snake_case(class_name)
    logger.warning(
        "Handler %s not found in HandlerID constants, using auto-generated key '%s'. "
        "Add a HandlerID constant for this handler.",
        class_name,
        auto_key,
    )
    return auto_key


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
