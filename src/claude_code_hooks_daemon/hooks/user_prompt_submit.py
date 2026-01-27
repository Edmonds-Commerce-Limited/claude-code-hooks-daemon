#!/usr/bin/env python3
"""UserPromptSubmit hook entry point.

This script is called by Claude Code when user submits a prompt.
It loads configuration and dispatches to registered handlers.
"""

import sys
from pathlib import Path
from typing import Any

# Allow running as standalone script
if __name__ == "__main__":
    # Add package to path for imports
    package_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(package_root))

from claude_code_hooks_daemon.config import ConfigLoader
from claude_code_hooks_daemon.core import FrontController
from claude_code_hooks_daemon.handlers.user_prompt_submit.auto_continue import (
    AutoContinueHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
    GitContextInjectorHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.hello_world import (
    HelloWorldUserPromptSubmitHandler,
)


def get_builtin_handlers() -> dict[str, type]:
    """Map of built-in handler names to classes.

    Returns:
        Dictionary mapping handler names to handler classes
    """
    return {
        "git_context_injector": GitContextInjectorHandler,
        "auto_continue": AutoContinueHandler,
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
    """Main entry point for UserPromptSubmit hook."""
    # 1. Load configuration with safe fallback
    try:
        config_path = ConfigLoader.find_config()
    except FileNotFoundError:
        # Use default config path (will fallback to defaults in load_config_safe)
        config_path = Path(".claude/hooks-daemon.yaml")

    config = load_config_safe(config_path)

    # 2. Create front controller
    controller = FrontController(event_name="UserPromptSubmit")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldUserPromptSubmitHandler())

    # 3. Register built-in handlers (if enabled)
    builtin_handlers = get_builtin_handlers()
    user_prompt_submit_config = config.get("handlers", {}).get("user_prompt_submit", {})

    # Extract tag filters from event config
    enable_tags = user_prompt_submit_config.get("enable_tags")
    disable_tags = user_prompt_submit_config.get("disable_tags", [])

    for handler_name, handler_class in builtin_handlers.items():
        handler_config = user_prompt_submit_config.get(handler_name, {})

        # Default to enabled if not explicitly disabled
        if not handler_config.get("enabled", True):
            continue

        # Instantiate handler to get its tags
        handler = handler_class()

        # Tag-based filtering
        if enable_tags and not any(tag in handler.tags for tag in enable_tags):
            continue  # Skip - no matching tags

        if disable_tags and any(tag in handler.tags for tag in disable_tags):
            continue  # Skip - has disabled tag

        # Override priority from config if specified
        priority = handler_config.get("priority")
        if priority is not None:
            handler.priority = priority

        controller.register(handler)

    # 4. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
