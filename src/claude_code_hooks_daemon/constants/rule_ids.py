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
    # root_recursion_guard handler
    # ------------------------------------------------------------------

    #: A recursive scanner (grep -r, find, rg, ...) rooted at /, /proc, /sys,
    #: /home, /root, ~ or $HOME — walks the entire filesystem.
    ROOT_RECURSION_CATASTROPHIC: str = "R-ROOT-RECURSION-CATASTROPHIC"

    # ------------------------------------------------------------------
    # dangerous_permissions handler (sudo_pip/pip_break_system are separate)
    # ------------------------------------------------------------------

    #: sudo pip install — installing as root corrupts the OS-managed Python.
    SUDO_PIP_INSTALL: str = "R-SUDO-PIP-INSTALL"

    #: pip install --break-system-packages — bypasses PEP 668 protection.
    PIP_BREAK_SYSTEM_PACKAGES: str = "R-PIP-BREAK-SYSTEM-PACKAGES"

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

    #: Stop attempted right after a QA tool's own output indicated failure.
    STOP_QA_FAILURE: str = "R-STOP-QA-FAILURE"

    #: Stop attempted after asking a non-rhetorical confirmation question.
    STOP_CONFIRMATION_QUESTION: str = "R-STOP-CONFIRMATION-QUESTION"

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

    # ------------------------------------------------------------------
    # tdd_enforcement handler
    # ------------------------------------------------------------------

    #: Creating a production source file with no corresponding test file yet.
    TDD_TEST_FIRST: str = "R-TDD-TEST-FIRST"

    # ------------------------------------------------------------------
    # qa_suppression handler
    # ------------------------------------------------------------------

    #: A QA suppression directive (noqa, type: ignore, eslint-disable, ...).
    QA_SUPPRESSION: str = "R-QA-SUPPRESSION"

    # ------------------------------------------------------------------
    # security_antipattern handler — 6 category rules (real category
    # structure: 5 OWASP-named mechanisms plus Rust's unsafe-memory outliers,
    # which fit none of the five).
    # ------------------------------------------------------------------

    #: eval/exec/new Function/__import__/instance_eval/yaml.load — code injection.
    SEC_CODE_INJECTION: str = "R-SEC-CODE-INJECTION"

    #: os.system/shell=True/shell_exec/proc_open/Runtime.exec/... — command injection.
    SEC_CMD_INJECTION: str = "R-SEC-CMD-INJECTION"

    #: pickle.load/Marshal.load/unserialize/ObjectInputStream/... — unsafe deserialisation.
    SEC_DESERIALISATION: str = "R-SEC-DESERIALISATION"

    #: innerHTML/dangerouslySetInnerHTML/document.write/template.HTML|JS|URL — XSS.
    SEC_XSS: str = "R-SEC-XSS"

    #: AWS/GitHub/Stripe keys, private key blocks — hardcoded credentials.
    SEC_HARDCODED_CREDS: str = "R-SEC-HARDCODED-CREDS"

    #: Rust from_raw_parts/transmute — unsafe memory/type-safety bypass.
    SEC_UNSAFE_MEMORY: str = "R-SEC-UNSAFE-MEMORY"

    # ------------------------------------------------------------------
    # error_hiding_blocker handler
    # ------------------------------------------------------------------

    #: A language-specific error-hiding pattern (bare except, || true, _ = err, ...).
    ERROR_HIDING: str = "R-ERROR-HIDING"

    # ------------------------------------------------------------------
    # comment_changelog handler
    # ------------------------------------------------------------------

    #: Changelog narrative (Prior/Previously <version>:, a dated entry) in a comment.
    COMMENT_CHANGELOG: str = "R-COMMENT-CHANGELOG"

    # ------------------------------------------------------------------
    # comment_size handler
    # ------------------------------------------------------------------

    #: A comment line or block growing past the configured size limit.
    COMMENT_SIZE: str = "R-COMMENT-SIZE"

    # ------------------------------------------------------------------
    # npm_command handler — 2 rules (distinct deny shapes)
    # ------------------------------------------------------------------

    #: A piped npm run/npx command — llm: caches make piping pointless.
    NPM_PIPED_COMMAND: str = "R-NPM-PIPED-COMMAND"

    #: A raw npm run/npx command when llm: wrapper scripts exist in package.json.
    NPM_NON_LLM_COMMAND: str = "R-NPM-NON-LLM-COMMAND"

    # ------------------------------------------------------------------
    # lsp_enforcement handler
    # ------------------------------------------------------------------

    #: A symbol-like Grep/Bash grep lookup LSP tools would serve better.
    LSP_SYMBOL_LOOKUP: str = "R-LSP-SYMBOL-LOOKUP"

    # ------------------------------------------------------------------
    # lint_on_edit handler (post_tool_use)
    # ------------------------------------------------------------------

    #: A written/authored file fails its language's lint check.
    LINT_FAILURE: str = "R-LINT-FAILURE"

    # ------------------------------------------------------------------
    # validate_eslint_on_write handler (post_tool_use) — 3 rules (distinct
    # failure shapes: reported errors, a timeout, and a run failure).
    # ------------------------------------------------------------------

    #: ESLint ran and reported errors on a written/authored TS/TSX file.
    ESLINT_ERRORS: str = "R-ESLINT-ERRORS"

    #: ESLint did not finish within the configured timeout.
    ESLINT_TIMEOUT: str = "R-ESLINT-TIMEOUT"

    #: ESLint failed to run at all (exception raised invoking it).
    ESLINT_RUN_FAILURE: str = "R-ESLINT-RUN-FAILURE"

    # ------------------------------------------------------------------
    # secret_file_guard handler — 3 rules (Decision B: per-route granularity)
    # ------------------------------------------------------------------

    #: Read/Write/Edit/NotebookEdit/Grep targeting a protected path directly.
    SECRET_READ: str = "R-SECRET-READ"

    #: A Bash command whose text mentions a protected path.
    SECRET_BASH_MENTION: str = "R-SECRET-BASH-MENTION"

    #: A script authored via Write/Edit whose content references a protected path.
    SECRET_SCRIPT_AUTHOR: str = "R-SECRET-SCRIPT-AUTHOR"

    # ------------------------------------------------------------------
    # sensitive_content handler — 2 rules (two independent sources)
    # ------------------------------------------------------------------

    #: Content matches a configured public pattern (safe to name in the reason).
    SENSITIVE_PUBLIC_PATTERN: str = "R-SENSITIVE-PUBLIC-PATTERN"

    #: Content matches a gitignored secret word list term (never echoed).
    SENSITIVE_SECRET_TERM: str = "R-SENSITIVE-SECRET-TERM"

    # ------------------------------------------------------------------
    # markdown_organization handler — 3 rules
    # ------------------------------------------------------------------

    #: A new .md file written to a location outside the allowed set.
    MARKDOWN_WRONG_LOCATION: str = "R-MARKDOWN-WRONG-LOCATION"

    #: A write to an untracked Claude auto-memory file (policy: forbidden).
    MARKDOWN_UNTRACKED_MEMORY: str = "R-MARKDOWN-UNTRACKED-MEMORY"

    # ------------------------------------------------------------------
    # remote_docs_provenance handler (Plan 00326) — 1 rule
    # ------------------------------------------------------------------

    #: A remote-docs write whose content lacks valid provenance frontmatter.
    REMOTE_DOCS_PROVENANCE: str = "R-REMOTE-DOCS-PROVENANCE"

    #: plansDirectory misconfigured/out of sync with the daemon's plan_workflow config.
    MARKDOWN_PLAN_SYNC: str = "R-MARKDOWN-PLAN-SYNC"

    # ------------------------------------------------------------------
    # validate_instruction_content handler — 8 rules (one per content category)
    # ------------------------------------------------------------------

    #: Implementation-log sentence ("created the file X") in CLAUDE.md/README.md.
    INSTRUCTION_IMPLEMENTATION_LOG: str = "R-INSTRUCTION-IMPLEMENTATION-LOG"

    #: Status emoji + completion word (e.g. checkmark + 'Done') in an instruction file.
    INSTRUCTION_STATUS_INDICATOR: str = "R-INSTRUCTION-STATUS-INDICATOR"

    #: ISO-format timestamp/date in an instruction file.
    INSTRUCTION_TIMESTAMP: str = "R-INSTRUCTION-TIMESTAMP"

    #: LLM summary section heading ('## Summary', '## Key Points') in an instruction file.
    INSTRUCTION_LLM_SUMMARY: str = "R-INSTRUCTION-LLM-SUMMARY"

    #: Test output count ('3 tests passed') in an instruction file.
    INSTRUCTION_TEST_OUTPUT: str = "R-INSTRUCTION-TEST-OUTPUT"

    #: Changelog-style file listing (e.g. 'created src/Foo.php') in an instruction file.
    INSTRUCTION_FILE_LISTING: str = "R-INSTRUCTION-FILE-LISTING"

    #: Change summary ('added 15 lines') in an instruction file.
    INSTRUCTION_CHANGE_SUMMARY: str = "R-INSTRUCTION-CHANGE-SUMMARY"

    #: Completion indicator ('ALL DONE!', 'Task complete!') in an instruction file.
    INSTRUCTION_COMPLETION_INDICATOR: str = "R-INSTRUCTION-COMPLETION-INDICATOR"

    # ------------------------------------------------------------------
    # lock_file_edit_blocker handler
    # ------------------------------------------------------------------

    #: Direct Write/Edit of a package manager lock file.
    LOCK_FILE_EDIT: str = "R-LOCK-FILE-EDIT"

    # ------------------------------------------------------------------
    # write_clobber_guard handler
    # ------------------------------------------------------------------

    #: Write to an existing file not read this session — would clobber unread content.
    WRITE_CLOBBER: str = "R-WRITE-CLOBBER"

    # ------------------------------------------------------------------
    # absolute_path handler
    # ------------------------------------------------------------------

    #: Read/Write/Edit file_path is relative, not absolute.
    ABSOLUTE_PATH_REQUIRED: str = "R-ABSOLUTE-PATH-REQUIRED"

    # ------------------------------------------------------------------
    # daemon_location_guard handler
    # ------------------------------------------------------------------

    #: cd into .claude/hooks-daemon/ — daemon commands must run from project root.
    DAEMON_DIR_CD: str = "R-DAEMON-DIR-CD"

    # ------------------------------------------------------------------
    # artifact_publish_blocker handler
    # ------------------------------------------------------------------

    #: Artifact tool publish/update — an egress path the repo cannot audit.
    ARTIFACT_PUBLISH: str = "R-ARTIFACT-PUBLISH"

    # ------------------------------------------------------------------
    # quarantine_artefact_read_guard handler (ships disabled)
    # ------------------------------------------------------------------

    #: Reading a quarantined *-opus-security-DETAIL* artefact back into the coordinator.
    QUARANTINE_ARTEFACT_READ: str = "R-QUARANTINE-ARTEFACT-READ"

    # ------------------------------------------------------------------
    # flaggable_content_channel_guard handler (ships disabled)
    # ------------------------------------------------------------------

    #: A content-revealing git/grep command shape over a configured flaggable path.
    FLAGGABLE_CONTENT_CHANNEL: str = "R-FLAGGABLE-CONTENT-CHANNEL"

    # ------------------------------------------------------------------
    # bash_safe_mode handler (ships disabled; block-mode deny path only)
    # ------------------------------------------------------------------

    #: A sequenced Bash invocation declares no required `set` safety prelude.
    BASH_SAFE_MODE_PRELUDE_MISSING: str = "R-BASH-SAFE-MODE-PRELUDE-MISSING"

    # ------------------------------------------------------------------
    # verification_result_gate handler (warn by default; block-mode deny path only)
    # ------------------------------------------------------------------

    #: A verifier's result is never consumed before a mutator runs.
    VERIFICATION_RESULT_NOT_CONSUMED: str = "R-VERIFICATION-RESULT-NOT-CONSUMED"

    # ------------------------------------------------------------------
    # failsafe_cron_blockage_suppressor handler (Plan 00298)
    # ------------------------------------------------------------------

    #: A delivered failsafe-cron tick suppressed by a still-valid
    #: blocked-only-on-human-input marker.
    FAILSAFE_CRON_SUPPRESSED: str = "R-FAILSAFE-CRON-SUPPRESSED"
