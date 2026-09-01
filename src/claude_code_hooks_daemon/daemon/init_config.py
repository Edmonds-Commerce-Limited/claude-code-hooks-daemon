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
            "  log_level: INFO            # DEBUG, INFO, WARNING, ERROR\n" + enforcement_line + "\n"
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
            "  log_level: INFO            # DEBUG, INFO, WARNING, ERROR\n" + enforcement_line + "\n"
            "# Handler Configuration\n"
            "# Enable/disable handlers per event type\n"
            "# Priority: lower numbers run first (5-60 range)\n"
            "\n"
            "handlers:\n"
            "  # PreToolUse - Before tool execution\n"
            "  pre_tool_use:\n"
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
            "    security_antipattern: {enabled: true, priority: 15}  # Block hardcoded secrets and injection patterns\n"
            # Inert until configured: public_patterns defaults to empty and the
            # secret word list defaults to a gitignored path that does not exist
            # in a fresh project. Registered enabled anyway so that adding terms
            # is a one-line config edit rather than also discovering the handler
            # exists -- a guard nobody knows about protects nobody.
            "    sensitive_content: {enabled: true, priority: 14}  # Block configured public patterns + gitignored secret word list\n"
            # On by default (Plan 00259): publishing mints a claude.ai URL for a
            # locally-rendered page, and that is the one disclosure path with no
            # guard. Read-only `action: "list"` stays allowed. Only a human may
            # lift this -- the handler deliberately has no agent-side hatch.
            "    artifact_publish_blocker: {enabled: true, priority: 14}  # Block publishing artefacts outside the project\n"
            # Plan 00272: protected files (vault passwords, *.secret*, SSH keys)
            # must never have their CONTENTS read into context by any route.
            # Presence/metadata stay available via `hooks-daemon secret-meta`.
            # No agent escape hatch — a human edits this block to lift it.
            "    secret_file_guard: {enabled: true, priority: 14}  # Deny reads of protected secret files (contents never enter context)\n"
            # Opt-in (Plan 00278 Phase 3d.1): closes the git/grep channel that
            # flaggable_work_advisor can only advise about. Inert until
            # flaggable_path_globs is configured.
            "    flaggable_content_channel_guard: {enabled: false, priority: 14}  "
            "# Deny content-revealing git/grep over configured flaggable paths (opt-in)\n"
            # Opt-in (Plan 00278 Phase 3d.2): pre-seeded with the DETAIL
            # marker glob, so enabling it needs no further configuration.
            "    quarantine_artefact_read_guard: {enabled: false, priority: 14}  "
            "# Deny reading a *-opus-security-DETAIL* artefact from the main context (opt-in)\n"
            # On by default (Plan 00261): Write replaces a file wholesale, and the
            # harness does not enforce its own documented read-before-overwrite
            # contract under bypassPermissions. New files are never blocked.
            "    write_clobber_guard: {enabled: true, priority: 16}  # Block Write to an existing file not read this session\n"
            "    root_recursion_guard: {enabled: true, priority: 16}  # Block recursive scans (grep -r, find, rg) rooted at / /proc /sys ~ $HOME\n"
            "    pipe_blocker: {enabled: true, priority: 15}      # Block dangerous pipe patterns\n"
            "    worktree_file_copy: {enabled: true, priority: 15}  # Prevent worktree file copies\n"
            "    dangerous_permissions: {enabled: true, priority: 15}  # Block chmod 777, chown root\n"
            "    git_stash: {enabled: true, priority: 20}         # Warn about git stash\n"
            # On by default (Plan 00275): "Fixes #123" auto-closes the issue on
            # the default branch, cannot be disabled repo-side, and is written
            # accidentally. No agent-side hatch: a project that wants
            # auto-close disables the handler instead.
            "    github_auto_close_keywords: {enabled: true, priority: 18}  "
            "# Block GitHub auto-closing keyword refs (Fixes #N) in git messages\n"
            "    git_message_backtick: {enabled: true, priority: 20}  "
            "# Block backticks in a double-quoted git -m (bash executes them)\n"
            "    ancestry_preserving_merge: {enabled: true, priority: 19}  "
            "# Block squash/rebase merges that sever ancestry\n"
            "\n"
            "    # CODE QUALITY HANDLERS (Priority 25-35)\n"
            "    qa_suppression: {enabled: true, priority: 30}  # Unified multi-language QA suppression blocker (11 languages)\n"
            "    comment_changelog: {enabled: true, priority: 31}  # Block changelog narrative in code comments (12 languages)\n"
            "    comment_size: {enabled: true, priority: 33}  # Cap comment length; only growing an over-limit comment is blocked\n"
            "    verification_result_gate: {enabled: true, priority: 34}  # Advise when a verifier's result is never consumed before a mutator\n"
            "    bash_safe_mode: {enabled: false, priority: 36}  # Opt-in: require a set safety prelude on sequenced Bash (warn-first)\n"
            "    plan_number_helper: {enabled: true, priority: 30}  # Provide correct next plan number\n"
            "    markdown_organization:  # Plan tracking and markdown organization\n"
            "      enabled: true\n"
            "      priority: 35\n"
            "      # Docs: docs/guides/handlers/markdown_organization.md\n"
            "      options:\n"
            '        track_plans_in_project: "CLAUDE/Plan"           # Path to plan folder\n'
            '        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"    # Path to workflow doc\n'
            "        # extra_allowed_markdown_paths: ADDS locations on top of built-ins (preferred).\n"
            '        #   - "^\\\\.github/.*\\\\.md$"\n'
            "        # allowed_markdown_paths: OVERRIDES built-in path rules (legacy). See HANDLER_REFERENCE.md.\n"
            '        #   - "^CLAUDE/.*\\\\.md$"\n'
            '        #   - "^docs/.*\\\\.md$"\n'
            "\n"
            "    lsp_enforcement: {enabled: false, priority: 38}  # Steer toward LSP tools instead of Grep\n"
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
            "    gh_pr_comments: {enabled: true, priority: 40}    # Require --comments on gh pr view\n"
            "    plan_time_estimates: {enabled: true, priority: 40}  # Block time estimates in plans\n"
            "    staged_lint_gate: {enabled: true, priority: 43}  # Cheap syntax-check backstop over staged files on git commit (warn-first)\n"
            "    plan_qa_edit: {enabled: true, priority: 44}      # Plan QA lint on PLAN.md writes\n"
            "    plan_qa_commit_gate: {enabled: true, priority: 44}  # Cross-file plan checks on git commit (warn-first)\n"
            "    global_npm_advisor: {enabled: true, priority: 40}  # Advise on npm install -g (non-blocking)\n"
            "    plan_workflow: {enabled: true, priority: 45}     # Guidance when creating plans\n"
            "    agent_isolation_advisor: {enabled: true, priority: 46}  # Advise worktree isolation for concurrent agents (non-blocking)\n"
            "    docs_qa_edit: {enabled: true, priority: 47}      # Docs QA lint on documentation writes (fires only when documentation.enabled)\n"
            "    docs_qa_commit_gate: {enabled: true, priority: 47}  # STAGED docs QA gate on git commit (fires only when documentation.enabled; warn-first)\n"
            "    npm_command: {enabled: true, priority: 50}       # Restrict npm commands to approved list\n"
            "    validate_instruction_content: {enabled: true, priority: 50}  # Block ephemeral content in CLAUDE.md/README.md\n"
            "    web_search_year: {enabled: true, priority: 55}   # Fix outdated years in searches\n"
            "\n"
            "    # ADVISORY HANDLERS (Priority 56-60)\n"
            "    daemon_docs_guard: {enabled: true, priority: 57}  # Warn when reading from daemon internal CLAUDE/ docs\n"
            "    flaggable_work_advisor: {enabled: false, priority: 58}  # Delegate-first advisory for safeguard-flaggable work (opt-in; Plan 00278)\n"
            "    british_english: {enabled: true, priority: 60}   # Warn about American English\n"
            "\n"
            "  # PostToolUse - After tool execution\n"
            "  post_tool_use:\n"
            "    git_hooks_executable_fixer: {enabled: true, priority: 27}  # Auto-fix non-executable git hooks\n"
            "    lint_on_edit: {enabled: true, priority: 25}  # Language-aware lint validation after Write/Edit\n"
            "    markdown_table_formatter: {enabled: true, priority: 26}  # Auto-format markdown tables via mdformat\n"
            "    validate_eslint_on_write: {enabled: true, priority: 10}  # Run ESLint after file writes\n"
            "    background_process_tracker: {enabled: true, priority: 28}  # Track backgrounded processes; advise harvest-background (never kills)\n"
            "    command_hints: {enabled: true, priority: 29}  # Config-driven advisory reminder after a configured command\n"
            "    recovery_cron_advisor: {enabled: true, priority: 30}    # Advise on failsafe recovery cron lifecycle (opt-out)\n"
            "    goal_injection: {enabled: false, priority: 31}  # Write <session>.goal-intent for the ccy supervisor on plan flip to In Progress (opt-in)\n"
            "\n"
            "  # PermissionRequest - Auto-approve decisions\n"
            "  permission_request:\n"
            "    auto_approve_reads: {enabled: true, priority: 10}  # Auto-approve read-only operations\n"
            "\n"
            "  # Notification - no handlers ship today (notification_logger removed in Plan 00237)\n"
            "  notification: {}\n"
            "\n"
            "  # UserPromptSubmit - Context injection before processing\n"
            "  user_prompt_submit:\n"
            "    git_context_injector: {enabled: true, priority: 20}  # Inject git context into prompts\n"
            "    failsafe_cron_blockage_suppressor: {enabled: true, priority: 37}  # Suppress a delivered failsafe-cron tick while the session is blocked only on human input\n"
            "    idle_housekeeping_advisory: {enabled: false, priority: 56}  # Report-first idle housekeeping (beta, opt-in)\n"
            "\n"
            "  # SessionStart - Initialize environment\n"
            "  session_start:\n"
            "    disclosure_reset_session_start: {enabled: true, priority: 15}  # Reset per-agent rule-disclosure state on every SessionStart\n"
            "    project_handler_load_checker: {enabled: true, priority: 50}  # Loud alert when project handlers fail to load\n"
            "    hook_registration_checker: {enabled: true, priority: 51}  # Validate hook registrations in settings.json\n"
            "    optimal_config_checker: {enabled: true, priority: 52}  # Check Claude Code env for optimal settings\n"
            "    git_filemode_checker: {enabled: true, priority: 53}  # Warn when git core.fileMode=false\n"
            "    gitignore_safety_checker: {enabled: true, priority: 54}  # Warn when required .claude/ paths are not gitignored\n"
            "    git_upstream_checker: {enabled: true, priority: 56, options: {mode: warn, auto_fetch: true}}  # Full fetch + advise pull when behind upstream\n"
            "    suggest_status_line: {enabled: true, priority: 55}  # Suggest status line setup\n"
            "    version_check: {enabled: true, priority: 55}  # Check for daemon updates on new sessions\n"
            "    plan_qa_sweep: {enabled: true, priority: 57}  # Plan-tree drift report (silent when clean)\n"
            "    ccy_supervisor_integrity: {enabled: true, priority: 58}  # Warn when the ccy supervisor is armed but its files are unsafe\n"
            "    plan_workflow_asset_checker: {enabled: true, priority: 59}  # Advise when plan_workflow is enabled but its assets are missing\n"
            "    contract_staleness: {enabled: true, priority: 60}  # Advise a hooks-contract refresh when Claude Code outruns the vendored audit\n"
            "    skill_opportunity_detector: {enabled: false, priority: 61}  # TTL-gated advisory to run `skill-scan` (opt-in; reads transcripts)\n"
            "    secret_file_hygiene_checker: {enabled: true, priority: 62}  # On-disk hygiene (gitignore/tracked/permissions) for protected paths\n"
            "    model_fallback_detector: {enabled: false, priority: 63}  # Opt-in (Plan 00278): loud SessionStart alert on a recorded model fallback. Probably leave OFF — it reports a fallback that already happened and is noisy; the downgrade_indicator status line shows a LIVE downgrade instead. Enable only to capture diagnostic snapshots for tuning delegation config.\n"
            "    docs_qa_sweep: {enabled: true, priority: 64}  # Whole-corpus docs drift report (fires only when documentation.enabled); silent when clean\n"
            "    tool_disable_advisor: {enabled: false, priority: 65}  # Opt-in (Plan 00293): advise when a tool_policy.never_want tool is not disabled in project settings (never edits)\n"
            "    monorepo_detector: {enabled: true, priority: 66}  # Advise on an unconfigured monorepo shape (manifests found below the repo root, none at it)\n"
            "\n"
            "  # SessionEnd - no handlers ship today (cleanup removed in Plan 00237)\n"
            "  session_end: {}\n"
            "\n"
            "  # Stop - Control agent continuation. auto_continue_stop is terminal and\n"
            "  # matches nearly every stop, so anything registered above it never runs\n"
            "  # (Plan 00237) — put message-auditing handlers on nitpick instead.\n"
            "  stop:\n"
            "    auto_continue_stop: {enabled: true, priority: 15}  # Auto-continue after stop events\n"
            "\n"
            "  # SubagentStop - no handlers ship today (removed in Plan 00237)\n"
            "  subagent_stop: {}\n"
            "\n"
            "  # PreCompact - Before conversation compaction\n"
            "  pre_compact:\n"
            "    disclosure_reset_pre_compact: {enabled: true, priority: 15}  # Reset per-agent rule-disclosure state before compaction\n"
            "    compaction_signal: {enabled: false, priority: 20}  # Drop compaction signal for PTY supervisor (opt-in)\n"
            "\n"
            "  # Status - Status line generation\n"
            "  status_line:\n"
            "    git_repo_name: {enabled: true, priority: 5}      # Git repository name\n"
            "    account_display: {enabled: true, priority: 6}    # Account information\n"
            "    model_context: {enabled: true, priority: 10}    # Model name and context %\n"
            "    downgrade_indicator: {enabled: true, priority: 11}  # Warn on a silent model-family downgrade\n"
            "    context_sidecar: {enabled: false, priority: 12}  # Observe-only context sidecar for PTY supervisor (opt-in)\n"
            "    git_branch: {enabled: true, priority: 20}       # Current git branch\n"
            "    startup_cleanup: {enabled: true, priority: 28}  # Stale file cleanup indicator\n"
            "    daemon_stats: {enabled: false, priority: 30}    # Daemon health metrics (opt-in; dev diagnostics)\n"
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
