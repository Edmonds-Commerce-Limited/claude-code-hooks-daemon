"""Plugin loader for dynamic handler loading."""

import importlib.util
import inspect
import logging
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.core import Handler
from claude_code_hooks_daemon.utils.error_formatter import format_plugin_load_error

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import PluginsConfig

logger = logging.getLogger(__name__)


class PluginLoader:
    """Load handlers from external plugin paths."""

    @staticmethod
    def snake_to_pascal(name: str) -> str:
        """Convert snake_case to PascalCase.

        Args:
            name: Snake case string (e.g., "my_handler_v2")

        Returns:
            PascalCase string (e.g., "MyHandlerV2")

        Examples:
            >>> PluginLoader.snake_to_pascal("test_handler")
            'TestHandler'
            >>> PluginLoader.snake_to_pascal("handler_v2")
            'HandlerV2'
        """
        if not name:
            return ""

        # Remove leading/trailing underscores and split
        parts = name.strip("_").split("_")

        # Filter out empty strings from multiple underscores
        parts = [p for p in parts if p]

        # Capitalize first letter of each part
        return "".join(word.capitalize() for word in parts)

    @staticmethod
    def load_handler(
        handler_name: str,
        plugin_path: Path,
    ) -> Handler | None:
        """Load a handler from a plugin path.

        Args:
            handler_name: Name of the handler module (without .py extension)
            plugin_path: Path to directory containing the handler module

        Returns:
            Handler instance if successful, None otherwise

        Note:
            Handlers are responsible for their own initialization and must
            call super().__init__(name=..., priority=..., terminal=...)
        """
        module_path = plugin_path / f"{handler_name}.py"

        if not module_path.exists():
            logger.error(f"Plugin module not found: {module_path}")
            return None

        # Import the module
        try:
            spec = importlib.util.spec_from_file_location(handler_name, module_path)
            if spec is None or spec.loader is None:
                logger.error(f"Failed to create module spec for: {module_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[handler_name] = module
            spec.loader.exec_module(module)

        except Exception as e:
            # Try to provide enhanced error message
            tb_text = traceback.format_exc()
            enhanced_error = format_plugin_load_error(tb_text, str(module_path))

            if enhanced_error:
                logger.error(
                    f"Failed to import plugin {handler_name}:\n{enhanced_error.format_for_display()}"
                )
            else:
                logger.error(f"Failed to import plugin {handler_name}: {e}")

            return None

        # Find the Handler class (try both with and without "Handler" suffix)
        class_name = PluginLoader.snake_to_pascal(handler_name)
        class_name_with_suffix = f"{class_name}Handler"

        # Try with "Handler" suffix first (common convention)
        if hasattr(module, class_name_with_suffix):
            handler_class_raw = getattr(module, class_name_with_suffix)
        elif hasattr(module, class_name):
            handler_class_raw = getattr(module, class_name)
        else:
            logger.error(
                f"Plugin module {handler_name} does not contain class {class_name} or {class_name_with_suffix}"
            )
            return None

        # Validate it's a Handler subclass
        if not (inspect.isclass(handler_class_raw) and issubclass(handler_class_raw, Handler)):
            logger.error(f"Class {class_name} in {handler_name} is not a Handler subclass")
            return None

        # Instantiate the handler
        try:
            # Handlers are responsible for their own initialization
            # They must call super().__init__(handler_id=..., priority=..., terminal=...)
            handler = handler_class_raw()
        except Exception as e:
            # Try to provide enhanced error message
            tb_text = traceback.format_exc()
            enhanced_error = format_plugin_load_error(tb_text, str(module_path))

            if enhanced_error:
                logger.error(
                    f"Failed to instantiate handler {class_name}:\n{enhanced_error.format_for_display()}"
                )
            else:
                logger.error(f"Failed to instantiate handler {class_name}: {e}")

            return None

        # Validate acceptance tests
        try:
            acceptance_tests = handler.get_acceptance_tests()
            if not acceptance_tests:
                logger.warning(
                    f"Plugin handler '{handler.name}' (class {class_name}) does not define "
                    f"any acceptance tests. Plugin handlers must define at least one acceptance "
                    f"test via get_acceptance_tests(). See CLAUDE/AcceptanceTests/PLAYBOOK.md "
                    f"for examples."
                )
        except Exception as e:
            logger.warning(
                f"Plugin handler '{handler.name}' (class {class_name}) failed to return "
                f"acceptance tests: {e}. Handlers must implement get_acceptance_tests() and "
                f"return at least one test."
            )

        return handler

    @staticmethod
    def discover_handlers(plugin_path: Path) -> list[str]:
        """Discover all handler modules in a directory.

        Args:
            plugin_path: Path to directory containing handler modules

        Returns:
            List of handler module names (without .py extension)
        """
        if not plugin_path.exists() or not plugin_path.is_dir():
            return []

        handlers = []
        for file_path in plugin_path.glob("*.py"):
            module_name = file_path.stem

            # Skip __init__.py
            if module_name == "__init__":
                continue

            # Skip test files (test_*.py)
            if module_name.startswith("test_"):
                continue

            handlers.append(module_name)

        return handlers

    @staticmethod
    def load_from_plugins_config(
        plugins_config: "PluginsConfig",
        workspace_root: Path | None = None,
    ) -> list[Handler]:
        """Load handlers from PluginsConfig model (new API).

        This is the preferred method for loading plugins, using the type-safe
        PluginsConfig model from config/models.py.

        Args:
            plugins_config: PluginsConfig instance from configuration file
            workspace_root: Project root for resolving relative plugin paths.
                If None, relative paths are resolved against CWD (fragile).

        Returns:
            List of loaded Handler instances, sorted by priority

        Example:
            >>> from claude_code_hooks_daemon.config.models import PluginsConfig, PluginConfig
            >>> config = PluginsConfig(
            ...     paths=["/path/to/plugins"],
            ...     plugins=[
            ...         PluginConfig(path="my_handler", enabled=True),
            ...     ]
            ... )
            >>> handlers = PluginLoader.load_from_plugins_config(config)
        """
        # Import here to avoid circular dependency
        from claude_code_hooks_daemon.config.models import PluginsConfig

        if not isinstance(plugins_config, PluginsConfig):
            logger.error("plugins_config must be a PluginsConfig instance")
            return []

        if not plugins_config.plugins:
            return []

        loaded_handlers = []

        # Process each plugin configuration
        for plugin_config in plugins_config.plugins:
            # Skip disabled plugins
            if not plugin_config.enabled:
                continue

            # Determine search paths: plugin.path or global paths
            plugin_path = Path(plugin_config.path)

            # Resolve relative paths against workspace_root (not CWD)
            if not plugin_path.is_absolute() and workspace_root is not None:
                resolved_path = workspace_root / plugin_path
            else:
                resolved_path = plugin_path

            # If plugin.path is a file or directory, use it directly
            if resolved_path.is_absolute() and (
                resolved_path.exists() or plugin_path.suffix == ".py"
            ):
                search_paths = [
                    resolved_path.parent if resolved_path.suffix == ".py" else resolved_path
                ]
                handler_module = (
                    resolved_path.stem if resolved_path.suffix == ".py" else resolved_path.name
                )
            else:
                # Use global search paths with plugin.path as module name
                raw_paths = [Path(p) for p in plugins_config.paths]
                # Resolve relative search paths against workspace_root
                if workspace_root is not None:
                    search_paths = [
                        workspace_root / p if not p.is_absolute() else p for p in raw_paths
                    ]
                else:
                    search_paths = raw_paths
                handler_module = plugin_config.path

            # Determine which handlers to load
            if plugin_config.handlers:
                # handlers are class names, but we need module names for load_handler
                # The module name is plugin_config.path (snake_case)
                # We'll load the module and check if the class exists
                # For now, just use the handler_module as the base
                handlers_to_load = [handler_module]
            else:
                # Load all handlers from the module (use snake_case module name)
                handlers_to_load = [handler_module]

            # Load each handler
            for module_name in handlers_to_load:
                handler = None

                # Try each search path
                for search_path in search_paths:
                    handler = PluginLoader.load_handler(module_name, search_path)
                    if handler is not None:
                        break

                if handler is not None:
                    loaded_handlers.append(handler)
                else:
                    # FAIL FAST: If a configured plugin can't be loaded, CRASH
                    raise RuntimeError(
                        f"Failed to load plugin handler from module '{module_name}' "
                        f"(path: '{plugin_config.path}'). "
                        f"Check the plugin file exists and contains a valid Handler class. "
                        f"See daemon logs above for specific loading errors."
                    )

        # Sort by priority (lower number = higher priority)
        loaded_handlers.sort(key=lambda h: h.priority)

        return loaded_handlers

    @staticmethod
    def load_handlers_from_config(plugin_config: dict[str, Any]) -> list[Handler]:
        """Load handlers from plugin configuration (legacy API).

        DEPRECATED: Use load_from_plugins_config() with PluginsConfig model instead.

        Args:
            plugin_config: Plugin configuration dictionary with structure:
                {
                    "enabled": bool,
                    "paths": List[str],
                    "handlers": {
                        "handler_name": {
                            "enabled": bool,
                            "config": {...}
                        }
                    }
                }

        Returns:
            List of loaded Handler instances, sorted by priority
        """
        # Check if plugins are enabled
        if not plugin_config.get("enabled", False):
            return []

        paths = plugin_config.get("paths", [])
        handler_configs = plugin_config.get("handlers", {})

        if not paths or not handler_configs:
            return []

        loaded_handlers = []

        # Load each configured handler
        for handler_name, handler_config in handler_configs.items():
            # Skip if handler is disabled
            if not handler_config.get("enabled", False):
                continue

            # Try to load from each path
            handler = None
            for path_str in paths:
                path = Path(path_str)
                handler = PluginLoader.load_handler(handler_name, path)
                if handler is not None:
                    break

            if handler is not None:
                loaded_handlers.append(handler)
            else:
                logger.warning(f"Failed to load plugin handler: {handler_name}")

        # Sort by priority (lower number = higher priority)
        loaded_handlers.sort(key=lambda h: h.priority)

        return loaded_handlers
