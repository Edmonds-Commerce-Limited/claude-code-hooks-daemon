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
    sed_blocker: {enabled: true, priority: 10}       # Block sed (use Edit tool instead)
    pip_break_system: {enabled: true, priority: 10}  # Block pip --break-system-packages
    sudo_pip: {enabled: true, priority: 10}          # Block sudo pip
    curl_pipe_shell: {enabled: true, priority: 10}   # Block curl | bash patterns
    lock_file_edit_blocker: {enabled: true, priority: 10}  # Block direct editing of package manager lock files
    absolute_path: {enabled: true, priority: 12}     # Require absolute paths
    pipe_blocker: {enabled: true, priority: 15}      # Block dangerous pipe patterns
    worktree_file_copy: {enabled: true, priority: 15}  # Prevent worktree file copies
    dangerous_permissions: {enabled: true, priority: 15}  # Block chmod 777, chown root
    git_stash: {enabled: true, priority: 20}         # Warn about git stash

    # CODE QUALITY HANDLERS (Priority 25-35)
    qa_suppression: {enabled: true, priority: 30}  # Unified multi-language QA suppression blocker (11 languages)
    validate_plan_number: {enabled: true, priority: 30}  # Validate plan number format
    plan_number_helper: {enabled: true, priority: 30}  # Provide correct next plan number
    markdown_organization:  # Plan tracking and markdown organization
      enabled: true
      priority: 35
      # Full docs: docs/guides/HANDLER_REFERENCE.md -> markdown_organization
      options:
        track_plans_in_project: "CLAUDE/Plan"           # Path to plan folder
        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"    # Path to workflow doc
        # allowed_markdown_paths: OVERRIDES built-in path rules. See HANDLER_REFERENCE.md.
        #   - "^CLAUDE/.*\\.md$"
        #   - "^docs/.*\\.md$"
        #   - "^untracked/.*\\.md$"
        #   - "^RELEASES/.*\\.md$"

    # WORKFLOW HANDLERS (Priority 36-55)
    tdd_enforcement:  # Enforce test-first development
      enabled: true
      priority: 15
      # options:
      #   # Restrict TDD enforcement to specific languages (default: ALL languages)
      #   # Uncomment and list only the languages you want enforced.
      #   # If omitted or empty, ALL 11 languages are enforced.
      #   languages:
      #     - Python
      #     - Go
      #     - JavaScript/TypeScript
      #     - PHP
      #     - Rust
      #     - Java
      #     - C#
      #     - Kotlin
      #     - Ruby
      #     - Swift
      #     - Dart
    gh_issue_comments: {enabled: true, priority: 40}  # Require --comments on gh issue view
    plan_time_estimates: {enabled: true, priority: 40}  # Block time estimates in plans
    global_npm_advisor: {enabled: true, priority: 40}  # Advise on npm install -g (non-blocking)
    plan_workflow: {enabled: true, priority: 45}     # Guidance when creating plans
    task_tdd_advisor: {enabled: true, priority: 45}  # Advise on TDD workflow for Task agents (non-blocking)
    npm_command: {enabled: true, priority: 50}       # Restrict npm commands to approved list
    plan_completion_advisor: {enabled: true, priority: 50}  # Advise on plan completion steps
    validate_instruction_content: {enabled: true, priority: 50}  # Block ephemeral content in CLAUDE.md/README.md
    web_search_year: {enabled: true, priority: 55}   # Fix outdated years in searches

    # ADVISORY HANDLERS (Priority 56-60)
    british_english: {enabled: true, priority: 60}   # Warn about American English

  # PostToolUse - After tool execution
  post_tool_use:
    bash_error_detector: {enabled: true, priority: 50}  # Detect bash errors
    validate_eslint_on_write: {enabled: true, priority: 10}  # Run ESLint after file writes

  # PermissionRequest - Auto-approve decisions
  permission_request:
    auto_approve_reads: {enabled: true, priority: 10}  # Auto-approve read-only operations

  # Notification - Custom notification handling
  notification:
    notification_logger: {enabled: true, priority: 10}  # Log notifications

  # UserPromptSubmit - Context injection before processing
  user_prompt_submit:
    git_context_injector: {enabled: true, priority: 20}  # Inject git context into prompts

  # SessionStart - Initialize environment
  session_start:
    workflow_state_restoration: {enabled: true, priority: 50}  # Restore workflow state after compaction
    yolo_container_detection: {enabled: true, priority: 40}  # Detect YOLO container environments
    optimal_config_checker: {enabled: true, priority: 52}  # Check Claude Code env for optimal settings
    suggest_status_line: {enabled: true, priority: 55}  # Suggest status line setup
    version_check: {enabled: true, priority: 55}  # Check for daemon updates on new sessions

  # SessionEnd - Cleanup on exit
  session_end:
    cleanup: {enabled: true, priority: 10}  # Session cleanup

  # Stop - Control agent continuation
  stop:
    auto_continue_stop: {enabled: true, priority: 15}  # Auto-continue after stop events
    hedging_language_detector: {enabled: true, priority: 30}  # Detect guessing language in output
    task_completion_checker: {enabled: true, priority: 50}  # Check for task completion

  # SubagentStop - Control subagent continuation
  subagent_stop:
    subagent_completion_logger: {enabled: true, priority: 10}  # Log subagent completion
    remind_prompt_library: {enabled: true, priority: 20}  # Remind about prompt library

  # PreCompact - Before conversation compaction
  pre_compact:
    transcript_archiver: {enabled: true, priority: 10}  # Archive transcripts
    workflow_state_pre_compact: {enabled: true, priority: 50}  # Save workflow state

  # Status - Status line generation
  status_line:
    git_repo_name: {enabled: true, priority: 5}      # Git repository name
    account_display: {enabled: true, priority: 6}    # Account information
    model_context: {enabled: true, priority: 10}    # Model name and context %
    usage_tracking: {enabled: true, priority: 15}   # Usage statistics
    git_branch: {enabled: true, priority: 20}       # Current git branch
    thinking_mode: {enabled: true, priority: 25}    # Current thinking mode
    daemon_stats: {enabled: true, priority: 30}     # Daemon health metrics

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
