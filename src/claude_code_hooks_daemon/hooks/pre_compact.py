#!/usr/bin/env python3
"""PreCompact hook entry point.

This script is called by Claude Code before compaction.
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
from claude_code_hooks_daemon.handlers.pre_compact.hello_world import (
    HelloWorldPreCompactHandler,
)
from claude_code_hooks_daemon.handlers.pre_compact.workflow_state_pre_compact import (
    WorkflowStatePreCompactHandler,
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
    """Main entry point for PreCompact hook."""
    # 1. Load configuration with safe fallback
    try:
        config_path = ConfigLoader.find_config()
    except FileNotFoundError:
        # Use default config path (will fallback to defaults in load_config_safe)
        config_path = Path(".claude/hooks-daemon.yaml")

    config = load_config_safe(config_path)

    # 2. Create front controller
    controller = FrontController(event_name="PreCompact")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldPreCompactHandler())

    # 3. Register built-in handlers
    pre_compact_config = config.get("handlers", {}).get("pre_compact", {})

    # WorkflowStatePreCompactHandler - always enabled by default
    workflow_config = pre_compact_config.get("workflow_state_pre_compact", {})
    if workflow_config.get("enabled", True):
        controller.register(WorkflowStatePreCompactHandler())

    # 4. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
