"""Plugin loader for dynamic handler loading."""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Handler

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
            logger.error(f"Failed to import plugin {handler_name}: {e}")
            return None

        # Find the Handler class
        class_name = PluginLoader.snake_to_pascal(handler_name)

        if not hasattr(module, class_name):
            logger.error(f"Plugin module {handler_name} does not contain class {class_name}")
            return None

        handler_class_raw = getattr(module, class_name)

        # Validate it's a Handler subclass
        if not (inspect.isclass(handler_class_raw) and issubclass(handler_class_raw, Handler)):
            logger.error(f"Class {class_name} in {handler_name} is not a Handler subclass")
            return None

        # Instantiate the handler
        try:
            # Handlers are responsible for their own initialization
            # They must call super().__init__(name=..., priority=..., terminal=...)
            # Type ignore: handler_class_raw is verified as Handler subclass but mypy sees it as Any
            handler = handler_class_raw()  # type: ignore[call-arg]
            return handler
        except Exception as e:
            logger.error(f"Failed to instantiate handler {class_name}: {e}")
            return None

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
    def load_handlers_from_config(plugin_config: dict[str, Any]) -> list[Handler]:
        """Load handlers from plugin configuration.

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
