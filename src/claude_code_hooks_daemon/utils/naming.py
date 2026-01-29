"""Centralized naming conversion utilities.

Single source of truth for converting between naming formats.
Eliminates duplication of _to_snake_case() across multiple files.

Before this module existed, the _to_snake_case() function was duplicated in:
- handlers/registry.py
- config/models.py
- config/validator.py

Now there is ONE implementation with comprehensive tests.

Usage:
    from claude_code_hooks_daemon.utils.naming import class_name_to_config_key

    # Convert handler class name to config key
    config_key = class_name_to_config_key("DestructiveGitHandler")
    # Result: "destructive_git"
"""

import re


def class_name_to_config_key(class_name: str) -> str:
    """Convert handler class name to config key.

    Removes "Handler" suffix and converts PascalCase to snake_case.

    Examples:
        DestructiveGitHandler -> destructive_git
        SedBlockerHandler -> sed_blocker
        HelloWorldPreToolUseHandler -> hello_world_pre_tool_use
        TDDEnforcementHandler -> tdd_enforcement

    Args:
        class_name: Python class name (PascalCase, may include Handler suffix)

    Returns:
        Config key in snake_case without Handler suffix
    """
    # Remove Handler suffix if present
    name = class_name.removesuffix("Handler")

    # Convert PascalCase to snake_case
    # Handle sequences of capitals followed by lowercase (e.g., "TDD" -> "tdd")
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Handle transition from lowercase/digit to uppercase (e.g., "git2HTTP" -> "git2_http")
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)

    return s2.lower()


def config_key_to_display_name(config_key: str) -> str:
    """Convert config key to display name.

    Replaces underscores with hyphens for kebab-case display format.

    Examples:
        destructive_git -> destructive-git
        sed_blocker -> sed-blocker
        hello_world_pre_tool_use -> hello-world-pre-tool-use

    Args:
        config_key: Config key in snake_case

    Returns:
        Display name in kebab-case
    """
    return config_key.replace("_", "-")


def display_name_to_config_key(display_name: str) -> str:
    """Convert display name back to config key.

    Replaces hyphens with underscores for snake_case config format.

    Examples:
        destructive-git -> destructive_git
        sed-blocker -> sed_blocker
        hello-world-pre-tool-use -> hello_world_pre_tool_use

    Args:
        display_name: Display name in kebab-case

    Returns:
        Config key in snake_case
    """
    return display_name.replace("-", "_")
