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
