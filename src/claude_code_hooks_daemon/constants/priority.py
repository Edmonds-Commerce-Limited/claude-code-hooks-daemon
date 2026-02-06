"""Handler priority constants - Single source of truth for all handler priorities.

This module defines the execution priority for all handlers.
Lower priority values execute first.

Priority Ranges:
- 5: Test handlers only
- 10-20: Safety and critical handlers (destructive operations, auto-approval)
- 30-35: Code quality and QA enforcement
- 40-55: Workflow and process enforcement
- 60: Advisory and suggestions
- 100: Logging, metrics, and cleanup

Usage:
    from claude_code_hooks_daemon.constants import Priority

    class MyHandler(Handler):
        def __init__(self) -> None:
            super().__init__(
                priority=Priority.DESTRUCTIVE_GIT,  # Not magic number 10!
            )
"""


class Priority:
    """Handler priority constants with semantic meaning.

    Each constant is named after a handler and defines its execution priority.
    This ensures priorities are never magic numbers and makes refactoring safe.
    """

    # Orchestrator-only mode (Priority: 8 - before all other handlers)
    ORCHESTRATOR_ONLY = 8

    # Test handlers (Priority: 5)
    HELLO_WORLD = 5

    # Safety handlers (Priority: 10-20)
    DAEMON_RESTART_VERIFIER = 10
    DESTRUCTIVE_GIT = 10
    SED_BLOCKER = 10
    PIP_BREAK_SYSTEM = 10
    SUDO_PIP = 10
    CURL_PIPE_SHELL = 10
    LOCK_FILE_EDIT_BLOCKER = 10
    AUTO_APPROVE_READS = 10
    VALIDATE_ESLINT_ON_WRITE = 10
    REMIND_VALIDATOR = 10
    TRANSCRIPT_ARCHIVER = 10

    ABSOLUTE_PATH = 12

    TDD_ENFORCEMENT = 15
    DANGEROUS_PERMISSIONS = 15
    AUTO_CONTINUE_STOP = 15
    WORKTREE_FILE_COPY = 15
    PIPE_BLOCKER = 15

    GIT_CONTEXT_INJECTOR = 20
    GIT_BRANCH = 20
    GIT_STASH = 20
    VALIDATE_SITEMAP = 20

    # QA enforcement handlers (Priority: 30-35)
    PYTHON_QA_SUPPRESSION = 30
    PHP_QA_SUPPRESSION = 30
    GO_QA_SUPPRESSION = 30
    ESLINT_DISABLE = 30
    VALIDATE_PLAN_NUMBER = 30
    PLAN_NUMBER_HELPER = 30
    DAEMON_STATS = 30

    MARKDOWN_ORGANIZATION = 35

    # Workflow handlers (Priority: 40-55)
    GH_ISSUE_COMMENTS = 40
    YOLO_CONTAINER_DETECTION = 40
    PLAN_TIME_ESTIMATES = 40
    GLOBAL_NPM_ADVISOR = 40

    PLAN_WORKFLOW = 45
    TASK_TDD_ADVISOR = 45

    NPM_COMMAND = 50
    PLAN_COMPLETION_ADVISOR = 50
    TASK_COMPLETION_CHECKER = 50
    BASH_ERROR_DETECTOR = 50

    WEB_SEARCH_YEAR = 55
    SUGGEST_STATUSLINE = 55

    # Advisory handlers (Priority: 60)
    BRITISH_ENGLISH = 60

    # Logging/cleanup handlers (Priority: 100)
    NOTIFICATION_LOGGER = 100
    SUBAGENT_COMPLETION_LOGGER = 100
    REMIND_PROMPT_LIBRARY = 100
    SESSION_CLEANUP = 100

    # Status line handlers (varied priorities)
    GIT_REPO_NAME = 3
    ACCOUNT_DISPLAY = 5
    MODEL_CONTEXT = 10
    USAGE_TRACKING = 15

    # Special handlers (no fixed priority in catalog)
    # These handlers set priority dynamically or don't use the standard system
    WORKFLOW_STATE_RESTORATION = 50  # Reasonable default
    WORKFLOW_STATE_PRE_COMPACT = 50  # Reasonable default
    STATS_CACHE_READER = 20  # Reasonable default


# Priority range constants (for validation and documentation)
class PriorityRange:
    """Priority range definitions for different handler categories."""

    TEST_MIN = 0
    TEST_MAX = 9

    SAFETY_MIN = 10
    SAFETY_MAX = 20

    QUALITY_MIN = 25
    QUALITY_MAX = 35

    WORKFLOW_MIN = 36
    WORKFLOW_MAX = 55

    ADVISORY_MIN = 56
    ADVISORY_MAX = 60

    LOGGING_MIN = 100
    LOGGING_MAX = 199
