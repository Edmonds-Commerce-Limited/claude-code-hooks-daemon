#!/usr/bin/env python3
"""SessionStart hook entry point.

This script is called by Claude Code when a session starts.
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
from claude_code_hooks_daemon.handlers.session_start.hello_world import (
    HelloWorldSessionStartHandler,
)
from claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration import (
    WorkflowStateRestorationHandler,
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
    """Main entry point for SessionStart hook."""
    # 1. Load configuration with safe fallback
    try:
        config_path = ConfigLoader.find_config()
    except FileNotFoundError:
        # Use default config path (will fallback to defaults in load_config_safe)
        config_path = Path(".claude/hooks-daemon.yaml")

    config = load_config_safe(config_path)

    # 2. Create front controller
    controller = FrontController(event_name="SessionStart")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldSessionStartHandler())

    # 3. Register built-in handlers
    session_start_config = config.get("handlers", {}).get("session_start", {})

    # WorkflowStateRestorationHandler - always enabled by default
    workflow_config = session_start_config.get("workflow_state_restoration", {})
    if workflow_config.get("enabled", True):
        controller.register(WorkflowStateRestorationHandler())

    # 4. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
