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
    # SAFETY HANDLERS (Priority 10-20)
    destructive_git_handler: {enabled: true, priority: 10}   # Block git reset --hard, clean -f
    sed_blocker_handler: {enabled: true, priority: 11}       # Block sed (use Edit tool instead)
    absolute_path_handler: {enabled: true, priority: 12}     # Require absolute paths
    worktree_file_copy_handler: {enabled: true, priority: 15}  # Prevent worktree file copies
    git_stash_handler: {enabled: true, priority: 20}         # Warn about git stash

    # CODE QUALITY HANDLERS (Priority 25-35)
    eslint_disable_handler: {enabled: true, priority: 25}    # Block ESLint suppressions
    python_qa_suppression_blocker: {enabled: true, priority: 26}  # Block Python QA suppressions
    php_qa_suppression_blocker: {enabled: true, priority: 27}     # Block PHP QA suppressions
    go_qa_suppression_blocker: {enabled: true, priority: 28}      # Block Go QA suppressions
    tdd_enforcement_handler: {enabled: true, priority: 35}   # Enforce test-first development

    # WORKFLOW HANDLERS (Priority 40-55)
    gh_issue_comments_handler: {enabled: true, priority: 40}  # Require --comments on gh issue view
    web_search_year_handler: {enabled: true, priority: 55}   # Fix outdated years in searches

    # ADVISORY HANDLERS (Priority 56-60)
    british_english_handler: {enabled: true, priority: 60}   # Warn about American English

  # PostToolUse - After tool execution
  post_tool_use:
    bash_error_detector_handler: {enabled: true, priority: 10}  # Detect bash errors

  # PermissionRequest - Auto-approve decisions
  permission_request: {}

  # Notification - Custom notification handling
  notification:
    notification_logger_handler: {enabled: true, priority: 10}  # Log notifications

  # UserPromptSubmit - Context injection before processing
  user_prompt_submit: {}

  # SessionStart - Initialize environment
  session_start: {}

  # SessionEnd - Cleanup on exit
  session_end:
    cleanup_handler: {enabled: true, priority: 10}  # Session cleanup

  # Stop - Control agent continuation
  stop: {}

  # SubagentStop - Control subagent continuation
  subagent_stop:
    subagent_completion_logger_handler: {enabled: true, priority: 10}  # Log subagent completion

  # PreCompact - Before conversation compaction
  pre_compact:
    transcript_archiver_handler: {enabled: true, priority: 10}  # Archive transcripts

# Custom project-specific handlers
plugins: []
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
