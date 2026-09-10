Config Migration Advisory: v2.2.0 → v2.15.2

💡 New Options Available (since v2.2.0 → v2.15.2)

  v2.5.0: handlers.pre_tool_use.plan_completion_advisor
    Reminds to move completed plans to the Completed/ archive folder.
    Example: plan_completion_advisor:
      enabled: true
      priority: 48
  v2.5.0: handlers.pre_tool_use.task_tdd_advisor
    Advisory: reminds to follow TDD workflow when creating tasks.
    Example: task_tdd_advisor:
      enabled: true
      priority: 36
  v2.8.0: handlers.stop.hedging_language_detector
    Advisory: detects uncertain language patterns (maybe, possibly, I think) in stop events.
    Example: hedging_language_detector:
      enabled: true
      priority: 30
  v2.9.0: daemon.project_languages
    Optional list of active project languages used to filter strategy-based handlers.
    Example: daemon:
      project_languages:
        - Python
        - JavaScript/TypeScript
  v2.11.0: handlers.pre_tool_use.markdown_organization.options.monorepo_subproject_patterns
    Regex patterns matching monorepo sub-project directories to allow markdown files within them.
    Example: markdown_organization:
      enabled: true
      options:
        monorepo_subproject_patterns:
          - "packages/[^/]+"
  v2.11.0: handlers.pre_tool_use.markdown_organization.options.allowed_markdown_paths
    Custom regex patterns that override all built-in markdown path rules.
    Example: markdown_organization:
      enabled: true
      options:
        allowed_markdown_paths:
          - "^CLAUDE/.*\\.md$"
          - "^docs/.*\\.md$"
  v2.11.0: handlers.pre_tool_use.tdd_enforcement.options.languages
    Optional list to restrict TDD enforcement to specific programming languages.
    Example: tdd_enforcement:
      enabled: true
      options:
        languages:
          - Python
          - Go
  v2.12.0: handlers.session_start.working_directory
    Displays current working directory in orange at session start when it differs from the project root.
    Example: working_directory:
      enabled: true
      priority: 25
  v2.12.0: handlers.session_start.current_time
    Shows current timestamp at session start for context freshness tracking.
    Example: current_time:
      enabled: true
      priority: 59
  v2.13.0: daemon.enforce_single_daemon_process
    Prevents multiple daemon instances running simultaneously; in containers kills all others, outside containers only cleans up stale PID files.
    Example: daemon:
      enforce_single_daemon_process: true  # Auto-enabled in container environments

See docs/guides/HANDLER_REFERENCE.md for full option details.
