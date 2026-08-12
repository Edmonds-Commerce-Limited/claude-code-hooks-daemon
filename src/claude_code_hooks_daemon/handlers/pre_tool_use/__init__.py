"""PreToolUse handlers for claude-code-hooks-daemon."""

from .absolute_path import AbsolutePathHandler
from .ancestry_preserving_merge import AncestryPreservingMergeHandler
from .british_english import BritishEnglishHandler
from .comment_changelog import CommentChangelogHandler
from .comment_size import CommentSizeHandler
from .daemon_location_guard import DaemonLocationGuardHandler
from .destructive_git import DestructiveGitHandler
from .error_hiding_blocker import ErrorHidingBlockerHandler
from .gh_issue_comments import GhIssueCommentsHandler
from .gh_pr_comments import GhPrCommentsHandler
from .git_stash import GitStashHandler
from .markdown_organization import MarkdownOrganizationHandler
from .npm_command import NpmCommandHandler
from .plan_qa_commit_gate import PlanQaCommitGateHandler
from .plan_qa_edit import PlanQaEditHandler
from .plan_time_estimates import PlanTimeEstimatesHandler
from .plan_workflow import PlanWorkflowHandler
from .qa_suppression import QaSuppressionHandler
from .root_recursion_guard import RootRecursionGuardHandler
from .security_antipattern import SecurityAntipatternHandler
from .sed_blocker import SedBlockerHandler
from .tdd_enforcement import TddEnforcementHandler
from .validate_instruction_content import ValidateInstructionContentHandler
from .validate_plan_number import ValidatePlanNumberHandler
from .web_search_year import WebSearchYearHandler
from .worktree_file_copy import WorktreeFileCopyHandler

__all__ = [
    "AbsolutePathHandler",
    "AncestryPreservingMergeHandler",
    "BritishEnglishHandler",
    "CommentChangelogHandler",
    "CommentSizeHandler",
    "DaemonLocationGuardHandler",
    "DestructiveGitHandler",
    "ErrorHidingBlockerHandler",
    "GhIssueCommentsHandler",
    "GhPrCommentsHandler",
    "GitStashHandler",
    "MarkdownOrganizationHandler",
    "NpmCommandHandler",
    "PlanQaCommitGateHandler",
    "PlanQaEditHandler",
    "PlanTimeEstimatesHandler",
    "PlanWorkflowHandler",
    "QaSuppressionHandler",
    "RootRecursionGuardHandler",
    "SecurityAntipatternHandler",
    "SedBlockerHandler",
    "TddEnforcementHandler",
    "ValidateInstructionContentHandler",
    "ValidatePlanNumberHandler",
    "WebSearchYearHandler",
    "WorktreeFileCopyHandler",
]
