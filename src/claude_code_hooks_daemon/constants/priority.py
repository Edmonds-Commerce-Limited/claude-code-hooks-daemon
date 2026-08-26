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

    # Default priority for handlers that don't specify one (matches Handler.__init__ default)
    DEFAULT = 50

    # Test handlers (Priority: 5). Named for the ROLE, not for a handler: the
    # hello_world canaries it was named after are gone, but the test suite uses
    # this throughout for purpose-built handlers that must sort before every real
    # one.
    TEST_HANDLER = 5

    # Safety handlers (Priority: 10-20)
    DAEMON_RESTART_VERIFIER = 10
    DESTRUCTIVE_GIT = 10
    SED_BLOCKER = 10
    PIP_BREAK_SYSTEM = 10
    SUDO_PIP = 10
    CURL_PIPE_SHELL = 10
    ASK_USER_QUESTION_BLOCKER = 10
    LOCK_FILE_EDIT_BLOCKER = 10
    AUTO_APPROVE_READS = 10
    VALIDATE_ESLINT_ON_WRITE = 10
    COMPACTION_SIGNAL = 20  # PreCompact: drop compaction signal for the PTY supervisor

    DAEMON_LOCATION_GUARD = 11

    ABSOLUTE_PATH = 12

    ERROR_HIDING_BLOCKER = 13

    SECURITY_ANTIPATTERN = 14
    SENSITIVE_CONTENT = 14
    # Same band as the two above, and for the same reason: all three guard
    # content leaving the project rather than a workflow preference.
    ARTIFACT_PUBLISH_BLOCKER = 14

    ROOT_RECURSION_GUARD = 16
    # Runs after the blocking safety handlers on purpose: a Read they DENY never
    # happened, so it must not be recorded as knowledge of the file.
    WRITE_CLOBBER_GUARD = 16

    TDD_ENFORCEMENT = 15
    DANGEROUS_PERMISSIONS = 15
    AUTO_CONTINUE_STOP = 15
    WORKTREE_FILE_COPY = 15
    PIPE_BLOCKER = 15

    GIT_CONTEXT_INJECTOR = 20
    GIT_BRANCH = 20
    GIT_STASH = 20
    # Plan 00207: sits beside GIT_STASH -- both are safety-band git-workflow
    # opinions with a mode option and a MUST_..._BECAUSE escape hatch. Relative
    # order does not change any verdict since the two match disjoint command
    # sets (merge/gh-pr-merge vs stash).
    ANCESTRY_PRESERVING_MERGE = 19

    # Plan 00219: deliberately BELOW destructive_git (10) and the other
    # full-string matchers. When a backticked span holds a dangerous command,
    # those deny first and their reason is the more useful one -- naming the
    # destructive operation rather than the quoting. This handler exists for
    # the remaining case: a BENIGN backticked span that would be silently
    # eaten by command substitution, which nothing else watches.
    GIT_MESSAGE_BACKTICK = 20

    # Lint on edit (Priority: 25 - code quality range)
    LINT_ON_EDIT = 25

    # Markdown table formatter (Priority: 26 - adjacent to lint_on_edit)
    MARKDOWN_TABLE_FORMATTER = 26

    # Git hooks executable fixer (Priority: 27 - adjacent to other PostToolUse fixers)
    GIT_HOOKS_EXECUTABLE_FIXER = 27

    # Background-process tracker (Priority: 28 - PostToolUse advisory)
    BACKGROUND_PROCESS_TRACKER = 28

    # Command hints (Priority: 29 - PostToolUse advisory reminders after
    # specific commands; sits between background_process_tracker and
    # recovery_cron_advisor)
    COMMAND_HINTS = 29

    # PostToolUse advisory handlers (Priority: 30)
    RECOVERY_CRON_ADVISOR = 30

    # Goal injection (Priority: 31 - PostToolUse plan-execution-start sensor;
    # sits after recovery_cron_advisor, which watches the same PLAN.md writes)
    GOAL_INJECTION = 31

    # QA enforcement handlers (Priority: 30-35)
    QA_SUPPRESSION = 30
    PLAN_NUMBER_HELPER = 30
    DAEMON_STATS = 30
    # Extracted from DAEMON_STATS (Plan 00167) so the upgrade prompt reaches
    # every client on-by-default, independent of the off-by-default dev health
    # line. Sits right after it so the arrow renders in the same trailing area.
    UPGRADE_NOTIFIER = 32

    # Plan 00208: comment_changelog is "the valuable half" (history-shaped
    # narrative in a comment); comment_size is the secondary, symptom-level
    # size cap. Both content-quality, both sit in the same band as
    # qa_suppression/markdown_organization.
    COMMENT_CHANGELOG = 31
    COMMENT_SIZE = 33

    # Plan 00268: "a verification result must be consumed" is QA enforcement,
    # so it sits in this band rather than with the safety blockers. Advisory by
    # default, and non-terminal either way, so its exact slot only decides the
    # order its context appears in.
    VERIFICATION_RESULT_GATE = 34

    MARKDOWN_ORGANIZATION = 35

    # Plan 00270: the opt-in safe-prelude forcer opens the 36-55 workflow
    # band, right after its sibling verification_result_gate (34) so the
    # sibling speaks first — a specific verifier→mutator finding appears
    # before the generic prelude advisory.
    BASH_SAFE_MODE = 36

    # LSP enforcement (Priority: 38)
    LSP_ENFORCEMENT = 38

    # Workflow handlers (Priority: 35-55)
    GH_ISSUE_COMMENTS = 40
    GH_PR_COMMENTS = 40
    PLAN_TIME_ESTIMATES = 40
    GLOBAL_NPM_ADVISOR = 40

    # Plan 00268 Task 3.2: sits between the workflow-40s entries and the plan
    # QA pair at 44 -- a sibling gate on the same `git commit` trigger, not an
    # extension of either.
    STAGED_LINT_GATE = 43

    PLAN_QA_EDIT = 44
    PLAN_QA_COMMIT_GATE = 44
    PLAN_WORKFLOW = 45
    AGENT_ISOLATION_ADVISOR = 46

    NPM_COMMAND = 50
    VALIDATE_INSTRUCTION_CONTENT = 50

    WEB_SEARCH_YEAR = 55
    PROJECT_HANDLER_LOAD_CHECKER = 50
    HOOK_REGISTRATION_CHECKER = 51
    OPTIMAL_CONFIG_CHECKER = 52
    GIT_FILEMODE_CHECKER = 53
    GITIGNORE_SAFETY_CHECKER = 54
    SUGGEST_STATUSLINE = 55
    VERSION_CHECK = 55
    GIT_UPSTREAM_CHECKER = 56
    PLAN_QA_SWEEP = 57
    CCY_SUPERVISOR_INTEGRITY = 58
    PLAN_WORKFLOW_ASSET_CHECKER = 59
    CONTRACT_STALENESS = 60
    SKILL_OPPORTUNITY_DETECTOR = 61

    # Advisory handlers (Priority: 55-65)
    CRITICAL_THINKING_ADVISORY = 55
    IDLE_HOUSEKEEPING_ADVISORY = 56
    # Last of the UserPromptSubmit advisories deliberately (Plan 00223): the
    # injected context block sits AFTER the user's prompt, so a higher number
    # is the recency position within it.
    STANDING_AUTHORISATIONS = 57
    NITPICK_DISMISSIVE = 10
    NITPICK_HEDGING = 20
    DAEMON_DOCS_GUARD = 57
    BRITISH_ENGLISH = 60

    # Status line handlers (varied priorities)
    MULTITHREAD_INDICATOR = 2  # "🧵 Y/X" — first segment; this thread's rank among live threads
    GIT_REPO_NAME = 3
    ENVIRONMENT_INDICATOR = 4  # After repo name, before account display
    ACCOUNT_DISPLAY = 5
    MODEL_CONTEXT = 10
    CONTEXT_SIDECAR = 12  # Observe-only context sidecar for the PTY supervisor (opt-in)
    SUPERVISOR_INDICATOR = 13  # ccy PTY supervisor armed/dryrun/inactive shield (opt-in)
    CURRENT_TIME = 14
    WORKING_DIRECTORY = 25
    STARTUP_CLEANUP = 28  # Between working_directory (25) and daemon_stats (30)


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
    # Widened from 60 for skill_opportunity_detector (Plan 00274): 56-60 was
    # fully occupied by the SessionStart advisory ladder ending at
    # contract_staleness (60). Documented in root CLAUDE.md's Priority Ranges.
    ADVISORY_MAX = 65

    LOGGING_MIN = 100
    LOGGING_MAX = 199
