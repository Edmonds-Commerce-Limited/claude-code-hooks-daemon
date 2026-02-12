"""Utility modules - Centralized utility functions.

This package contains utility functions used throughout the daemon.
All utilities follow DRY principles - no duplication allowed.
"""

from claude_code_hooks_daemon.utils.guides import get_llm_command_guide_path
from claude_code_hooks_daemon.utils.naming import (
    class_name_to_config_key,
    config_key_to_display_name,
    display_name_to_config_key,
)
from claude_code_hooks_daemon.utils.npm import has_llm_commands_in_package_json

__all__ = [
    "class_name_to_config_key",
    "config_key_to_display_name",
    "display_name_to_config_key",
    "get_llm_command_guide_path",
    "has_llm_commands_in_package_json",
]
