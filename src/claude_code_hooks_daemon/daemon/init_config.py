"""Configuration initialization module.

Provides template generation for hooks-daemon.yaml configuration files.
Supports minimal and full configuration modes with helpful comments.
"""

from typing import Literal

from claude_code_hooks_daemon.utils.container_detection import is_container_environment


def _get_enforcement_line() -> str:
    """Generate enforcement config line based on container detection.

    Returns:
        Configuration line for enforce_single_daemon_process setting.
        Auto-enabled if container detected, commented out otherwise.
    """
    in_container = is_container_environment()
    if in_container:
        return "  enforce_single_daemon_process: true   # Auto-enabled (container detected)\n"
    else:
        return "  # enforce_single_daemon_process: false  # Enable to prevent multiple daemon instances (auto-enabled in containers)\n"


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
        enforcement_line = _get_enforcement_line()
        return (
            'version: "1.0"\n'
            "\n"
            "# Daemon Settings\n"
            "daemon:\n"
            "  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes\n"
            "  log_level: INFO            # DEBUG, INFO, WARNING, ERROR\n"
            "  enable_hello_world_handlers: false  # Set true to confirm hooks working\n"
            + enforcement_line
            + "\n"
            "# Handler Configuration\n"
            "# Enable/disable handlers per event type\n"
            "# Priority: lower numbers run first (5-60 range)\n"
            "\n"
            "handlers:\n"
            "  # PreToolUse - Before tool execution\n"
            "  pre_tool_use: {}\n"
            "\n"
            "  # PostToolUse - After tool execution\n"
            "  post_tool_use: {}\n"
            "\n"
            "  # PermissionRequest - Auto-approve decisions\n"
            "  permission_request: {}\n"
            "\n"
            "  # Notification - Custom notification handling\n"
            "  notification: {}\n"
            "\n"
            "  # UserPromptSubmit - Context injection before processing\n"
            "  user_prompt_submit: {}\n"
            "\n"
            "  # SessionStart - Initialize environment\n"
            "  session_start: {}\n"
            "\n"
            "  # SessionEnd - Cleanup on exit\n"
            "  session_end: {}\n"
            "\n"
            "  # Stop - Control agent continuation\n"
            "  stop: {}\n"
            "\n"
            "  # SubagentStop - Control subagent continuation\n"
            "  subagent_stop: {}\n"
            "\n"
            "  # PreCompact - Before conversation compaction\n"
            "  pre_compact: {}\n"
            "\n"
            "  # Status - Status line generation\n"
            "  status_line: {}\n"
            "\n"
            "# Custom project-specific handlers\n"
            "plugins:\n"
            "  paths: []\n"
            "  plugins: []\n"
        )

    @staticmethod
    def generate_full() -> str:
        """Generate full configuration template with examples.

        Returns:
            YAML configuration string with all hook events and example handlers
        """
        enforcement_line = _get_enforcement_line()
        return (
            'version: "1.0"\n'
            "\n"
            "# Daemon Settings\n"
            "daemon:\n"
            "  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes\n"
            "  log_level: INFO            # DEBUG, INFO, WARNING, ERROR\n"
            "  enable_hello_world_handlers: false  # Set true to confirm hooks working\n"
            + enforcement_line
            + "\n"
            "# Handler Configuration\n"
            "# Enable/disable handlers per event type\n"
            "# Priority: lower numbers run first (5-60 range)\n"
            "\n"
            "handlers:\n"
            "  # PreToolUse - Before tool execution\n"
            "  pre_tool_use:\n"
            "    # ORCHESTRATOR MODE (Priority 8 - opt-in, disabled by default)\n"
            "    orchestrator_only: {enabled: false, priority: 8}  # Block work tools, force Task delegation\n"
            "\n"
            "    # SAFETY HANDLERS (Priority 10-20)\n"
            "    daemon_restart_verifier: {enabled: true, priority: 10}  # Suggest daemon restart verification (advisory)\n"
            "    destructive_git: {enabled: true, priority: 10}   # Block git reset --hard, clean -f\n"
            "    daemon_location_guard: {enabled: true, priority: 11}  # Prevent cd into .claude/hooks-daemon\n"
            "    sed_blocker: {enabled: true, priority: 10}       # Block sed (use Edit tool instead)\n"
            "    pip_break_system: {enabled: true, priority: 10}  # Block pip --break-system-packages\n"
            "    sudo_pip: {enabled: true, priority: 10}          # Block sudo pip\n"
            "    curl_pipe_shell: {enabled: true, priority: 10}   # Block curl | bash patterns\n"
            "    lock_file_edit_blocker: {enabled: true, priority: 10}  # Block direct editing of package manager lock files\n"
            "    absolute_path: {enabled: true, priority: 12}     # Require absolute paths\n"
            "    error_hiding_blocker: {enabled: true, priority: 13}  # Block error-hiding patterns (|| true, except: pass, catch(e){})\n"
            "    pipe_blocker: {enabled: true, priority: 15}      # Block dangerous pipe patterns\n"
            "    worktree_file_copy: {enabled: true, priority: 15}  # Prevent worktree file copies\n"
            "    dangerous_permissions: {enabled: true, priority: 15}  # Block chmod 777, chown root\n"
            "    git_stash: {enabled: true, priority: 20}         # Warn about git stash\n"
            "\n"
            "    # CODE QUALITY HANDLERS (Priority 25-35)\n"
            "    qa_suppression: {enabled: true, priority: 30}  # Unified multi-language QA suppression blocker (11 languages)\n"
            "    validate_plan_number: {enabled: true, priority: 30}  # Validate plan number format\n"
            "    plan_number_helper: {enabled: true, priority: 30}  # Provide correct next plan number\n"
            "    markdown_organization:  # Plan tracking and markdown organization\n"
            "      enabled: true\n"
            "      priority: 35\n"
            "      # Docs: docs/guides/handlers/markdown_organization.md\n"
            "      options:\n"
            '        track_plans_in_project: "CLAUDE/Plan"           # Path to plan folder\n'
            '        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"    # Path to workflow doc\n'
            "        # allowed_markdown_paths: OVERRIDES built-in path rules. See HANDLER_REFERENCE.md.\n"
            '        #   - "^CLAUDE/.*\\\\.md$"\n'
            '        #   - "^docs/.*\\\\.md$"\n'
            '        #   - "^untracked/.*\\\\.md$"\n'
            '        #   - "^RELEASES/.*\\\\.md$"\n'
            "\n"
            "    # WORKFLOW HANDLERS (Priority 36-55)\n"
            "    tdd_enforcement:  # Enforce test-first development\n"
            "      enabled: true\n"
            "      priority: 15\n"
            "      # options:\n"
            "      #   # Restrict TDD enforcement to specific languages (default: ALL languages)\n"
            "      #   # Uncomment and list only the languages you want enforced.\n"
            "      #   # If omitted or empty, ALL 11 languages are enforced.\n"
            "      #   languages:\n"
            "      #     - Python\n"
            "      #     - Go\n"
            "      #     - JavaScript/TypeScript\n"
            "      #     - PHP\n"
            "      #     - Rust\n"
            "      #     - Java\n"
            "      #     - C#\n"
            "      #     - Kotlin\n"
            "      #     - Ruby\n"
            "      #     - Swift\n"
            "      #     - Dart\n"
            "    gh_issue_comments: {enabled: true, priority: 40}  # Require --comments on gh issue view\n"
            "    plan_time_estimates: {enabled: true, priority: 40}  # Block time estimates in plans\n"
            "    global_npm_advisor: {enabled: true, priority: 40}  # Advise on npm install -g (non-blocking)\n"
            "    plan_workflow: {enabled: true, priority: 45}     # Guidance when creating plans\n"
            "    task_tdd_advisor: {enabled: true, priority: 45}  # Advise on TDD workflow for Task agents (non-blocking)\n"
            "    npm_command: {enabled: true, priority: 50}       # Restrict npm commands to approved list\n"
            "    plan_completion_advisor: {enabled: true, priority: 50}  # Advise on plan completion steps\n"
            "    validate_instruction_content: {enabled: true, priority: 50}  # Block ephemeral content in CLAUDE.md/README.md\n"
            "    web_search_year: {enabled: true, priority: 55}   # Fix outdated years in searches\n"
            "\n"
            "    # ADVISORY HANDLERS (Priority 56-60)\n"
            "    british_english: {enabled: true, priority: 60}   # Warn about American English\n"
            "\n"
            "  # PostToolUse - After tool execution\n"
            "  post_tool_use:\n"
            "    bash_error_detector: {enabled: true, priority: 50}  # Detect bash errors\n"
            "    lint_on_edit: {enabled: true, priority: 25}  # Language-aware lint validation after Write/Edit\n"
            "    validate_eslint_on_write: {enabled: true, priority: 10}  # Run ESLint after file writes\n"
            "\n"
            "  # PermissionRequest - Auto-approve decisions\n"
            "  permission_request:\n"
            "    auto_approve_reads: {enabled: true, priority: 10}  # Auto-approve read-only operations\n"
            "\n"
            "  # Notification - Custom notification handling\n"
            "  notification:\n"
            "    notification_logger: {enabled: true, priority: 10}  # Log notifications\n"
            "\n"
            "  # UserPromptSubmit - Context injection before processing\n"
            "  user_prompt_submit:\n"
            "    git_context_injector: {enabled: true, priority: 20}  # Inject git context into prompts\n"
            "\n"
            "  # SessionStart - Initialize environment\n"
            "  session_start:\n"
            "    workflow_state_restoration: {enabled: true, priority: 50}  # Restore workflow state after compaction\n"
            "    yolo_container_detection: {enabled: true, priority: 40}  # Detect YOLO container environments\n"
            "    optimal_config_checker: {enabled: true, priority: 52}  # Check Claude Code env for optimal settings\n"
            "    suggest_status_line: {enabled: true, priority: 55}  # Suggest status line setup\n"
            "    version_check: {enabled: true, priority: 55}  # Check for daemon updates on new sessions\n"
            "\n"
            "  # SessionEnd - Cleanup on exit\n"
            "  session_end:\n"
            "    cleanup: {enabled: true, priority: 10}  # Session cleanup\n"
            "\n"
            "  # Stop - Control agent continuation\n"
            "  stop:\n"
            "    auto_continue_stop: {enabled: true, priority: 15}  # Auto-continue after stop events\n"
            "    hedging_language_detector: {enabled: true, priority: 30}  # Detect guessing language in output\n"
            "    task_completion_checker: {enabled: true, priority: 50}  # Check for task completion\n"
            "\n"
            "  # SubagentStop - Control subagent continuation\n"
            "  subagent_stop:\n"
            "    subagent_completion_logger: {enabled: true, priority: 10}  # Log subagent completion\n"
            "    remind_prompt_library: {enabled: true, priority: 20}  # Remind about prompt library\n"
            "\n"
            "  # PreCompact - Before conversation compaction\n"
            "  pre_compact:\n"
            "    transcript_archiver: {enabled: true, priority: 10}  # Archive transcripts\n"
            "    workflow_state_pre_compact: {enabled: true, priority: 50}  # Save workflow state\n"
            "\n"
            "  # Status - Status line generation\n"
            "  status_line:\n"
            "    git_repo_name: {enabled: true, priority: 5}      # Git repository name\n"
            "    account_display: {enabled: true, priority: 6}    # Account information\n"
            "    model_context: {enabled: true, priority: 10}    # Model name and context %\n"
            "    usage_tracking: {enabled: true, priority: 15}   # Usage statistics\n"
            "    git_branch: {enabled: true, priority: 20}       # Current git branch\n"
            "    thinking_mode: {enabled: true, priority: 25}    # Current thinking mode\n"
            "    daemon_stats: {enabled: true, priority: 30}     # Daemon health metrics\n"
            "\n"
            "# Custom project-specific handlers\n"
            "plugins:\n"
            "  paths: []\n"
            "  plugins: []\n"
        )


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
