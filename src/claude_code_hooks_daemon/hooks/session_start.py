#!/usr/bin/env python3
"""SessionStart hook entry point.

This script is called by Claude Code when a session starts.
It loads configuration and dispatches to registered handlers.
"""

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
# Allow running as standalone script
if __name__ == "__main__":
    # Add package to path for imports
    package_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(package_root))

from claude_code_hooks_daemon.config import ConfigLoader
from claude_code_hooks_daemon.core import FrontController
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.session_start.hello_world import (
    HelloWorldSessionStartHandler,
)
from claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration import (
    WorkflowStateRestorationHandler,
)
from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
    YoloContainerDetectionHandler,
)


def get_builtin_handlers() -> dict[str, type]:
    """Map of built-in handler names to classes.

    Returns:
        Dictionary mapping handler names to handler classes
    """
    return {
        "workflow_state_restoration": WorkflowStateRestorationHandler,
        "yolo_container_detection": YoloContainerDetectionHandler,
    }


def load_config_safe(config_path: Path) -> dict[str, Any]:
    """Load configuration file with fallback to defaults.

    Args:
        config_path: Path to configuration file

    Returns:
        Configuration dictionary (loaded from file or defaults)
    """
    try:
        return ConfigLoader.load(config_path)
    except (FileNotFoundError, ValueError):
        # Fallback to defaults if config not found or invalid
        return ConfigLoader.get_default_config()


def main() -> None:
    """Main entry point for SessionStart hook."""
    # 1. Load configuration with safe fallback
    try:
        config_path = ConfigLoader.find_config()
    except FileNotFoundError:
        # Use default config path (will fallback to defaults in load_config_safe)
        config_path = Path(".claude/hooks-daemon.yaml")

    config = load_config_safe(config_path)

    # 1.5. Initialize ProjectContext (required for handlers that use it)
    # Only initialize if config file exists (skip for default config scenarios)
    if config_path.exists():
        ProjectContext.initialize(config_path)

    # 2. Create front controller
    controller = FrontController(event_name="SessionStart")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldSessionStartHandler())

    # 3. Register built-in handlers (if enabled)
    builtin_handlers = get_builtin_handlers()
    session_start_config = config.get("handlers", {}).get("session_start", {})

    # Extract tag filters from event config
    enable_tags = session_start_config.get("enable_tags")
    disable_tags = session_start_config.get("disable_tags", [])

    for handler_name, handler_class in builtin_handlers.items():
        handler_config = session_start_config.get(handler_name, {})

        # Default to enabled if not explicitly disabled
        if not handler_config.get("enabled", True):
            continue

        # Instantiate handler to get its tags

        try:
            handler = handler_class()

        except RuntimeError as e:

            logger.warning(
                "Skipping handler %s (requires ProjectContext): %s", handler_class.__name__, e
            )

            continue

        # Tag-based filtering
        if enable_tags and not any(tag in handler.tags for tag in enable_tags):
            continue  # Skip - no matching tags

        if disable_tags and any(tag in handler.tags for tag in disable_tags):
            continue  # Skip - has disabled tag

        # Special configuration for YoloContainerDetectionHandler
        if handler_name == "yolo_container_detection":
            handler_settings = {
                "min_confidence_score": handler_config.get("min_confidence_score", 3),
                "show_detailed_indicators": handler_config.get("show_detailed_indicators", True),
                "show_workflow_tips": handler_config.get("show_workflow_tips", True),
            }
            handler.configure(handler_settings)

        # Override priority from config if specified
        priority = handler_config.get("priority")
        if priority is not None:
            handler.priority = priority

        controller.register(handler)

    # 4. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
