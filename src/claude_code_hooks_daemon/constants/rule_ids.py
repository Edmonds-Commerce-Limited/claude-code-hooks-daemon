"""Rule identifier constants — single source of truth for all rule IDs.

Rule IDs are a PUBLIC CONTRACT (Decision D, Plan 00116): they appear in
user CLAUDE.md and in block messages. Once assigned, a rule ID MUST NOT be
renamed without a breaking-change upgrade guide entry.

Naming convention: ``R-`` prefix, then SCREAMING-KEBAB-CASE.
Example: ``R-GIT-RESET-HARD``.

Usage::

    from claude_code_hooks_daemon.constants.rule_ids import RuleID

    rule = Rule(
        rule_id=RuleID.GIT_RESET_HARD,
        blocked="`git reset --hard`",
        ...
    )
"""


class RuleID:
    """Single source of truth for all rule identifiers.

    All values follow the ``R-SCREAMING-KEBAB-CASE`` convention and must be
    unique across the entire codebase.  Any rename is a breaking change and
    MUST be documented in the upgrade guide.
    """

    # ------------------------------------------------------------------
    # destructive_git handler — 9 rules (Decision B: per-rule granularity)
    # ------------------------------------------------------------------

    #: git reset --hard — permanently destroys all uncommitted changes.
    GIT_RESET_HARD: str = "R-GIT-RESET-HARD"

    #: git clean -f — permanently deletes untracked files.
    GIT_CLEAN_FORCE: str = "R-GIT-CLEAN-FORCE"

    #: git checkout [REF] -- <file> — discards all local changes to a file.
    GIT_CHECKOUT_DISCARD: str = "R-GIT-CHECKOUT-DISCARD"

    #: git restore <file> — discards working-tree changes (--staged is allowed).
    GIT_RESTORE: str = "R-GIT-RESTORE"

    #: git stash drop — permanently destroys a stash entry.
    GIT_STASH_DROP: str = "R-GIT-STASH-DROP"

    #: git stash clear — permanently destroys all stash entries.
    GIT_STASH_CLEAR: str = "R-GIT-STASH-CLEAR"

    #: git push --force — can overwrite remote history and destroy team work.
    GIT_PUSH_FORCE: str = "R-GIT-PUSH-FORCE"

    #: git branch -D — force-deletes a branch without checking if it is merged.
    GIT_BRANCH_FORCE_DELETE: str = "R-GIT-BRANCH-FORCE-DELETE"

    #: git commit --amend — rewrites the previous commit.
    GIT_COMMIT_AMEND: str = "R-GIT-COMMIT-AMEND"

    # ------------------------------------------------------------------
    # sed_blocker handler
    # ------------------------------------------------------------------

    #: sed -i / sed -e — in-place file editing via Bash; use Edit tool instead.
    SED_FILE_MODIFICATION: str = "R-SED-FILE-MODIFICATION"

    # ------------------------------------------------------------------
    # pipe_blocker handler
    # ------------------------------------------------------------------

    #: Piping to tail — truncates output and causes information loss.
    PIPE_TO_TAIL: str = "R-PIPE-TO-TAIL"

    #: Piping to head — truncates output and causes information loss.
    PIPE_TO_HEAD: str = "R-PIPE-TO-HEAD"

    # ------------------------------------------------------------------
    # dangerous_permissions handler
    # ------------------------------------------------------------------

    #: chmod 777 / chmod a+w / chmod o+w — world-writable permissions.
    CHMOD_WORLD_WRITABLE: str = "R-CHMOD-WORLD-WRITABLE"

    # ------------------------------------------------------------------
    # curl_pipe_shell handler
    # ------------------------------------------------------------------

    #: curl URL | bash — executes untrusted remote code without inspection.
    CURL_PIPE_SHELL: str = "R-CURL-PIPE-SHELL"

    # ------------------------------------------------------------------
    # git_stash handler (stash push — distinct from stash drop/clear above)
    # ------------------------------------------------------------------

    #: git stash / git stash push — stashes get forgotten; use WIP commits.
    GIT_STASH_PUSH: str = "R-GIT-STASH-PUSH"

    # ------------------------------------------------------------------
    # plan_time_estimates handler
    # ------------------------------------------------------------------

    #: Time/date estimates in a plan document — plans describe WHAT, not WHEN.
    PLAN_TIME_ESTIMATE: str = "R-PLAN-TIME-ESTIMATE"

    # ------------------------------------------------------------------
    # ask_user_question_blocker handler
    # ------------------------------------------------------------------

    #: AskUserQuestion missing the required 'ASKING BECAUSE:' justification prefix.
    ASK_USER_QUESTION_UNJUSTIFIED: str = "R-ASK-USER-QUESTION-UNJUSTIFIED"

    # ------------------------------------------------------------------
    # plan_qa_edit / plan_qa_commit_gate handlers (gate-level granularity)
    # ------------------------------------------------------------------

    #: A PLAN.md/README.md Write/Edit violates a block-level plan QA check.
    PLAN_QA_EDIT: str = "R-PLAN-QA-EDIT"

    #: A git commit violates a block-level plan QA cross-file invariant.
    PLAN_QA_COMMIT: str = "R-PLAN-QA-COMMIT"

    # ------------------------------------------------------------------
    # docs_qa_edit / docs_qa_commit_gate handlers (gate-level granularity)
    # ------------------------------------------------------------------

    #: A documentation Write/Edit violates a block-level docs QA check.
    DOCS_QA_EDIT: str = "R-DOCS-QA-EDIT"

    #: A git commit violates a block-level docs QA staged-tree check.
    DOCS_QA_COMMIT: str = "R-DOCS-QA-COMMIT"

    # ------------------------------------------------------------------
    # staged_lint_gate handler
    # ------------------------------------------------------------------

    #: A staged file fails the cheap syntax check at commit time.
    STAGED_LINT_FAILURE: str = "R-STAGED-LINT-FAILURE"

    # ------------------------------------------------------------------
    # auto_continue_stop handler (stop event; concept-level granularity)
    # ------------------------------------------------------------------

    #: Stop attempted with no 'STOPPING BECAUSE:' explanation.
    STOP_NO_REASON: str = "R-STOP-NO-REASON"

    #: Stop attempted by smuggling a rhetorical/tautological continue question.
    STOP_TAUTOLOGICAL_QUESTION: str = "R-STOP-TAUTOLOGICAL-QUESTION"

    #: Stop attempted right after an unresolved tool_use_error.
    STOP_AFTER_TOOL_ERROR: str = "R-STOP-AFTER-TOOL-ERROR"

    #: Stop attempted while a goal-ledger entry is still live/unexplained.
    STOP_GOAL_LEDGER: str = "R-STOP-GOAL-LEDGER"

    # ------------------------------------------------------------------
    # ancestry_preserving_merge handler — 3 rules (one per severing spelling)
    # ------------------------------------------------------------------

    #: git merge --squash — severs ancestry, git branch -d refuses forever.
    GIT_MERGE_SQUASH: str = "R-GIT-MERGE-SQUASH"

    #: gh pr merge --squash — GitHub's squash-merge integration button.
    GH_PR_MERGE_SQUASH: str = "R-GH-PR-MERGE-SQUASH"

    #: gh pr merge --rebase — GitHub's rebase-merge integration button.
    GH_PR_MERGE_REBASE: str = "R-GH-PR-MERGE-REBASE"

    # ------------------------------------------------------------------
    # git_message_backtick handler
    # ------------------------------------------------------------------

    #: Unescaped backtick in a double-quoted git commit/tag message — executed, not quoted.
    GIT_MESSAGE_BACKTICK: str = "R-GIT-MESSAGE-BACKTICK"

    # ------------------------------------------------------------------
    # github_auto_close_keywords handler
    # ------------------------------------------------------------------

    #: A GitHub closing keyword + issue reference in a git/gh message — auto-closes on merge.
    GH_AUTO_CLOSE_KEYWORD: str = "R-GH-AUTO-CLOSE-KEYWORD"

    # ------------------------------------------------------------------
    # gh_issue_comments handler
    # ------------------------------------------------------------------

    #: gh issue view without --comments — misses issue discussion context.
    GH_ISSUE_VIEW_NO_COMMENTS: str = "R-GH-ISSUE-VIEW-NO-COMMENTS"

    # ------------------------------------------------------------------
    # gh_pr_comments handler
    # ------------------------------------------------------------------

    #: gh pr view without --comments — misses PR review discussion context.
    GH_PR_VIEW_NO_COMMENTS: str = "R-GH-PR-VIEW-NO-COMMENTS"

    # ------------------------------------------------------------------
    # worktree_file_copy handler
    # ------------------------------------------------------------------

    #: cp/mv/rsync between a worktree and the main repo — breaks isolation.
    WORKTREE_FILE_COPY: str = "R-WORKTREE-FILE-COPY"

    # ------------------------------------------------------------------
    # plan_number_helper handler — 2 rules
    # ------------------------------------------------------------------

    #: A bash discovery scan (ls/find/sort+tail) for the next plan number.
    PLAN_NUMBER_DISCOVERY: str = "R-PLAN-NUMBER-DISCOVERY"

    #: mkdir of a new NNNNN-name plan folder — claims a number unsynchronised.
    PLAN_FOLDER_MKDIR: str = "R-PLAN-FOLDER-MKDIR"
