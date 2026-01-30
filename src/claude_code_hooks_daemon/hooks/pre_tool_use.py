#!/usr/bin/env python3
"""PreToolUse hook entry point.

This script is called by Claude Code before each tool use.
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
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.pre_tool_use.absolute_path import (
    AbsolutePathHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import (
    BritishEnglishHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.eslint_disable import (
    EslintDisableHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.go_qa_suppression_blocker import (
    GoQaSuppressionBlocker,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.hello_world import (
    HelloWorldPreToolUseHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import (
    NpmCommandHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.php_qa_suppression_blocker import (
    PhpQaSuppressionBlocker,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_time_estimates import (
    PlanTimeEstimatesHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import (
    PlanWorkflowHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.python_qa_suppression_blocker import (
    PythonQaSuppressionBlocker,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
    TddEnforcementHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.validate_plan_number import (
    ValidatePlanNumberHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.web_search_year import (
    WebSearchYearHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
    WorktreeFileCopyHandler,
)
from claude_code_hooks_daemon.plugins import PluginLoader


def get_builtin_handlers() -> dict[str, type]:
    """Map of built-in handler names to classes.

    Returns:
        Dictionary mapping handler names to handler classes
    """
    return {
        "destructive_git": DestructiveGitHandler,
        "git_stash": GitStashHandler,
        "absolute_path": AbsolutePathHandler,
        "web_search_year": WebSearchYearHandler,
        "british_english": BritishEnglishHandler,
        "eslint_disable": EslintDisableHandler,
        "python_qa_suppression_blocker": PythonQaSuppressionBlocker,
        "php_qa_suppression_blocker": PhpQaSuppressionBlocker,
        "go_qa_suppression_blocker": GoQaSuppressionBlocker,
        "tdd_enforcement": TddEnforcementHandler,
        "sed_blocker": SedBlockerHandler,
        "worktree_file_copy": WorktreeFileCopyHandler,
        "validate_plan_number": ValidatePlanNumberHandler,
        "markdown_organization": MarkdownOrganizationHandler,
        "plan_time_estimates": PlanTimeEstimatesHandler,
        "plan_workflow": PlanWorkflowHandler,
        "npm_command": NpmCommandHandler,
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
    """Main entry point for PreToolUse hook."""
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
    controller = FrontController(event_name="PreToolUse")

    # 2.5. Register hello_world handler if enabled (runs first with priority 5)
    if config.get("daemon", {}).get("enable_hello_world_handlers", False):
        controller.register(HelloWorldPreToolUseHandler())

    # 3. Register built-in handlers (if enabled)
    builtin_handlers = get_builtin_handlers()
    pre_tool_use_config = config.get("handlers", {}).get("pre_tool_use", {})

    # Extract tag filters from event config
    enable_tags = pre_tool_use_config.get("enable_tags")
    disable_tags = pre_tool_use_config.get("disable_tags", [])

    for handler_name, handler_class in builtin_handlers.items():
        handler_config = pre_tool_use_config.get(handler_name, {})

        # Default to enabled if not explicitly disabled
        if not handler_config.get("enabled", True):
            continue

        # Instantiate handler to get its tags
        try:
            handler = handler_class()
        except RuntimeError:
            # Skip handlers that require ProjectContext when it's not initialized
            # (This happens in edge cases like no config file)
            continue

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

    # 4. Load plugin handlers
    plugins_config = config.get("plugins", [])
    for plugin in plugins_config:
        handlers = PluginLoader.load_handlers_from_config(plugin)
        for handler in handlers:
            controller.register(handler)

    # 5. Run dispatcher
    controller.run()


if __name__ == "__main__":
    main()
