"""Configuration initialization module.

Provides template generation for hooks-daemon.yaml configuration files.
Supports minimal and full configuration modes with helpful comments.
"""

from typing import Literal


class ConfigTemplate:
    """Generate configuration templates for hooks-daemon.yaml.

    Provides two modes:
    - minimal: Essential configuration with no examples
    - full: Complete configuration with all hook events and example handlers
    """

    @staticmethod
    def generate_minimal() -> str:
        """Generate minimal configuration template.

        Returns:
            YAML configuration string with essential fields only
        """
        return """version: "1.0"

# Daemon Settings
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes
  log_level: INFO            # DEBUG, INFO, WARNING, ERROR
  enable_hello_world_handlers: false  # Set true to confirm hooks working

# Handler Configuration
# Enable/disable handlers per event type
# Priority: lower numbers run first (5-60 range)

handlers:
  # PreToolUse - Before tool execution
  pre_tool_use: {}

  # PostToolUse - After tool execution
  post_tool_use: {}

  # PermissionRequest - Auto-approve decisions
  permission_request: {}

  # Notification - Custom notification handling
  notification: {}

  # UserPromptSubmit - Context injection before processing
  user_prompt_submit: {}

  # SessionStart - Initialize environment
  session_start: {}

  # SessionEnd - Cleanup on exit
  session_end: {}

  # Stop - Control agent continuation
  stop: {}

  # SubagentStop - Control subagent continuation
  subagent_stop: {}

  # PreCompact - Before conversation compaction
  pre_compact: {}

# Custom project-specific handlers
plugins: []
"""

    @staticmethod
    def generate_full() -> str:
        """Generate full configuration template with examples.

        Returns:
            YAML configuration string with all hook events and example handlers
        """
        return """version: "1.0"

# Daemon Settings
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes
  log_level: INFO            # DEBUG, INFO, WARNING, ERROR
  enable_hello_world_handlers: false  # Set true to confirm hooks working

# Handler Configuration
# Enable/disable handlers per event type
# Priority: lower numbers run first (5-60 range)

handlers:
  # PreToolUse - Before tool execution
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
    # git_stash: {enabled: false, priority: 20}
    # absolute_path: {enabled: false, priority: 12}
    # web_search_year: {enabled: false, priority: 55}
    # british_english: {enabled: false, priority: 60}
    # eslint_disable: {enabled: false, priority: 15}
    # sed_blocker: {enabled: false, priority: 25}
    # worktree_file_copy: {enabled: false, priority: 30}
    # tdd_enforcement: {enabled: false, priority: 35}

  # PostToolUse - After tool execution
  post_tool_use: {}
    # bash_error_detector: {enabled: false, priority: 10}

  # PermissionRequest - Auto-approve decisions
  permission_request: {}
    # auto_approve_reads: {enabled: false, priority: 10}
    # auto_approve_safe_files: {enabled: false, priority: 15}

  # Notification - Custom notification handling
  notification: {}
    # notification_logger: {enabled: false, priority: 10}

  # UserPromptSubmit - Context injection before processing
  user_prompt_submit: {}
    # git_context_injector: {enabled: false, priority: 10}

  # SessionStart - Initialize environment
  session_start: {}
    # environment_loader: {enabled: false, priority: 10}

  # SessionEnd - Cleanup on exit
  session_end: {}
    # cleanup_handler: {enabled: false, priority: 10}

  # Stop - Control agent continuation
  stop: {}
    # task_completion_checker: {enabled: false, priority: 10}

  # SubagentStop - Control subagent continuation
  subagent_stop: {}
    # subagent_logger: {enabled: false, priority: 10}

  # PreCompact - Before conversation compaction
  pre_compact: {}
    # transcript_archiver: {enabled: false, priority: 10}

# Custom project-specific handlers
plugins: []
  # Example:
  # - path: .claude/hooks/custom
  #   handlers:
  #     - custom_handler_one
  #     - custom_handler_two
"""


def generate_config(mode: Literal["minimal", "full"] = "full") -> str:
    """Generate configuration template.

    Args:
        mode: Configuration mode - "minimal" or "full" (default: "full")

    Returns:
        YAML configuration string
    """
    if mode == "minimal":
        return ConfigTemplate.generate_minimal()
    else:
        return ConfigTemplate.generate_full()
