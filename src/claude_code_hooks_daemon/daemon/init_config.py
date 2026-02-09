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

  # Status - Status line generation
  status_line: {}

# Custom project-specific handlers
plugins:
  paths: []
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
    # ORCHESTRATOR MODE (Priority 8 - opt-in, disabled by default)
    orchestrator_only: {enabled: false, priority: 8}  # Block work tools, force Task delegation

    # SAFETY HANDLERS (Priority 10-20)
    daemon_restart_verifier: {enabled: true, priority: 10}  # Suggest daemon restart verification (advisory)
    destructive_git: {enabled: true, priority: 10}   # Block git reset --hard, clean -f
    sed_blocker: {enabled: true, priority: 11}       # Block sed (use Edit tool instead)
    absolute_path: {enabled: true, priority: 12}     # Require absolute paths
    pip_break_system: {enabled: true, priority: 13}  # Block pip --break-system-packages
    sudo_pip: {enabled: true, priority: 14}          # Block sudo pip
    curl_pipe_shell: {enabled: true, priority: 15}   # Block curl | bash patterns
    lock_file_edit_blocker: {enabled: true, priority: 10}  # Block direct editing of package manager lock files
    worktree_file_copy: {enabled: true, priority: 16}  # Prevent worktree file copies
    dangerous_permissions: {enabled: true, priority: 17}  # Block chmod 777, chown root
    git_stash: {enabled: true, priority: 20}         # Warn about git stash

    # CODE QUALITY HANDLERS (Priority 25-35)
    eslint_disable: {enabled: true, priority: 25}    # Block ESLint suppressions
    python_qa_suppression_blocker: {enabled: true, priority: 26}  # Block Python QA suppressions
    php_qa_suppression_blocker: {enabled: true, priority: 27}     # Block PHP QA suppressions
    go_qa_suppression_blocker: {enabled: true, priority: 28}      # Block Go QA suppressions
    tdd_enforcement: {enabled: true, priority: 35}   # Enforce test-first development

    # WORKFLOW HANDLERS (Priority 36-55)
    # Plan workflow handlers (parent-child relationship)
    markdown_organization:  # Parent handler - defines plan tracking options
      enabled: true
      priority: 42
      options:
        track_plans_in_project: "CLAUDE/Plan"           # Path to plan folder
        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"    # Path to workflow doc
    plan_number_helper:     # Child handler - inherits options from markdown_organization
      enabled: true
      priority: 30
      # options: {}  # Inherits from markdown_organization (no duplication needed)

    gh_issue_comments: {enabled: true, priority: 40}  # Require --comments on gh issue view
    global_npm_advisor: {enabled: true, priority: 41}  # Advise on npm install -g (non-blocking)
    task_tdd_advisor: {enabled: true, priority: 45}  # Advise on TDD workflow for Task agents (non-blocking)
    plan_completion_advisor: {enabled: true, priority: 50}  # Advise on plan completion steps (git mv, README update)
    web_search_year: {enabled: true, priority: 55}   # Fix outdated years in searches

    # ADVISORY HANDLERS (Priority 56-60)
    british_english: {enabled: true, priority: 60}   # Warn about American English

  # PostToolUse - After tool execution
  post_tool_use:
    bash_error_detector: {enabled: true, priority: 10}  # Detect bash errors

  # PermissionRequest - Auto-approve decisions
  permission_request: {}

  # Notification - Custom notification handling
  notification:
    notification_logger: {enabled: true, priority: 10}  # Log notifications

  # UserPromptSubmit - Context injection before processing
  user_prompt_submit: {}

  # SessionStart - Initialize environment
  session_start:
    workflow_state_restoration: {enabled: true, priority: 10}  # Restore workflow state after compaction
    yolo_container_detection: {enabled: true, priority: 40}  # Detect YOLO container environments
    suggest_status_line: {enabled: true, priority: 55}  # Suggest status line setup

  # SessionEnd - Cleanup on exit
  session_end:
    cleanup: {enabled: true, priority: 10}  # Session cleanup

  # Stop - Control agent continuation
  stop: {}

  # SubagentStop - Control subagent continuation
  subagent_stop:
    subagent_completion_logger: {enabled: true, priority: 10}  # Log subagent completion

  # PreCompact - Before conversation compaction
  pre_compact:
    transcript_archiver: {enabled: true, priority: 10}  # Archive transcripts

  # Status - Status line generation
  status_line:
    model_context: {enabled: true, priority: 10}  # Model name and context %
    git_branch: {enabled: true, priority: 20}     # Current git branch
    daemon_stats: {enabled: true, priority: 30}   # Daemon health metrics

# Custom project-specific handlers
plugins:
  paths: []
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
