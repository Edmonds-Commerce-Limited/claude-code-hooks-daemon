#!/usr/bin/env python3
"""SubagentStop hook entry point.

This script is called by Claude Code when a subagent stops.
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
from claude_code_hooks_daemon.handlers.subagent_stop.hello_world import (
    HelloWorldSubagentStopHandler,
)
from claude_code_hooks_daemon.handlers.subagent_stop.remind_prompt_library import (
    RemindPromptLibraryHandler,
)
from claude_code_hooks_daemon.handlers.subagent_stop.remind_validator import (
    RemindValidatorHandler,
)


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
    """Main entry point for SubagentStop hook."""
    # 1. Load configuration with safe fallback
    try:
        config_path = ConfigLoader.find_config()
    except FileNotFoundError:
        # Use default config path (will fallback to defaults in load_config_safe)
        config_path = Path(".claude/hooks-daemon.yaml")

    config = load_config_safe(config_path)

    # 2. Create front controller
    controller = FrontController(event_name="SubagentStop")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldSubagentStopHandler())

    # 3. Register built-in handlers
    subagent_stop_config = config.get("handlers", {}).get("subagent_stop", {})

    # RemindValidatorHandler - enabled by default (priority 10)
    validator_config = subagent_stop_config.get("remind_validator", {})
    if validator_config.get("enabled", True):
        controller.register(RemindValidatorHandler())

    # RemindPromptLibraryHandler - enabled by default (priority 100)
    prompt_library_config = subagent_stop_config.get("remind_prompt_library", {})
    if prompt_library_config.get("enabled", True):
        controller.register(RemindPromptLibraryHandler())

    # 4. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
