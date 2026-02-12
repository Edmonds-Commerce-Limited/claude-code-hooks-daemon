"""Handler identifier constants - Single source of truth for all handler names.

This module defines the canonical identifiers for all handlers in the system.
Each handler has three name formats:
- class_name: PascalCase with "Handler" suffix (Python class name)
- config_key: snake_case without suffix (YAML config key)
- display_name: kebab-case, descriptive (user-facing name)

Usage:
    from claude_code_hooks_daemon.constants import HandlerID

    class DestructiveGitHandler(Handler):
        def __init__(self) -> None:
            super().__init__(
                handler_id=HandlerID.DESTRUCTIVE_GIT,
                priority=Priority.DESTRUCTIVE_GIT,
            )
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HandlerIDMeta:
    """Metadata for a handler identifier.

    Attributes:
        class_name: Python class name (PascalCase with Handler suffix)
        config_key: YAML config key (snake_case, no suffix)
        display_name: User-facing name (kebab-case, descriptive)
    """

    class_name: str
    config_key: str
    display_name: str


class HandlerID:
    """Single source of truth for all handler identifiers.

    Each constant provides all three naming formats for a handler.
    Use these instead of hardcoding handler names anywhere in the codebase.
    """

    # Orchestrator-only mode (Priority: 8)
    ORCHESTRATOR_ONLY = HandlerIDMeta(
        class_name="OrchestratorOnlyHandler",
        config_key="orchestrator_only",
        display_name="orchestrator-only-mode",
    )

    # Test handlers (Priority: 5)
    TEST_SERVER = HandlerIDMeta(
        class_name="TestServerHandler",
        config_key="test_server",
        display_name="test-server",
    )
    HELLO_WORLD_PRE_TOOL_USE = HandlerIDMeta(
        class_name="HelloWorldPreToolUseHandler",
        config_key="hello_world_pre_tool_use",
        display_name="hello-world",
    )
    HELLO_WORLD_POST_TOOL_USE = HandlerIDMeta(
        class_name="HelloWorldPostToolUseHandler",
        config_key="hello_world_post_tool_use",
        display_name="hello-world",
    )
    HELLO_WORLD_SESSION_START = HandlerIDMeta(
        class_name="HelloWorldSessionStartHandler",
        config_key="hello_world_session_start",
        display_name="hello-world",
    )
    HELLO_WORLD_SESSION_END = HandlerIDMeta(
        class_name="HelloWorldSessionEndHandler",
        config_key="hello_world_session_end",
        display_name="hello-world",
    )
    HELLO_WORLD_STOP = HandlerIDMeta(
        class_name="HelloWorldStopHandler",
        config_key="hello_world_stop",
        display_name="hello-world",
    )
    HELLO_WORLD_SUBAGENT_STOP = HandlerIDMeta(
        class_name="HelloWorldSubagentStopHandler",
        config_key="hello_world_subagent_stop",
        display_name="hello-world",
    )
    HELLO_WORLD_USER_PROMPT_SUBMIT = HandlerIDMeta(
        class_name="HelloWorldUserPromptSubmitHandler",
        config_key="hello_world_user_prompt_submit",
        display_name="hello-world",
    )
    HELLO_WORLD_PRE_COMPACT = HandlerIDMeta(
        class_name="HelloWorldPreCompactHandler",
        config_key="hello_world_pre_compact",
        display_name="hello-world",
    )
    HELLO_WORLD_NOTIFICATION = HandlerIDMeta(
        class_name="HelloWorldNotificationHandler",
        config_key="hello_world_notification",
        display_name="hello-world",
    )
    HELLO_WORLD_PERMISSION_REQUEST = HandlerIDMeta(
        class_name="HelloWorldPermissionRequestHandler",
        config_key="hello_world_permission_request",
        display_name="hello-world",
    )

    # Safety handlers (Priority: 10-20)
    DAEMON_RESTART_VERIFIER = HandlerIDMeta(
        class_name="DaemonRestartVerifierHandler",
        config_key="daemon_restart_verifier",
        display_name="verify-daemon-restart",
    )
    DESTRUCTIVE_GIT = HandlerIDMeta(
        class_name="DestructiveGitHandler",
        config_key="destructive_git",
        display_name="prevent-destructive-git",
    )
    SED_BLOCKER = HandlerIDMeta(
        class_name="SedBlockerHandler",
        config_key="sed_blocker",
        display_name="block-sed-command",
    )
    PIP_BREAK_SYSTEM = HandlerIDMeta(
        class_name="PipBreakSystemHandler",
        config_key="pip_break_system",
        display_name="block-pip-break-system",
    )
    SUDO_PIP = HandlerIDMeta(
        class_name="SudoPipHandler",
        config_key="sudo_pip",
        display_name="block-sudo-pip",
    )
    LOCK_FILE_EDIT_BLOCKER = HandlerIDMeta(
        class_name="LockFileEditBlockerHandler",
        config_key="lock_file_edit_blocker",
        display_name="lock-file-edit-blocker",
    )
    CURL_PIPE_SHELL = HandlerIDMeta(
        class_name="CurlPipeShellHandler",
        config_key="curl_pipe_shell",
        display_name="block-curl-pipe-shell",
    )
    DANGEROUS_PERMISSIONS = HandlerIDMeta(
        class_name="DangerousPermissionsHandler",
        config_key="dangerous_permissions",
        display_name="block-dangerous-permissions",
    )
    AUTO_APPROVE_READS = HandlerIDMeta(
        class_name="AutoApproveReadsHandler",
        config_key="auto_approve_reads",
        display_name="auto-approve-reads",
    )
    VALIDATE_ESLINT_ON_WRITE = HandlerIDMeta(
        class_name="ValidateEslintOnWriteHandler",
        config_key="validate_eslint_on_write",
        display_name="validate-eslint-on-write",
    )
    TRANSCRIPT_ARCHIVER = HandlerIDMeta(
        class_name="TranscriptArchiverHandler",
        config_key="transcript_archiver",
        display_name="transcript-archiver",
    )
    ABSOLUTE_PATH = HandlerIDMeta(
        class_name="AbsolutePathHandler",
        config_key="absolute_path",
        display_name="require-absolute-paths",
    )
    TDD_ENFORCEMENT = HandlerIDMeta(
        class_name="TddEnforcementHandler",
        config_key="tdd_enforcement",
        display_name="enforce-tdd",
    )
    AUTO_CONTINUE_STOP = HandlerIDMeta(
        class_name="AutoContinueStopHandler",
        config_key="auto_continue_stop",
        display_name="auto-continue-stop",
    )
    WORKTREE_FILE_COPY = HandlerIDMeta(
        class_name="WorktreeFileCopyHandler",
        config_key="worktree_file_copy",
        display_name="prevent-worktree-file-copying",
    )
    GIT_CONTEXT_INJECTOR = HandlerIDMeta(
        class_name="GitContextInjectorHandler",
        config_key="git_context_injector",
        display_name="git-context-injector",
    )
    GIT_REPO_NAME = HandlerIDMeta(
        class_name="GitRepoNameHandler",
        config_key="git_repo_name",
        display_name="status-git-repo-name",
    )
    GIT_BRANCH = HandlerIDMeta(
        class_name="GitBranchHandler",
        config_key="git_branch",
        display_name="status-git-branch",
    )
    CURRENT_TIME = HandlerIDMeta(
        class_name="CurrentTimeHandler",
        config_key="current_time",
        display_name="status-current-time",
    )
    PIPE_BLOCKER = HandlerIDMeta(
        class_name="PipeBlockerHandler",
        config_key="pipe_blocker",
        display_name="pipe-blocker",
    )
    GIT_STASH = HandlerIDMeta(
        class_name="GitStashHandler",
        config_key="git_stash",
        display_name="block-git-stash",
    )
    # QA enforcement handlers (Priority: 30-35)
    QA_SUPPRESSION = HandlerIDMeta(
        class_name="QaSuppressionHandler",
        config_key="qa_suppression",
        display_name="qa-suppression-blocker",
    )
    VALIDATE_PLAN_NUMBER = HandlerIDMeta(
        class_name="ValidatePlanNumberHandler",
        config_key="validate_plan_number",
        display_name="validate-plan-number",
    )
    PLAN_NUMBER_HELPER = HandlerIDMeta(
        class_name="PlanNumberHelperHandler",
        config_key="plan_number_helper",
        display_name="plan-number-helper",
    )
    DAEMON_STATS = HandlerIDMeta(
        class_name="DaemonStatsHandler",
        config_key="daemon_stats",
        display_name="status-daemon-stats",
    )
    MARKDOWN_ORGANIZATION = HandlerIDMeta(
        class_name="MarkdownOrganizationHandler",
        config_key="markdown_organization",
        display_name="enforce-markdown-organization",
    )
    VALIDATE_INSTRUCTION_CONTENT = HandlerIDMeta(
        class_name="ValidateInstructionContentHandler",
        config_key="validate_instruction_content",
        display_name="validate-instruction-content",
    )

    # Workflow handlers (Priority: 40-55)
    GH_ISSUE_COMMENTS = HandlerIDMeta(
        class_name="GhIssueCommentsHandler",
        config_key="gh_issue_comments",
        display_name="require-gh-issue-comments",
    )
    YOLO_CONTAINER_DETECTION = HandlerIDMeta(
        class_name="YoloContainerDetectionHandler",
        config_key="yolo_container_detection",
        display_name="yolo-container-detection",
    )
    PLAN_TIME_ESTIMATES = HandlerIDMeta(
        class_name="PlanTimeEstimatesHandler",
        config_key="plan_time_estimates",
        display_name="block-plan-time-estimates",
    )
    PLAN_WORKFLOW = HandlerIDMeta(
        class_name="PlanWorkflowHandler",
        config_key="plan_workflow",
        display_name="plan-workflow-guidance",
    )
    NPM_COMMAND = HandlerIDMeta(
        class_name="NpmCommandHandler",
        config_key="npm_command",
        display_name="enforce-npm-commands",
    )
    TASK_COMPLETION_CHECKER = HandlerIDMeta(
        class_name="TaskCompletionCheckerHandler",
        config_key="task_completion_checker",
        display_name="task-completion-checker",
    )
    TASK_TDD_ADVISOR = HandlerIDMeta(
        class_name="TaskTddAdvisorHandler",
        config_key="task_tdd_advisor",
        display_name="task-tdd-advisor",
    )
    BASH_ERROR_DETECTOR = HandlerIDMeta(
        class_name="BashErrorDetectorHandler",
        config_key="bash_error_detector",
        display_name="bash-error-detector",
    )
    WEB_SEARCH_YEAR = HandlerIDMeta(
        class_name="WebSearchYearHandler",
        config_key="web_search_year",
        display_name="validate-websearch-year",
    )
    SUGGEST_STATUSLINE = HandlerIDMeta(
        class_name="SuggestStatusLineHandler",
        config_key="suggest_status_line",
        display_name="suggest-statusline",
    )
    VERSION_CHECK = HandlerIDMeta(
        class_name="VersionCheckHandler",
        config_key="version_check",
        display_name="version-check",
    )
    PLAN_COMPLETION_ADVISOR = HandlerIDMeta(
        class_name="PlanCompletionAdvisorHandler",
        config_key="plan_completion_advisor",
        display_name="plan-completion-advisor",
    )
    GLOBAL_NPM_ADVISOR = HandlerIDMeta(
        class_name="GlobalNpmAdvisorHandler",
        config_key="global_npm_advisor",
        display_name="advise-global-npm",
    )

    # Advisory handlers (Priority: 55-60)
    CRITICAL_THINKING_ADVISORY = HandlerIDMeta(
        class_name="CriticalThinkingAdvisoryHandler",
        config_key="critical_thinking_advisory",
        display_name="critical-thinking-advisory",
    )
    BRITISH_ENGLISH = HandlerIDMeta(
        class_name="BritishEnglishHandler",
        config_key="british_english",
        display_name="enforce-british-english",
    )

    # Logging/cleanup handlers (Priority: 100)
    NOTIFICATION_LOGGER = HandlerIDMeta(
        class_name="NotificationLoggerHandler",
        config_key="notification_logger",
        display_name="notification-logger",
    )
    SUBAGENT_COMPLETION_LOGGER = HandlerIDMeta(
        class_name="SubagentCompletionLoggerHandler",
        config_key="subagent_completion_logger",
        display_name="subagent-completion-logger",
    )
    REMIND_PROMPT_LIBRARY = HandlerIDMeta(
        class_name="RemindPromptLibraryHandler",
        config_key="remind_prompt_library",
        display_name="remind-capture-prompt",
    )
    SESSION_CLEANUP = HandlerIDMeta(
        class_name="CleanupHandler",
        config_key="cleanup",
        display_name="session-cleanup",
    )

    # Status line handlers (varied priorities)
    ACCOUNT_DISPLAY = HandlerIDMeta(
        class_name="AccountDisplayHandler",
        config_key="account_display",
        display_name="status-account-display",
    )
    MODEL_CONTEXT = HandlerIDMeta(
        class_name="ModelContextHandler",
        config_key="model_context",
        display_name="status-model-context",
    )
    USAGE_TRACKING = HandlerIDMeta(
        class_name="UsageTrackingHandler",
        config_key="usage_tracking",
        display_name="status-usage-tracking",
    )

    # Workflow state handlers (no fixed priority)
    WORKFLOW_STATE_RESTORATION = HandlerIDMeta(
        class_name="WorkflowStateRestorationHandler",
        config_key="workflow_state_restoration",
        display_name="workflow-state-restoration",
    )
    WORKFLOW_STATE_PRE_COMPACT = HandlerIDMeta(
        class_name="WorkflowStatePreCompactHandler",
        config_key="workflow_state_pre_compact",
        display_name="workflow-state-precompact",
    )

    # Thinking mode status (status line)
    THINKING_MODE = HandlerIDMeta(
        class_name="ThinkingModeHandler",
        config_key="thinking_mode",
        display_name="status-thinking-mode",
    )

    # Optimal config checker (SessionStart handler)
    OPTIMAL_CONFIG_CHECKER = HandlerIDMeta(
        class_name="OptimalConfigCheckerHandler",
        config_key="optimal_config_checker",
        display_name="optimal-config-checker",
    )

    # Lint on edit (PostToolUse handler)
    LINT_ON_EDIT = HandlerIDMeta(
        class_name="LintOnEditHandler",
        config_key="lint_on_edit",
        display_name="lint-on-edit",
    )

    # Hedging language detector (Stop handler)
    HEDGING_LANGUAGE_DETECTOR = HandlerIDMeta(
        class_name="HedgingLanguageDetectorHandler",
        config_key="hedging_language_detector",
        display_name="hedging-language-detector",
    )


# Type-safe config key literal (for mypy/type checking)
HandlerKey = Literal[
    # Orchestrator-only mode
    "orchestrator_only",
    # Test handlers
    "hello_world_pre_tool_use",
    "hello_world_post_tool_use",
    "hello_world_session_start",
    "hello_world_session_end",
    "hello_world_stop",
    "hello_world_subagent_stop",
    "hello_world_user_prompt_submit",
    "hello_world_pre_compact",
    "hello_world_notification",
    "hello_world_permission_request",
    # Safety handlers
    "daemon_restart_verifier",
    "destructive_git",
    "sed_blocker",
    "pip_break_system",
    "sudo_pip",
    "curl_pipe_shell",
    "dangerous_permissions",
    "auto_approve_reads",
    "validate_eslint_on_write",
    "transcript_archiver",
    "absolute_path",
    "tdd_enforcement",
    "auto_continue_stop",
    "worktree_file_copy",
    "git_context_injector",
    "git_branch",
    "current_time",
    "pipe_blocker",
    "git_stash",
    # QA enforcement handlers
    "qa_suppression",
    "validate_plan_number",
    "plan_number_helper",
    "daemon_stats",
    "markdown_organization",
    "validate_instruction_content",
    # Lint on edit
    "lint_on_edit",
    # Workflow handlers
    "gh_issue_comments",
    "yolo_container_detection",
    "plan_time_estimates",
    "plan_workflow",
    "npm_command",
    "task_completion_checker",
    "hedging_language_detector",
    "optimal_config_checker",
    "bash_error_detector",
    "web_search_year",
    "suggest_status_line",
    "plan_completion_advisor",
    "global_npm_advisor",
    # Advisory handlers
    "critical_thinking_advisory",
    "british_english",
    # Logging/cleanup handlers
    "notification_logger",
    "subagent_completion_logger",
    "remind_prompt_library",
    "cleanup",
    # Status line handlers
    "git_repo_name",
    "account_display",
    "model_context",
    "usage_tracking",
    # Workflow state handlers
    "workflow_state_restoration",
    "workflow_state_pre_compact",
]
