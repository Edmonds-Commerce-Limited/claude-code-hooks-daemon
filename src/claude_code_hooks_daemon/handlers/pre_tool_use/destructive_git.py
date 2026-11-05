"""DestructiveGitHandler - blocks destructive git commands that permanently destroy data."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.branch_cleanup import preview_paths, worktree_blockers
from claude_code_hooks_daemon.core.evacuation import (
    Evacuation,
    EvacuationMatch,
    destroys_recorded,
    evacuate_then_destroy,
)
from claude_code_hooks_daemon.core.evacuation_turns import recorded_evacuations
from claude_code_hooks_daemon.core.force_removal import (
    ALL_HOLDERS,
    REMOTE_HOLDERS,
    ContainmentUnknown,
    lost_commit_count,
    uncontained_tips,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.daemon.branch_safety import matches_any_glob
from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_INVOCATION,
    SUBCOMMAND_SEPARATOR_CHARS,
    remove_word_quoting,
)
from claude_code_hooks_daemon.utils.command_position import command_position_argument_segments
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, branch_ref, run_git
from claude_code_hooks_daemon.utils.git_sync import resolve_default_branch
from claude_code_hooks_daemon.utils.path_predicates import path_is_dir

logger = logging.getLogger(__name__)

# Generic reason used when a destructive pattern matches but warrants no
# command-specific explanation (e.g. bare `git checkout .`).
_GENERIC_DESTRUCTIVE_REASON = "This git command destroys uncommitted changes permanently"

# Git accepts GLOBAL OPTIONS between `git` and the subcommand -- `-C <path>`,
# `-c <k>=<v>`, `--git-dir=<path>`, `--work-tree=<path>`, `--no-pager`, and more.
# Every pattern below must tolerate them. Anchoring on a bare `\bgit\s+<sub>`
# made ONE inserted token silently disable the whole handler:
#
#     git reset --hard origin/main            -> denied
#     git -C /path reset --hard origin/main   -> ALLOWED
#
# The same insertion bypassed clean -f, push --force, stash drop and the rest.
# `--git-dir=/repo/.git reset --hard` looked covered, but only by accident: the
# path ends in `.git`, so `\bgit` matched INSIDE THE PATH and `\s+reset` matched
# right after it. Aim it at a directory not ending in `.git` and the block
# disappeared -- so the near-miss also hid how broad the hole was.
#
# GIT_INVOCATION is SHARED (utils.command_evasion) rather than defined here:
# git_stash and sensitive_content had the identical defect, and a fix that lives
# in one handler cannot reach the others. See
# tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py.
_SUBCOMMAND_SEPARATOR_CHARS = SUBCOMMAND_SEPARATOR_CHARS
_GIT_INVOCATION = GIT_INVOCATION

# Force-push detection, scoped to the `git push` sub-command segment.
# The negated class consumes only characters within the push segment (never a
# command separator), so a non-push `--force` later in a compound command —
# e.g. `git push origin main; git worktree remove <path> --force` — is NOT
# matched. A NEWLINE is one of those separators (Plan 00406): the same pair
# written on two lines was matched, so `git push origin main` followed by
# `grep -f patterns.txt notes.txt` was denied on grep's `-f`.
#
# EVERY alternative below guards its leading position with `(?<!\S)`, so each
# must START a whitespace-delimited token rather than merely appear inside one.
# The refspec branch has done this since Plan 00205; the flag branches did not,
# and GitHub issue #37 is what that cost: `-f` inside `lane-f-adoption` matched,
# because the `f` is followed by `-` and that counts as a word boundary. An
# ordinary push was denied purely for its branch NAME.
#
# The two flag syntaxes need DIFFERENT rules, which is why they are separate
# alternatives rather than one group behind a shared guard:
#
#   - a LONG option is forceful only when it is exactly `--force` or
#     `--force-with-lease`. Matching a prefix would catch `--follow-tags`, and
#     dropping the leading guard would catch `--no-force-with-lease`, which
#     NEGATES the lease.
#   - a SHORT cluster is any single-dash token containing `f`, whatever else
#     rides along with it. Git groups short options — `git push -nq <remote>`
#     is accepted by its own parser, failing on the remote rather than on an
#     unknown switch — so `-uf`, `-fu` and `-nf` are all real force pushes.
#     Requiring the literal `-f` missed every one of them: that substring does
#     not occur in `-uf` at all, and in `-fu` the `f` is followed by a word
#     character so a trailing `\b` fails. `(?!-)` keeps this branch off long
#     options, leaving those to the rule above.
#   - a `+`-prefixed REFSPEC (Plan 00205): `git push origin +main:main` forces
#     the update exactly like `--force` and needs no flag at all, so a branch
#     name that merely CONTAINS `+` (`feature+fix`) is never matched.
_GIT_PUSH_FORCE_PATTERN = (
    rf"{_GIT_INVOCATION}push\b[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
    r"(?:(?<!\S)--force(?:-with-lease)?\b"
    r"|(?<!\S)-(?!-)[A-Za-z0-9]*f[A-Za-z0-9]*\b"
    r"|(?<!\S)\+\S)"
)

# Remote ref deletion (Plan 00483 Task 2.2, owner ruling A6), scoped to the `git push`
# segment exactly like the force-push pattern above, and with the same token rule:
# every marker must START a whitespace-delimited argument. Three spellings delete a
# ref on the remote:
#
#   - `--delete`, exactly (never a prefix, so a branch NAME like `my-delete-branch`
#     is untouched);
#   - a SHORT cluster containing `d` (`-d`, `-ud`), because git groups short
#     options, mirroring the force-push cluster branch;
#   - a refspec with an EMPTY source, `:<name>` -- no flag at all, one key away
#     from the `+<name>` force refspec. `main:feature` and `HEAD:refs/heads/x`
#     have a source and are ordinary pushes.
#
# `--mirror` and `--prune` delete remote refs too (the remote is made to match
# the local refs, dropping the rest), so they are the same human-only act. They
# are never in `_PUSH_LONG_FLAGS`: the merged-branch allowance cannot read what
# they delete, so they stay denied.
#
# Deleting a LOCAL ref (`git tag -d`, `git branch -d`) is a different command and a
# different pattern; the owner ruled `git tag -d` allowed.
_DELETE_LONG: Final[str] = "--delete"
_DELETE_LETTER: Final[str] = "d"
_REF_DROPPING_LONG_FLAGS: Final[tuple[str, ...]] = ("--mirror", "--prune")
_PUSH_DELETE_LONG_ALTERNATIVES = "|".join(
    re.escape(flag) for flag in (_DELETE_LONG, *_REF_DROPPING_LONG_FLAGS)
)
_GIT_PUSH_DELETE_PATTERN = (
    rf"{_GIT_INVOCATION}push\b[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
    rf"(?:(?<!\S)(?:{_PUSH_DELETE_LONG_ALTERNATIVES})(?!\S)"
    rf"|(?<!\S)-(?!-)[A-Za-z0-9]*{_DELETE_LETTER}[A-Za-z0-9]*(?!\S)"
    r"|(?<!\S):[^\s:]\S*)"
)

# SINGLE SOURCE OF TRUTH: ordered (pattern, reason) pairs consumed by BOTH matches()
# and handle(). Order matters — handle() returns the reason of the FIRST matching
# pattern, exactly mirroring matches()' first-hit semantics. Keeping one ordered
# list prevents the pattern source from drifting between the two methods.
_DESTRUCTIVE_PATTERN_REASONS: tuple[tuple[str, str], ...] = (
    (
        rf"{_GIT_INVOCATION}reset\s+.*--hard\b",
        "git reset --hard destroys all uncommitted changes permanently",
    ),
    (
        # The force flag must START a whitespace-delimited token: `-f` inside the
        # operand `build-final/` is a directory name, not the flag.
        rf"{_GIT_INVOCATION}clean\s+(?:.*\s)?(?:--force\b|-(?!-)[a-z]*f)",
        "git clean -f permanently deletes untracked files",
    ),
    # Bare `git checkout .` discards working-tree changes; generic reason suffices.
    (
        rf"{_GIT_INVOCATION}checkout\s+\.\s*(?:$|;|&&|\|)",
        _GENERIC_DESTRUCTIVE_REASON,
    ),
    # Match all variants of checkout with -- and a file:
    # git checkout -- file / git checkout HEAD -- file / git checkout main -- file
    (
        rf"{_GIT_INVOCATION}checkout\s+(?:.*\s)?--\s+\S",
        "git checkout [REF] -- file discards all local changes to that file permanently",
    ),
    # git restore with file paths discards working-tree changes.
    # Does NOT match the staged-only forms (safe - they only unstage), wherever
    # the flag sits and whatever else rides along (`--source=<tree>`):
    #   git restore --staged file.txt   (long flag)
    #   git restore -S file.txt          (short flag, equivalent to --staged)
    # `--staged --worktree` (`-SW`) restores the working tree too, so it matches.
    # The short letters are case-SENSITIVE: `-s` is `--source`, not `-S`.
    (
        rf"{_GIT_INVOCATION}restore\s+"
        r"(?!(?=.*(?<!\S)(?:--staged|-(?!-)(?-i:[A-Za-z]*S[A-Za-z]*))(?!\S))"
        r"(?!.*(?<!\S)(?:--worktree|-(?!-)(?-i:[A-Za-z]*W[A-Za-z]*))(?!\S)))"
        r".*\S",
        "git restore discards all local changes to files permanently",
    ),
    (
        rf"{_GIT_INVOCATION}stash\s+drop\b",
        "git stash drop permanently destroys stashed changes",
    ),
    (
        rf"{_GIT_INVOCATION}stash\s+clear\b",
        "git stash clear permanently destroys all stashed changes",
    ),
    (
        _GIT_PUSH_FORCE_PATTERN,
        "git push --force can overwrite remote history and destroy team members' work",
    ),
    # Force branch deletion bypasses merge check. (?-i:) matches only uppercase -D
    # (lowercase -d is safe, it checks merge status).
    (
        rf"{_GIT_INVOCATION}branch\s+.*(?-i:-D)\b",
        "git branch -D force-deletes a branch without checking if it has been merged",
    ),
    # Plan 00205: `git update-ref -d refs/heads/<name>` is the plumbing
    # equivalent of `git branch -D` — same force delete, no merge check, no
    # flag an agent would recognise as "the dangerous one". Scoped to `-d`
    # with a `refs/heads/` target (PLAN.md Risks & Mitigations): creating or
    # moving a ref (no `-d`), and deleting a non-branch ref (e.g.
    # `refs/remotes/...`), stay untouched.
    #
    # `[^;&|<newline>]*?` for the same reason as the push-force sibling above: a
    # `.*` spans a separator, so `git update-ref refs/heads/backup HEAD; echo -d
    # refs/heads/backup` — a ref CREATE plus unrelated text — was denied under
    # a rule neither statement matches. The separator set includes the newline
    # (Plan 00406), because the same pair written on two LINES was denied too.
    #
    # The gap after `update-ref` is horizontal-only for a separate reason:
    # `\s` matches a newline, so `\s+` would step over the end of this command
    # even once the class stops it, and `git update-ref` ⏎ `-d refs/heads/x`
    # would read as one call. A continuation cannot be lost this way — it is
    # already normalised away before any pattern here runs.
    (
        rf"{_GIT_INVOCATION}update-ref[ \t]+[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
        rf"-d[ \t]+refs/heads/\S+",
        "git update-ref -d refs/heads/<name> force-deletes a branch ref with no "
        "merge check — the plumbing equivalent of git branch -D",
    ),
    # `git branch -d --force` / `--delete --force` / `-fd` are `-D` spelled as two
    # options, in either order: the same force delete with no merge check. Each
    # lookahead needs a whole token, so a branch NAME ending in `-f` or `-d`
    # never counts, and the class stops at a command separator.
    (
        rf"{_GIT_INVOCATION}branch(?=[ \t])"
        rf"(?=[^{_SUBCOMMAND_SEPARATOR_CHARS}]*(?<!\S)(?:--delete|-[A-Za-z]*d[A-Za-z]*)(?!\S))"
        rf"(?=[^{_SUBCOMMAND_SEPARATOR_CHARS}]*(?<!\S)(?:--force|-[A-Za-z]*f[A-Za-z]*)(?!\S))",
        "git branch -d --force force-deletes a branch without checking if it has been "
        "merged — the same delete as git branch -D",
    ),
    (
        rf"{_GIT_INVOCATION}commit\s+.*--amend\b",
        "git commit --amend rewrites the previous commit, creating messy history "
        "and potential data loss — create a new commit instead",
    ),
    # Plan 00412 class 6. `git checkout -- <file>` above is already denied, so
    # discarding the working tree is judged worth guarding; `-f` reaches the
    # same outcome and names no file at all.
    #
    # The force test mirrors the push-force sibling deliberately rather than
    # re-deriving it: exact `--force` (never a prefix, so `--force-with-lease`
    # and a hypothetical `--foo` stay out) or a short cluster containing `f`,
    # because git groups short options. The negated class stops at a command
    # separator so a later unrelated `-f` -- `git status && grep -f patterns
    # notes` -- is not swept in.
    (
        rf"{_GIT_INVOCATION}checkout[ \t]+[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
        r"(?:(?<!\S)--force(?!-)\b|(?<!\S)-(?!-)[A-Za-z0-9]*f[A-Za-z0-9]*\b)",
        "git checkout -f discards every uncommitted change in the working tree",
    ),
    (
        rf"{_GIT_INVOCATION}switch[ \t]+[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
        # `force(?!-)` mirrors the checkout sibling above: exact `--force`,
        # never a prefix. Without the negative lookahead, `\b` matches
        # mid-token and `--force-create` (the long spelling of `-C`, which
        # resets a branch ref and cannot discard uncommitted changes — git
        # refuses it when that would happen) was denied for a loss it cannot
        # cause.
        r"(?:(?<!\S)--(?:force(?!-)|discard-changes)\b"
        r"|(?<!\S)-(?!-)[A-Za-z0-9]*f[A-Za-z0-9]*\b)",
        "git switch -f/--discard-changes discards every uncommitted change — the "
        "`switch` spelling of the same loss `git checkout -f` causes",
    ),
    # `=now` is load-bearing, not decoration: expiring entries older than ninety
    # days is routine housekeeping, and only `now` cuts the net that this
    # handler's OWN acceptance test leans on when it justifies a decision with
    # "recoverable via reflog".
    (
        rf"{_GIT_INVOCATION}reflog[ \t]+expire[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?"
        r"--expire(?:-unreachable)?=now\b",
        "git reflog expire --expire=now destroys the reflog, which is the recovery "
        "route every other rule in this handler assumes is still there",
    ),
    (
        rf"{_GIT_INVOCATION}gc[ \t]+[^{_SUBCOMMAND_SEPARATOR_CHARS}]*?--prune=now\b",
        "git gc --prune=now drops unreachable objects immediately, making anything "
        "only the reflog still referenced unrecoverable",
    ),
    (
        rf"{_GIT_INVOCATION}filter-(?:branch|repo)\b",
        "git filter-branch/filter-repo rewrites every commit in the history",
    ),
    (
        _GIT_PUSH_DELETE_PATTERN,
        "git push --delete (or a `:<name>` refspec) deletes a branch or tag on the remote, "
        "in the shared repository",
    ),
    # Forced or not: git deletes a worktree's ignored files either way (Plan 00558
    # section 11), so every removal is judged and a lossless one is allowed.
    (
        rf"{_GIT_INVOCATION}worktree[ \t]+remove\b",
        "git worktree remove deletes the worktree's ignored files, and with --force its "
        "modified and untracked files and any commit only its HEAD holds",
    ),
)

# Parallel, index-aligned RuleID for each entry in _DESTRUCTIVE_PATTERN_REASONS
# (Plan 00116, Decision B: per-rule granularity). The bare `git checkout .` and
# `git checkout -- file` patterns (indices 2 and 3) share one rule -- both are
# "discards local changes"; every other pattern maps 1:1 to its own rule.
_PATTERN_RULE_IDS: tuple[str, ...] = (
    RuleID.GIT_RESET_HARD,
    RuleID.GIT_CLEAN_FORCE,
    RuleID.GIT_CHECKOUT_DISCARD,
    RuleID.GIT_CHECKOUT_DISCARD,
    RuleID.GIT_RESTORE,
    RuleID.GIT_STASH_DROP,
    RuleID.GIT_STASH_CLEAR,
    RuleID.GIT_PUSH_FORCE,
    RuleID.GIT_BRANCH_FORCE_DELETE,
    RuleID.GIT_BRANCH_FORCE_DELETE,  # git update-ref -d refs/heads/<name> (Plan 00205)
    RuleID.GIT_BRANCH_FORCE_DELETE,  # git branch -d --force, the two-option spelling of -D
    RuleID.GIT_COMMIT_AMEND,
    RuleID.GIT_CHECKOUT_FORCE,
    RuleID.GIT_SWITCH_FORCE,
    RuleID.GIT_REFLOG_EXPIRE,
    RuleID.GIT_GC_PRUNE_NOW,
    RuleID.GIT_FILTER_HISTORY,
    RuleID.GIT_PUSH_DELETE_REMOTE,
    RuleID.GIT_WORKTREE_REMOVE_FORCE,
)

# Shared teaching content appended after the rule-specific "why" in every
# verbose block (Plan 00116, Task 3.2: preserves the boilerplate previously
# emitted by the old count-driven `_verbose_reason` ladder).
_SAFE_ALTERNATIVES_BLOCK = (
    "This command PERMANENTLY DESTROYS data with NO recovery possible.\n\n"
    "If this operation is truly necessary, you must ask the human user to run it manually.\n\n"
    "SAFE alternatives:\n"
    "  - git stash        (save changes, can recover later)\n"
    "  - git diff         (review changes first)\n"
    "  - git status       (see what would be affected)\n"
    "  - git commit       (save changes permanently first)\n\n"
    "The LLM is NOT ALLOWED to run destructive git commands. Ask the user to do it."
)


def _verbose_content(why: str) -> str:
    """Build the full first-fire teaching content for a rule from its "why"."""
    return f"{why}.\n\n{_SAFE_ALTERNATIVES_BLOCK}"


# A forced branch delete cannot lose a commit a remote-tracking ref already
# reaches, so clearing up such a branch needs no human. The teaching for that
# rule therefore says how to get there, not that the LLM may not.
_BRANCH_DELETE_VERBOSE: Final[str] = (
    "A forced branch delete skips git's merge check, so a branch whose tip no other ref "
    "holds would lose its commits with no recovery.\n\n"
    "It is ALLOWED when every named branch's tip is reachable from a ref that survives the "
    "command: another local branch, a tag or a remote-tracking ref (refs the same command "
    "deletes do not count), judged in the repository the command runs in (`git -C <dir>` "
    "and a `cd` in the same command are honoured). Anything the check cannot establish is "
    "denied. With `branches.force_removal.mode: off` only remote-tracking refs count.\n\n"
    "To proceed: push each branch named below (`git push -u origin <name>`) or merge it, "
    "then retry. `git branch -d` (lowercase) remains the merge-checked delete."
)
_WORKTREE_REMOVE_VERBOSE: Final[str] = (
    "`git worktree remove` deletes the worktree directory. Even without `--force` git "
    "deletes its IGNORED files (scratch notes, reports, patches), and `--force` also "
    "deletes modified and untracked files. Forced or not, a clean worktree on a detached "
    "HEAD is removed too, and any commit that only that HEAD holds is orphaned.\n\n"
    "It is ALLOWED when nothing would be lost: `git status --porcelain` is empty (forced "
    "form), every ignored entry matches a `branches.cleanup_after_merge.regenerable` glob "
    "(`untracked/scratch/` never does), and the HEAD is held by a branch, tag "
    "or remote-tracking ref the same command does not delete.\n\n"
    "To proceed: commit or push the work on the lane's branch, move each listed path to a "
    "tracked home, or delete it deliberately, then retry. Ask a human if none of those fits."
)
# A remote ref deletion removes the ref from the SHARED repository, where this
# checkout's reflog cannot bring it back and other people may be working from it.
# Owner ruling A6: a human runs it; ruling D11 (niggle N362) carves out ONE lossless case --
# a branch whose remote tip is already merged into the default branch. Tags stay human-only.
_PUSH_DELETE_VERBOSE: Final[str] = (
    "This command deletes a branch or tag on the REMOTE repository. Other people and other "
    "machines share that ref, and nothing in this checkout (reflog included) restores it.\n\n"
    "It is ALLOWED when every named branch's remote-tracking ref is already merged into the "
    "default branch or an integration line (`branches.integration_lines`; one "
    "`git for-each-ref --merged` per target) AND `git ls-remote` shows the remote's live tip "
    "equal to it (a stale tracking ref is denied: run `git fetch` and retry), judged in the "
    "repository the command runs in; nothing is lost then. An integration line itself is "
    "judged against the DEFAULT branch only (merged into another line does not count). "
    "Tags, the default branch, an exempt or protected name (`branches.exempt`, "
    "`branches.protected_names`), an unmerged branch (an integration line not yet merged "
    "into the default branch included) and anything the check cannot establish are "
    "denied.\n\n"
    "Otherwise do not run it, and do not look for another spelling of it. Stop and ask the "
    "human to run it themselves: tell them the remote, the ref and why it should go.\n\n"
    "Local clean-up is not affected: `git tag -d <tag>` and `git branch -d <name>` only touch "
    "this checkout and are allowed."
)
_EVACUATE_VERBOSE: Final[str] = (
    "This command writes a worktree's or branch's work out to a file no repository tracks "
    "(a patch, a diff, a `tee` copy) and then destroys the worktree or branch it came from. "
    "History, review and the branch's remote copy are traded for one loose file that nothing "
    "checks and the next clean-up deletes.\n\n"
    "To proceed: commit the work on the lane's branch and push it (or merge it), then remove "
    "the worktree or branch in its own command. If the work should not be kept, ask a human "
    "to remove it. `branches.evacuation.mode` is `block`, `warn` or `off`."
)
_VERBOSE_OVERRIDES: Final[dict[str, str]] = {
    RuleID.GIT_EVACUATE_THEN_DESTROY: _EVACUATE_VERBOSE,
    RuleID.GIT_BRANCH_FORCE_DELETE: _BRANCH_DELETE_VERBOSE,
    RuleID.GIT_PUSH_DELETE_REMOTE: _PUSH_DELETE_VERBOSE,
    RuleID.GIT_WORKTREE_REMOVE_FORCE: _WORKTREE_REMOVE_VERBOSE,
}


#: Rules with a lossless case: allowed when the containment proof passes (section 11).
_LOSSLESS_WHEN_PROVEN: Final[frozenset[str]] = frozenset(
    {RuleID.GIT_BRANCH_FORCE_DELETE, RuleID.GIT_WORKTREE_REMOVE_FORCE}
)
_MODE_OFF: Final[str] = "off"
_MODE_WARN: Final[str] = "warn"


class _Unverifiable(Exception):
    """A forced branch delete whose target this handler cannot establish."""


_BRANCH: Final[str] = "branch"
_UPDATE_REF: Final[str] = "update-ref"
_OPTIONS_END: Final[str] = "--"
# `git branch` flags a forced delete may carry. Anything else (`-r` deletes a
# remote-tracking ref, for one) changes what is deleted, so it is unverifiable.
_BRANCH_FLAG_LETTERS: Final[frozenset[str]] = frozenset("dDfq")
_BRANCH_LONG_FLAGS: Final[frozenset[str]] = frozenset({_DELETE_LONG, "--force", "--quiet"})
# A branch name that is safe to hand to git as one argument: no expansion,
# quoting or option-looking characters survive it.
_LITERAL_BRANCH_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._/+@-]+")
# Command and process substitution can run a git command this reading never sees.
_SUBSTITUTION: Final[re.Pattern[str]] = re.compile(r"\$\(|`|[<>]\(")
_UNVERIFIED_ADVICE: Final[str] = (
    "Name each branch literally, push it first (`git push -u origin <name>`), then retry."
)


def _forced_branch_names(run: GitInvocation) -> list[str] | None:
    """The branches ``git branch`` force-deletes, or None when ``run`` does not."""
    delete = force = False
    unknown: list[str] = []
    names: list[str] = []
    options_ended = False
    for argument in run.arguments:
        if options_ended or not argument.startswith("-"):
            names.append(argument)
        elif argument == _OPTIONS_END:
            options_ended = True
        elif argument.startswith("--"):
            delete = delete or argument == _DELETE_LONG
            force = force or argument == "--force"
            if argument not in _BRANCH_LONG_FLAGS:
                unknown.append(argument)
        else:
            letters = set(argument[1:])
            delete = delete or bool(letters & {_DELETE_LETTER, "D"})
            force = force or bool(letters & {"f", "D"})
            if not letters <= _BRANCH_FLAG_LETTERS:
                unknown.append(argument)
    if not (delete and force):
        return None
    if unknown:
        raise _Unverifiable(f"`{unknown[0]}` changes what `git branch` deletes")
    return names


def _update_ref_branch_names(run: GitInvocation) -> list[str] | None:
    """The branches ``git update-ref -d`` deletes, or None when ``run`` deletes none."""
    if "-d" not in run.arguments:
        return None
    if "--stdin" in run.arguments:
        raise _Unverifiable("`--stdin` names its refs where this handler cannot read them")
    return [
        argument.removeprefix(HEADS_PREFIX)
        for argument in run.arguments
        if argument.startswith(HEADS_PREFIX)
    ] or None


def _deleted_branches(command: str) -> list[tuple[GitInvocation, list[str]]]:
    """Every forced branch deletion in ``command``, with the invocation that makes it."""
    deletions: list[tuple[GitInvocation, list[str]]] = []
    for run in git_invocations(command):
        if run.subcommand == _BRANCH:
            names = _forced_branch_names(run)
        elif run.subcommand == _UPDATE_REF:
            names = _update_ref_branch_names(run)
        else:
            continue
        if names is not None:
            deletions.append((run, names))
    return deletions


_WORKTREE: Final[str] = "worktree"
_REMOVE: Final[str] = "remove"
_FORCE_LETTER: Final[str] = "f"


@dataclass(frozen=True)
class _WorktreeRemoval:
    """One ``git worktree remove``: the invocation, the path it names, and whether forced."""

    run: GitInvocation
    path: str
    forced: bool


def _worktree_removals(command: str) -> list[_WorktreeRemoval]:
    """Every ``git worktree remove`` in ``command``.

    Raises:
        _Unverifiable: When an option this reading does not know, or other than one
            path, could change what is removed.
    """
    removals: list[_WorktreeRemoval] = []
    for run in git_invocations(command):
        if run.subcommand != _WORKTREE or run.arguments[:1] != (_REMOVE,):
            continue
        forced = options_ended = False
        paths: list[str] = []
        for argument in run.arguments[1:]:
            if options_ended or not argument.startswith("-"):
                paths.append(argument)
            elif argument == _OPTIONS_END:
                options_ended = True
            elif argument == "--force" or (
                not argument.startswith("--") and set(argument[1:]) == {_FORCE_LETTER}
            ):
                forced = True
            else:
                raise _Unverifiable(f"`{argument}` changes what `git worktree remove` removes")
        if len(paths) != 1:
            raise _Unverifiable("`git worktree remove` must name exactly one worktree")
        removals.append(_WorktreeRemoval(run=run, path=paths[0], forced=forced))
    return removals


@dataclass
class _HeldTip:
    """A commit a deletion leaves to the refs that survive it."""

    label: str
    rule_id: str
    directory: Path
    tip: str | None
    advice: str


def _git_line(directory: Path, *args: str) -> str | None:
    """The trimmed stdout of one git call, or None when it fails or prints nothing."""
    result = run_git(directory, *args, timeout=Timeout.GIT_CONTEXT)
    line = result.stdout.strip()
    return line if result.returncode == 0 and line else None


def _commit_of(directory: Path, revision: str) -> str | None:
    return _git_line(directory, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")


def _common_dir(directory: Path) -> str | None:
    """The repository ``directory`` belongs to, shared by all of its worktrees."""
    return _git_line(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")


def _unverified(reason: str) -> str:
    return f"This delete could not be verified as safe: {reason}. {_UNVERIFIED_ADVICE}"


def _with_principle(note: str) -> str:
    return f"{note}\n\n{BRANCH_LIMIT_PRINCIPLE}"


def _lost_phrase(count: int | None) -> str:
    if count is None:
        return "an unknown number of commits"
    return f"{count} commit" + ("" if count == 1 else "s")


class _ForceRemovalJudge:
    """Judges every forced branch delete and worktree removal in one command as a whole."""

    def __init__(self, cwd: Path, branches: BranchesConfig) -> None:
        self._cwd = cwd
        self._branches = branches
        self._judge_worktrees = branches.force_removal.mode != _MODE_OFF
        self._namespaces = ALL_HOLDERS if self._judge_worktrees else REMOTE_HOLDERS
        self._held: dict[str, list[_HeldTip]] = {}
        self._excluded: dict[str, set[str]] = {}
        self._unheld: list[_HeldTip] = []
        self._worktree_losses: list[str] = []

    def _place(self, run: GitInvocation) -> Path:
        problem = placement_problem(run, self._cwd)
        if problem is not None:
            raise _Unverifiable(problem)
        directory = invocation_directory(run, self._cwd)
        if not path_is_dir(directory, unreadable_means=False):
            raise _Unverifiable(f"`{directory}` is not a directory")
        return directory

    def _hold(self, held: _HeldTip) -> None:
        """Queue ``held`` for the containment proof of its repository."""
        repository = _common_dir(held.directory) if held.tip is not None else None
        if repository is None:
            self._unheld.append(held)
            return
        self._held.setdefault(repository, []).append(held)

    def _add_deletions(self, deletions: list[tuple[GitInvocation, list[str]]]) -> None:
        for run, names in deletions:
            directory = self._place(run)
            if not names:
                raise _Unverifiable("it names no branch")
            where = "" if directory == self._cwd else f"-C {directory} "
            for name in names:
                if not _LITERAL_BRANCH_NAME.fullmatch(name):
                    raise _Unverifiable(f"`{name}` is not a literal branch name")
                repository = _common_dir(directory)
                if repository is not None:
                    self._excluded.setdefault(repository, set()).add(branch_ref(name))
                self._hold(
                    _HeldTip(
                        label=f"`{name}`",
                        rule_id=RuleID.GIT_BRANCH_FORCE_DELETE,
                        directory=directory,
                        tip=_commit_of(directory, branch_ref(name)),
                        advice=f"push it: `git {where}push -u origin {name}`",
                    )
                )

    def _add_removal(self, removal: _WorktreeRemoval) -> None:
        path = self._place(removal.run) / Path(removal.path).expanduser()
        if not path_is_dir(path, unreadable_means=False):
            raise _Unverifiable(f"worktree `{path}` is not a directory")
        blockers = worktree_blockers(path, self._branches.cleanup_after_merge.regenerable)
        if blockers:
            self._worktree_losses.append(
                f"worktree `{path}` holds {len(blockers)} path(s) the removal would lose: "
                f"{preview_paths(blockers)}"
            )
        # Forced or not: a clean detached worktree is removed by plain git too, and its
        # HEAD commits then survive only if some ref holds them.
        self._hold(
            _HeldTip(
                label=f"worktree `{path}` HEAD",
                rule_id=RuleID.GIT_WORKTREE_REMOVE_FORCE,
                directory=path,
                tip=_commit_of(path, "HEAD"),
                advice=f"commit it to a branch: `git -C {path} switch -c <name>`, then push",
            )
        )

    def _prove(self) -> None:
        """Move every held tip no surviving ref contains onto ``_unheld``."""
        for repository, held in self._held.items():
            excluded = self._excluded.get(repository, set())
            tips = [h.tip for h in held if h.tip is not None]
            try:
                stranded = uncontained_tips(held[0].directory, tips, excluded, self._namespaces)
            except ContainmentUnknown as exc:
                labels = ", ".join(h.label for h in held)
                raise _Unverifiable(f"what holds {labels} could not be read ({exc})") from exc
            self._unheld.extend(h for h in held if h.tip in stranded)

    def _describe(self, held: _HeldTip) -> str:
        if held.tip is None:
            return f"{held.label} (its tip could not be read)"
        repository = _common_dir(held.directory) or ""
        count = lost_commit_count(
            held.directory, held.tip, self._excluded.get(repository, set()), self._namespaces
        )
        return f"{held.label} ({held.advice}) would lose {_lost_phrase(count)}"

    def judge(self, command: str) -> tuple[str, str] | None:
        """None when nothing would be lost, else the rule that denies and why."""
        deletions = _deleted_branches(command)
        removals = _worktree_removals(command) if self._judge_worktrees else []
        if not deletions and not removals:
            if self._judge_worktrees or not _worktree_removals(command):
                raise _Unverifiable("no forced branch delete or worktree removal could be read")
            return None
        self._add_deletions(deletions)
        for removal in removals:
            self._add_removal(removal)
        self._prove()
        losses = [*self._worktree_losses, *(self._describe(h) for h in self._unheld)]
        if not losses:
            return None
        worktree_rule = self._worktree_losses or any(
            h.rule_id == RuleID.GIT_WORKTREE_REMOVE_FORCE for h in self._unheld
        )
        rule_id = (
            RuleID.GIT_WORKTREE_REMOVE_FORCE if worktree_rule else RuleID.GIT_BRANCH_FORCE_DELETE
        )
        note = (
            "Not removed: nothing that survives this command (another branch, a tag, a "
            "remote-tracking ref) holds this work, or it could not be checked, so it would be "
            "lost: " + "; ".join(losses) + ". Push or merge each branch, commit or move each "
            "path, then retry."
        )
        return rule_id, _with_principle(note)


def _force_removal_note(
    command: str, cwd: Path, branches: BranchesConfig, fallback_rule: str
) -> tuple[str, str] | None:
    """None when every forced deletion and worktree removal loses nothing, else (rule, why)."""
    if _SUBSTITUTION.search(command):
        return fallback_rule, _with_principle(
            _unverified("a command or process substitution can run a delete this reading misses")
        )
    try:
        return _ForceRemovalJudge(cwd, branches).judge(command)
    except _Unverifiable as exc:
        return fallback_rule, _with_principle(_unverified(str(exc)))


_PUSH: Final[str] = "push"
_REMOTES_PREFIX: Final[str] = "refs/remotes/"
_TAGS_PREFIX: Final[str] = "refs/tags/"
# `git push` flags a remote delete may carry without changing WHAT it deletes. Anything
# else (`--repo`, `-o`, `--receive-pack`, ...) can redirect or reshape the push, so a
# command using one is unverifiable.
_PUSH_FLAG_LETTERS: Final[frozenset[str]] = frozenset({_DELETE_LETTER, *"qvnu"})
_PUSH_LONG_FLAGS: Final[frozenset[str]] = frozenset(
    {_DELETE_LONG, "--quiet", "--verbose", "--dry-run", "--no-verify", "--set-upstream"}
)
_REFSPEC_SEPARATOR: Final[str] = ":"
# Branch patterns per `git ls-remote` call. One call per remote is the aim; this only
# bounds the argv (Linux caps one argument at 128 KiB and the whole argv near 2 MiB), and
# 500 names of ~100 bytes stay far below both while a realistic delete is a single call.
_LS_REMOTE_CHUNK: Final[int] = 500


def _remote_delete_targets(run: GitInvocation) -> tuple[str, list[str]] | None:
    """The ``(remote, refs)`` a ``git push`` deletes, or None when ``run`` deletes none.

    A ref is what follows ``--delete`` or an empty-source ``:`` refspec. Refspecs that
    have a source are ordinary pushes and are not judged here.

    Raises:
        _Unverifiable: When a flag changes what the push does, or no remote is named.
    """
    delete = False
    positional: list[str] = []
    options_ended = False
    for argument in run.arguments:
        if options_ended or not argument.startswith("-"):
            positional.append(argument)
        elif argument == _OPTIONS_END:
            options_ended = True
        elif argument.startswith("--"):
            delete = delete or argument == _DELETE_LONG
            if argument not in _PUSH_LONG_FLAGS:
                raise _Unverifiable(f"`{argument}` changes what `git push` does")
        else:
            letters = set(argument[1:])
            delete = delete or _DELETE_LETTER in letters
            if not letters <= _PUSH_FLAG_LETTERS:
                raise _Unverifiable(f"`{argument}` changes what `git push` does")
    refspecs = positional[1:]
    if delete:
        refs = refspecs
    else:
        refs = [
            spec[1:]
            for spec in refspecs
            if spec.startswith(_REFSPEC_SEPARATOR) and len(spec) > len(_REFSPEC_SEPARATOR)
        ]
    if not refs:
        return None
    if not positional:
        raise _Unverifiable("it names no remote")
    return positional[0], refs


def _branch_name(ref: str) -> str:
    """The branch name a delete ``ref`` (``name`` or ``refs/heads/name``) refers to."""
    return ref.removeprefix(HEADS_PREFIX)


def _refusal(name: str, default: str, branches: BranchesConfig) -> str | None:
    """Why ``name`` may never be deleted remotely by an agent, whatever the proof."""
    if name == default:
        return f"`{name}` is the default branch"
    if matches_any_glob(name, branches.exempt):
        return f"`{name}` is exempt (`branches.exempt`)"
    if matches_any_glob(name, branches.protected_names):
        return f"`{name}` is a protected name (`branches.protected_names`)"
    return None


def _named_ref_problem(remote: str, ref: str, default: str, branches: BranchesConfig) -> str | None:
    """Why ``ref`` cannot be judged or is refused outright, before any git runs."""
    name = _branch_name(ref)
    if not _LITERAL_BRANCH_NAME.fullmatch(remote):
        return f"`{remote}` is not a literal remote name"
    if name.startswith(_TAGS_PREFIX) or not _LITERAL_BRANCH_NAME.fullmatch(name):
        return f"`{ref}` is not a literal branch name (tags are never deleted by an agent)"
    return _refusal(name, default, branches)


_REF_FORMAT: Final[str] = "--format=%(objectname) %(objecttype) %(refname)"


def _listed_refs(directory: Path, patterns: list[str]) -> dict[str, tuple[str, str]] | None:
    """Map refname to ``(object, type)`` for every ref matching ``patterns``, in one call.

    Keyed by the exact refname, so a pattern that also matches a longer ref never
    lends it to another name. None when git fails or times out.
    """
    listing = run_git(
        directory, "for-each-ref", _REF_FORMAT, *patterns, timeout=Timeout.GIT_CONTEXT
    )
    if listing.returncode != 0:
        return None
    refs: dict[str, tuple[str, str]] = {}
    for line in listing.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            refs[parts[2]] = (parts[0], parts[1])
    return refs


def _merged_into(directory: Path, target: str, refnames: list[str]) -> set[str] | None:
    """Which of ``refnames`` are ancestors of ``target``: one ``for-each-ref --merged``.

    None when git fails or times out.
    """
    merged = run_git(
        directory,
        "for-each-ref",
        f"--merged={target}",
        "--format=%(refname)",
        *refnames,
        timeout=Timeout.GIT_CONTEXT,
    )
    if merged.returncode != 0:
        return None
    return set(merged.stdout.splitlines())


def _default_proof_targets(
    remote: str, default: str, refs: dict[str, tuple[str, str]]
) -> list[str]:
    """The existing default-branch refs: the only proof an integration line accepts."""
    tracking_prefix = f"{_REMOTES_PREFIX}{remote}/"
    return [
        ref
        for ref in (f"{tracking_prefix}{default}", branch_ref(default))
        if ref in refs and refs[ref][1] == "commit"
    ]


def _proof_targets(
    remote: str, default: str, branches: BranchesConfig, refs: dict[str, tuple[str, str]]
) -> list[str]:
    """The existing refs a merged branch may be an ancestor of: default, then lines."""
    tracking_prefix = f"{_REMOTES_PREFIX}{remote}/"
    targets = _default_proof_targets(remote, default, refs)
    for refname, (_object, kind) in refs.items():
        line = refname.removeprefix(tracking_prefix)
        if (
            refname.startswith(tracking_prefix)
            and kind == "commit"
            and line not in (default, "HEAD")
            and matches_any_glob(line, branches.integration_lines)
        ):
            targets.append(refname)
    return targets


def _merged_tracking_tips(
    directory: Path, remote: str, names: list[str], default: str, branches: BranchesConfig
) -> tuple[dict[str, str], list[str]]:
    """``(name -> tracking tip for every proven name, problems for the rest)``.

    Proven means: ``refs/remotes/<remote>/<name>`` exists, no tag shares the name, and
    the tip is an ancestor of the default branch (its remote-tracking ref or the local
    one) or, for an ordinary branch, of any existing ``refs/remotes/<remote>/<line>``
    for an integration line. An integration line is proved against the default only.
    One listing call, then one ``for-each-ref --merged`` per target over all the named
    refs, so the cost does not grow with the number of branches. Judged from local git
    only; the remote's live tip is checked afterwards by :func:`_remote_tip_problems`.
    Fails closed: a missing ref, a failing git and a timeout all give a reason.
    """
    tracking = {name: f"{_REMOTES_PREFIX}{remote}/{name}" for name in names}
    refs = _listed_refs(
        directory,
        [
            f"{_REMOTES_PREFIX}{remote}",
            branch_ref(default),
            *[f"{_TAGS_PREFIX}{name}" for name in names],
        ],
    )
    if refs is None:
        return {}, [
            f"`git for-each-ref` failed, so `{name}` could not be checked" for name in names
        ]
    tips: dict[str, str] = {}
    problems: list[str] = []
    for name in names:
        listed = refs.get(tracking[name])
        if f"{_TAGS_PREFIX}{name}" in refs:
            problems.append(f"`{name}` is also the name of a tag, so the delete is ambiguous")
        elif listed is None or listed[1] != "commit":
            problems.append(f"`{name}` has no remote-tracking ref `{tracking[name]}` here")
        else:
            tips[name] = listed[0]
    proven: set[str] = set()
    if tips:
        default_targets = _default_proof_targets(remote, default, refs)
        # An integration line is proved against the default branch ONLY: being merged
        # into another line is no evidence the line may go.
        feature_tracking = [
            tracking[name]
            for name in tips
            if not matches_any_glob(name, branches.integration_lines)
        ]
        for target in _proof_targets(remote, default, branches, refs):
            checked = (
                [tracking[name] for name in tips] if target in default_targets else feature_tracking
            )
            if not checked:
                continue
            merged = _merged_into(directory, target, checked)
            if merged is None:
                failed = [
                    f"`git for-each-ref --merged={target}` failed, so `{n}` could not be " "checked"
                    for n in tips
                ]
                return {}, problems + failed
            proven |= merged
    lines = " or any integration line" if branches.integration_lines else ""
    for name in list(tips):
        if tracking[name] not in proven:
            del tips[name]
            if matches_any_glob(name, branches.integration_lines):
                problems.append(
                    f"`{name}` is an integration line not yet merged into the default "
                    f"branch `{default}` (another line does not count)"
                )
            else:
                problems.append(f"`{name}` is not merged into `{default}`{lines}")
    return tips, problems


def _live_remote_tips(directory: Path, remote: str, names: list[str]) -> dict[str, str]:
    """Map branch name to the tip ``remote`` reports, from one ``ls-remote`` per chunk.

    Fails closed: a failed or timed-out listing contributes nothing, so its branches
    are absent from the map. Lines are keyed by their exact ref, so a pattern that
    also matches a longer name (``feat`` and ``feat-2``) or a foreign ref ending in
    the name never lends its tip to another branch.
    """
    tips: dict[str, str] = {}
    for start in range(0, len(names), _LS_REMOTE_CHUNK):
        chunk = names[start : start + _LS_REMOTE_CHUNK]
        listing = run_git(
            directory,
            "ls-remote",
            remote,
            *[f"{HEADS_PREFIX}{name}" for name in chunk],
            timeout=Timeout.GIT_CONTEXT,
            env={"GIT_TERMINAL_PROMPT": "0"},
        )
        if listing.returncode != 0:
            continue
        for line in listing.stdout.splitlines():
            tip, separator, listed = line.partition("\t")
            if separator and listed.startswith(HEADS_PREFIX):
                tips[listed.removeprefix(HEADS_PREFIX)] = tip
    return tips


def _remote_tip_problems(directory: Path, remote: str, local_tips: dict[str, str]) -> list[str]:
    """Why the remote's live tips are not the merged ``local_tips`` (name to tip).

    The remote-tracking ref is only as fresh as the last fetch: a commit pushed since
    would be lost by the delete. ``git ls-remote`` asks the remote itself, once for
    all the branches (a delete of dozens of branches once exceeded the dispatch
    budget at one call each); it never fetches. Fails closed: a mismatch, an absent
    branch, a failure and a timeout all give a reason naming the branch.
    """
    if not local_tips:
        return []
    live = _live_remote_tips(directory, remote, list(local_tips))
    return [
        f"the remote tip of `{name}` could not be confirmed as merged (it differs from "
        f"`{_REMOTES_PREFIX}{remote}/{name}`, is gone, or `git ls-remote {remote}` failed); "
        "run `git fetch` and retry"
        for name, tip in local_tips.items()
        if live.get(name) != tip
    ]


def _remote_delete_note(command: str, cwd: Path, branches: BranchesConfig) -> str | None:
    """None when every remote ref ``command`` deletes is merged, else why not."""
    if _SUBSTITUTION.search(command):
        return _unverified("a command or process substitution can run a delete this reading misses")
    deletions: list[tuple[GitInvocation, str, list[str]]] = []
    try:
        for run in git_invocations(command):
            targets = _remote_delete_targets(run) if run.subcommand == _PUSH else None
            if targets is not None:
                deletions.append((run, *targets))
    except _Unverifiable as exc:
        return _unverified(str(exc))
    if not deletions:
        return _unverified("no `git push --delete` / `git push <remote> :<name>` could be read")
    problems: list[str] = []
    for run, remote, refs in deletions:
        problem = placement_problem(run, cwd)
        if problem is not None:
            return _unverified(problem)
        directory = invocation_directory(run, cwd)
        if not path_is_dir(directory, unreadable_means=False):
            return _unverified(f"`{directory}` is not a directory")
        default = resolve_default_branch(branches, directory)
        if default is None:
            return _unverified("the default branch could not be determined")
        judged: list[str] = []
        for ref in refs:
            problem = _named_ref_problem(remote, ref, default, branches)
            if problem is not None:
                problems.append(problem)
            elif _branch_name(ref) not in judged:
                judged.append(_branch_name(ref))
        if judged:
            local_tips, unproven = _merged_tracking_tips(
                directory, remote, judged, default, branches
            )
            problems.extend(unproven)
            problems.extend(_remote_tip_problems(directory, remote, local_tips))
    if not problems:
        return None
    return (
        "Not deleted: " + "; ".join(problems) + ". A remote branch that is already merged into "
        "the default branch or an integration line may be deleted by an agent; an unmerged "
        "branch, an integration line not yet merged into the default, the default, an exempt "
        "or protected name (or any tag) is human-only, so ask the human to run it."
    )


# SINGLE SOURCE OF TRUTH for get_rules(): (rule_id, blocked, why, fix). One
# entry per unique RuleID in _PATTERN_RULE_IDS (9 rules, Decision B).
_RULE_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        RuleID.GIT_RESET_HARD,
        "`git reset --hard`",
        "Permanently destroys all uncommitted changes",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_CLEAN_FORCE,
        "`git clean -f`",
        "Permanently deletes untracked files",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_CHECKOUT_DISCARD,
        "`git checkout -- <file>` / `git checkout .`",
        "Discards local changes to file(s) permanently",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_RESTORE,
        "`git restore <file>`",
        "Discards local changes to files permanently (`--staged`/`-S` is allowed)",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_STASH_DROP,
        "`git stash drop`",
        "Permanently destroys a stashed change",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_STASH_CLEAR,
        "`git stash clear`",
        "Permanently destroys all stashed changes",
        "Ask the user to run it manually",
    ),
    (
        RuleID.GIT_PUSH_FORCE,
        "`git push --force` / `git push <remote> +<refspec>`",
        "Can overwrite remote history and destroy team members' work",
        "Ask the user to run it manually, or coordinate and use `--force-with-lease`",
    ),
    (
        RuleID.GIT_BRANCH_FORCE_DELETE,
        "`git branch -D` / `git update-ref -d refs/heads/<name>` of a branch no remote holds",
        "Force-deletes a branch without a merge check; a tip on no remote loses its commits",
        "Push the branch (`git push -u origin <name>`) and retry; a branch a remote holds "
        "is deleted freely",
    ),
    (
        RuleID.GIT_COMMIT_AMEND,
        "`git commit --amend`",
        "Rewrites the previous commit, creating messy history and potential data loss",
        "Create a new commit instead",
    ),
    (
        RuleID.GIT_CHECKOUT_FORCE,
        "`git checkout -f` / `git checkout --force`",
        "Discards every uncommitted change in the working tree, naming no file",
        "Commit or stash first; ask the user if the discard is genuinely wanted",
    ),
    (
        RuleID.GIT_SWITCH_FORCE,
        "`git switch -f` / `git switch --discard-changes`",
        "Discards every uncommitted change — the `switch` spelling of `checkout -f`",
        "Commit or stash first; `git switch <branch>` alone is never blocked",
    ),
    (
        RuleID.GIT_REFLOG_EXPIRE,
        "`git reflog expire --expire=now`",
        "Destroys the reflog, which is the recovery route the other rules assume",
        "Use a real expiry window (`--expire=90.days.ago`), which is not blocked",
    ),
    (
        RuleID.GIT_GC_PRUNE_NOW,
        "`git gc --prune=now`",
        "Drops unreachable objects immediately, so reflog-only history is gone",
        "Plain `git gc` and `git gc --auto` are not blocked; use a prune window",
    ),
    (
        RuleID.GIT_FILTER_HISTORY,
        "`git filter-branch` / `git filter-repo`",
        "Rewrites every commit in the history",
        "Ask the user to run it manually, on a fresh clone with a backup ref",
    ),
    (
        RuleID.GIT_PUSH_DELETE_REMOTE,
        "`git push --delete <name>` / `git push <remote> :<name>` of a branch not merged "
        "into the default branch, or of a tag; `git push --mirror` / `--prune` always",
        "Deletes a branch or tag in the shared remote repository, beyond any local recovery",
        "A branch already merged into the default branch is deleted freely; otherwise do not "
        "run it, stop and ask the human to run it themselves",
    ),
    (
        RuleID.GIT_WORKTREE_REMOVE_FORCE,
        "`git worktree remove [--force]` of a worktree holding dirty files, unregenerable "
        "ignored content, or a HEAD no surviving ref holds (forced or not)",
        "The removal deletes that work with no recovery",
        "Commit, push or deliberately delete each listed path, then remove",
    ),
    (
        RuleID.GIT_EVACUATE_THEN_DESTROY,
        "one command that copies a worktree's or branch's work to an untracked file "
        "(`git diff`/`format-patch`/`stash show -p`/`show` by redirect, `tee` or `-o`) and "
        "then destroys that worktree or branch",
        "The work survives only as an unreviewed patch file outside history",
        "Commit or push the work on the lane's branch, then remove it; or ask a human",
    ),
    (
        RuleID.GIT_DESTRUCTIVE_UNREADABLE,
        "a git command that may destroy changes and cannot be read in full",
        "Fail closed: a command this handler cannot parse might be any of the rules above",
        "Rewrite it as one plain git command per call, or ask the user to run it manually",
    ),
)


class DestructiveGitHandler(PreToolUseHandlerBase):
    """Block destructive git commands that permanently destroy data."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Compile the single source-of-truth mapping once, preserving order.
        self._pattern_reasons: tuple[tuple[re.Pattern[str], str], ...] = tuple(
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in _DESTRUCTIVE_PATTERN_REASONS
        )
        # Index-aligned rule_id per pattern (Decision B), compiled once alongside it.
        self._pattern_rule_ids: tuple[tuple[re.Pattern[str], str], ...] = tuple(
            (pattern, rule_id)
            for (pattern, _reason), rule_id in zip(
                self._pattern_reasons, _PATTERN_RULE_IDS, strict=True
            )
        )
        # One Rule per unique rule_id (Decision B: 9 rules), built once from the
        # single source-of-truth _RULE_DEFINITIONS mapping.
        self._rules: tuple[Rule, ...] = tuple(
            Rule(
                rule_id=rule_id,
                blocked=blocked,
                why=why,
                fix=fix,
                verbose=_VERBOSE_OVERRIDES.get(rule_id) or _verbose_content(why),
            )
            for rule_id, blocked, why, fix in _RULE_DEFINITIONS
        )
        self._rules_by_id: dict[str, Rule] = {rule.rule_id: rule for rule in self._rules}
        self._formatter = RuleFormatter()
        # Injected by the registry from the top-level `branches:` block (Plan 00558);
        # the model defaults apply when the config has none.
        self._branches: BranchesConfig = BranchesConfig()
        self._untracked_override: Path | None = None

    @property
    def destructive_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Compiled destructive-command patterns (derived from the single mapping)."""
        return tuple(pattern for pattern, _reason in self._pattern_reasons)

    @staticmethod
    def _scan_target(command: str) -> list[str]:
        """The command's segments with every span bash hands over as DATA blanked out.

        A quoted-delimiter heredoc body and an inert `-m`/`-F` message value
        are prose; the shell never parses them as syntax, so neither can be the
        destructive command this handler exists to stop. Scanning the raw
        string read them as one anyway (Plan 00377 N7): a commit message
        describing a newly added `--force` flag was denied as a force push.

        The mechanism is worth naming, because it is not "two words in one
        string". The opener line was `git commit -F - <<'EOF' && git push
        origin main`, so the heredoc BODY follows `git push` in the command
        string, and `_GIT_PUSH_FORCE_PATTERN`'s negated class excluded `;`, `&`
        and `|` but NOT newlines — the scan ran straight down into the body.
        That class now excludes the newline too (Plan 00406), which closes this
        route independently; blanking is still required, because an inert span
        can sit on the SAME line as the push. A second route needs no heredoc
        at all: the single-line patterns use
        `.*`, which stays on one line but still matches inside a `-m` value, so
        `git commit -m 'document --amend'` was denied too.

        `command_position_view` goes further (ledger N241): the arguments of a
        command that only prints or searches them (`echo`, `grep`), a `gh`
        title/body and a literal `bash -c` body are read as the commands they
        are, so `echo 'do not run git reset --hard'` is prose and
        `bash -c 'git reset --hard'` is not. A single-quoted message ends at
        the next quote, backslash or not.

        Both halves of `strip_inert_spans` are therefore required; blanking
        only the heredoc leaves that second route open. Nothing a shell can
        RUN is blanked — a substituting value (`-m "$(...)"`) and an UNQUOTED
        `<<EOF` body are both left intact, because bash really does execute
        them.

        What survives then has its in-word quoting removed, because bash removes
        it too: `git checkout "--" f.txt` hands git a bare `--`, and every rule
        anchored on a leading token missed the quoted spelling (Plan 00408 Task
        3.0). Blanking runs FIRST so a message value is gone before unquoting
        could expose anything inside it.

        The result is one string PER COMMAND SEGMENT, and each pattern is
        searched in each segment on its own. A pattern's `.*` therefore cannot
        run across `&&`, `;` or a pipe into the next command (Plan 00483 Task
        3.2): `git checkout main && git log -- src/x.py` has git log's `--`,
        and `git reset HEAD f && ls --hard` has ls's `--hard`. The quoted
        pattern of `git log --grep='...'` is data for that command and is
        blanked before the quotes are removed.
        """
        return [
            remove_word_quoting(segment) for segment in command_position_argument_segments(command)
        ]

    def _segment_matches(self, pattern: re.Pattern[str], command: str) -> bool:
        """Whether ``pattern`` matches inside any one command segment."""
        return any(pattern.search(target) for target in self._scan_target(command))

    def _match_reason(self, command: str) -> str | None:
        """Return the reason for the first matching destructive pattern, or None."""
        for pattern, reason in self._pattern_reasons:
            if self._segment_matches(pattern, command):
                return reason
        return None

    def _match_rule_id(self, command: str) -> str | None:
        """Return the RuleID for the first matching destructive pattern, or None.

        Mirrors ``_match_reason`` exactly — same ordered pattern list, and the
        same blanked scan target — so the two can never disagree about which
        pattern matched first, nor about what counted as a command.
        """
        for pattern, rule_id in self._pattern_rule_ids:
            if self._segment_matches(pattern, command):
                return rule_id
        return None

    def _match_rule_ids(self, command: str) -> list[str]:
        """Every distinct RuleID whose pattern matches, in pattern order."""
        matched = (
            rule_id
            for pattern, rule_id in self._pattern_rule_ids
            if self._segment_matches(pattern, command)
        )
        return list(dict.fromkeys(matched))

    @staticmethod
    def _cwd(hook_input: dict[str, Any]) -> Path:
        """The directory the command starts in.

        Raises:
            RuntimeError: When the event carries none and no project is initialised.
        """
        cwd = hook_input.get(HookInputField.CWD)
        if isinstance(cwd, str) and cwd:
            return Path(cwd)
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a destructive git command."""
        command = get_bash_command(hook_input)
        if not command or "git" not in command.lower():
            return False

        if self._match_reason(command) is not None:
            return True
        # An `rm -r` of a worktree matches no git pattern; only its evacuation makes it ours.
        return self._evacuation(command, hook_input) is not None

    def _evacuation(self, command: str, hook_input: dict[str, Any]) -> EvacuationMatch | None:
        """The evacuate-then-destroy shape in ``command``, unless the mode turns it off."""
        if self._branches.evacuation.mode == _MODE_OFF:
            return None
        cwd: Path | None = None
        try:
            cwd = self._cwd(hook_input)
        except RuntimeError as exc:
            log_and_continue(
                logger,
                exc,
                reason="with no starting directory the evacuation shape cannot be placed; "
                "the destructive patterns and their own fail-closed checks still apply",
            )
        if cwd is None:
            return None
        return evacuate_then_destroy(command, cwd) or self._same_turn(command, cwd, hook_input)

    def _same_turn(
        self, command: str, cwd: Path, hook_input: dict[str, Any]
    ) -> EvacuationMatch | None:
        """A destruction of work an earlier command of this turn evacuated (DESIGN section 13)."""
        return destroys_recorded(command, cwd, self._turn_records(hook_input))

    def _turn_records(self, hook_input: dict[str, Any]) -> list[Evacuation]:
        """The evacuations recorded this turn for the calling identity; none without a session."""
        session_id = hook_input.get(HookInputField.SESSION_ID)
        if not isinstance(session_id, str) or not session_id:
            return []
        raw_agent = hook_input.get(HookInputField.AGENT_ID)
        agent_id = raw_agent if isinstance(raw_agent, str) and raw_agent else None
        try:
            untracked = self._untracked_override or ProjectContext.daemon_untracked_dir()
        except RuntimeError as exc:
            log_and_continue(
                logger,
                exc,
                reason="with no daemon untracked directory there are no turn records to read; "
                "the same-command check and the destructive patterns still apply",
            )
            return []
        return recorded_evacuations(untracked, session_id, agent_id)

    @staticmethod
    def _evacuation_note(found: EvacuationMatch) -> str:
        return _with_principle(
            f"`{found.evacuation}` writes the work to `{found.landing}`, which nothing tracks, "
            f"and `{found.destruction}` then destroys its source. Commit or push the work on "
            "the lane's branch instead, or ask a human."
        )

    def get_rules(self) -> list[Rule]:
        """Return the Rule objects backing this handler's blocking behaviour.

        Deliberately uncounted. The previous wording named a figure, and Plan
        00412 class 6 made it false by adding five rules — a docstring that
        states a count is a claim that rots the next time anyone extends the
        single source of truth it describes.
        """
        return list(self._rules)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block the destructive command with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G): the first fire of a rule
        for a given agent is verbose (full teaching content); subsequent
        fires of the SAME rule for the SAME agent are terse. An event with no
        transcript_path fails toward verbose every time (unknown disclosure
        state -> more info, per the plan's risk table) since there is no key
        to track against.
        """
        command = get_bash_command(hook_input)
        if not command:
            return GatingResult(decision=Decision.ALLOW)

        # Evacuate then destroy (DESIGN section 13) is judged before any lossless allowance:
        # a removal that loses nothing to git has still moved the work out of history.
        found = self._evacuation(command, hook_input)
        if found is None:
            return self._judge(command, hook_input)
        note = self._evacuation_note(found)
        if self._branches.evacuation.mode != _MODE_WARN:
            return self._deny(RuleID.GIT_EVACUATE_THEN_DESTROY, note, hook_input)
        if not self._match_rule_ids(command):
            return GatingResult(decision=Decision.ALLOW, context=[note])
        result = self._judge(command, hook_input)
        if result.decision == Decision.ALLOW:
            return GatingResult(decision=Decision.ALLOW, context=[note])
        return result

    def _judge(self, command: str, hook_input: dict[str, Any]) -> GatingResult:
        """The destructive-pattern verdict, with each rule's lossless allowance."""
        # Both matches() and handle() consume the same ordered mapping, so they
        # can never drift on which pattern matched first.
        rule_ids = self._match_rule_ids(command)
        # A forced branch delete is the ONLY destructive rule with a safe case: when
        # every named tip is on a remote nothing can be lost. It is judged only when
        # no other rule matched too, so a compound command cannot ride the allowance,
        # and the denial then names the rule that actually blocks it.
        others = [matched for matched in rule_ids if matched not in _LOSSLESS_WHEN_PROVEN]
        rule_id = others[0] if others else (rule_ids[0] if rule_ids else None)
        if rule_id is None:
            # Defensive only: handle() is normally invoked exclusively after
            # matches() returned True, so this path is unreachable via the
            # daemon's dispatch. Kept for callers that invoke handle() directly
            # with a command none of the patterns matches.
            unreadable = self._rules_by_id[RuleID.GIT_DESTRUCTIVE_UNREADABLE]
            return GatingResult(
                decision=Decision.DENY,
                reason=f"{self._formatter.headline(unreadable)}\n\n{_GENERIC_DESTRUCTIVE_REASON}",
                rule=unreadable.rule_id,
            )

        note: str | None = None
        branches = self._branches
        if not others:
            try:
                judged = _force_removal_note(command, self._cwd(hook_input), branches, rule_id)
            except RuntimeError as exc:
                logger.warning("destructive_git: removal not verified: %s", exc)
                judged = rule_id, _with_principle(
                    _unverified("the directory the command runs in is unknown")
                )
            if judged is None:
                return GatingResult(decision=Decision.ALLOW)
            rule_id, note = judged
        elif rule_ids == [RuleID.GIT_PUSH_DELETE_REMOTE]:
            # A remote delete has the same safe case, judged only when it is the sole rule.
            try:
                note = _remote_delete_note(command, self._cwd(hook_input), branches)
            except RuntimeError as exc:
                logger.warning("destructive_git: delete not verified: %s", exc)
                note = _unverified("the directory the command runs in is unknown")
            if note is None:
                return GatingResult(decision=Decision.ALLOW)

        return self._deny(rule_id, note, hook_input)

    def _deny(self, rule_id: str, note: str | None, hook_input: dict[str, Any]) -> GatingResult:
        """Deny under ``rule_id``: verbose on its first fire for an agent, terse after."""
        rule = self._rules_by_id[rule_id]
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule_id)
            message = self._formatter.verbose(rule)

        if note is not None:
            message = f"{message}\n\n{note}"

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            rule=rule_id,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## destructive_git — blocked git commands\n\n"
            "The following git commands are blocked (a forced branch delete has one "
            "exception, in its row):\n\n"
            "| Command | Reason |\n"
            "|---------|--------|\n"
            "| `git reset --hard` | Permanently destroys all uncommitted changes |\n"
            "| `git clean -f` | Permanently deletes untracked files (a dry run `git clean -nd` is allowed) |\n"
            "| `git checkout -- <file>` | Discards all local changes to that file |\n"
            "| `git restore <file>` | Discards local changes (`--staged` alone, with or without "
            "`--source`, is allowed; `--staged --worktree` is not) |\n"
            "| `git stash drop` | Permanently destroys stashed changes |\n"
            "| `git stash clear` | Permanently destroys all stashes |\n"
            "| `git push --force` / `git push <remote> +<refspec>` "
            "| Can overwrite remote history and destroy teammates' work |\n"
            "| `git branch -D` / `git update-ref -d refs/heads/<name>` "
            "| ALLOWED when every named branch's tip is reachable from any surviving "
            "branch, tag or remote-tracking ref (refs the same command deletes do not "
            "count), judged in the repository the command runs in (`git -C`, `cd`); "
            "otherwise denied, naming each branch with the commits it would lose. Any "
            "check failure denies. Lowercase `-d` is the merge-checked delete. "
            "`branches.force_removal.mode: off` trusts only remote-tracking refs |\n"
            "| `git worktree remove [--force]` "
            "| ALLOWED when nothing would be lost: every ignored entry matches a "
            "`branches.cleanup_after_merge.regenerable` glob, the HEAD is held by a surviving "
            "ref, and when forced the status is clean. Otherwise denied "
            "(R-GIT-WORKTREE-REMOVE-FORCE), listing each path to commit, push or delete |\n"
            "| copy out, then destroy, in ONE command "
            "| `git diff`/`format-patch`/`stash show -p`/`show` written by redirect, `tee` or "
            "`-o` to an untracked, ignored or out-of-repo file, followed by `worktree "
            "remove`, `branch -d/-D`, `update-ref -d` or `rm -r` of that same worktree or "
            "branch, is denied (R-GIT-EVACUATE-THEN-DESTROY): commit or push on the lane's "
            "branch instead, or ask a human. The same denial applies when the copy was made by an "
            "EARLIER command of the same turn (the `evacuation_recorder` remembers it; the main "
            "thread's turn ends at your next prompt, a sub-agent's is its lifetime). "
            "`branches.evacuation.mode`: block, warn, off |\n"
            "| `git commit --amend` | Rewrites the previous commit — create a new commit instead |\n"
            "| `git checkout -f` / `git switch -f` / `git switch --discard-changes` "
            "| Discards every uncommitted change, naming no file |\n"
            "| `git reflog expire --expire=now` "
            "| Destroys the reflog — a real window such as `--expire=90.days.ago` is allowed |\n"
            "| `git gc --prune=now` "
            "| Drops unreachable objects at once; plain `git gc` and `--auto` are allowed |\n"
            "| `git filter-branch` / `git filter-repo` | Rewrites every commit in the history |\n"
            "| `git push --delete <name>` / `git push <remote> :<name>` "
            "| ALLOWED when every named branch is already merged into the default branch "
            "or an integration line (its `refs/remotes/<remote>/<name>` is an ancestor of "
            "the default branch or of a `branches.integration_lines` ref, "
            "and `git ls-remote` confirms the remote's live tip equals it, so a stale "
            "tracking ref is denied until `git fetch`; `git -C` and `cd` are honoured). "
            "Otherwise HUMAN ONLY — an "
            "unmerged branch, a tag, the default branch, an integration line not yet merged "
            "into the default branch (merged only into another line does not count), an "
            "exempt or protected name, a missing remote-tracking ref or "
            "any check failure is denied: stop and ask the human to run it. "
            "`git push --mirror` and `git push --prune` delete remote refs the command "
            "never names, so they are always HUMAN ONLY. Local "
            "`git tag -d` and `git reset --keep` are allowed |\n\n"
            "The last four rows close spellings that reached an outcome this handler "
            "already guarded: `git checkout -- <file>` was blocked while "
            "`git checkout -f` was not, and the reflog rules matter because the "
            "safety advice above ('can recover later') assumes a reflog still "
            "exists. Branch-switching itself is never blocked — `git switch main`, "
            "`git checkout -b feature` and `git gc --auto` all pass.\n\n"
            "If the user needs to run one of these, ask them to do it manually. "
            "Do not attempt to work around the block.\n\n"
            "**Each command is judged on its own, and on its own TOKENS.** A chained "
            "command is split at `&&`, `||`, `;`, `|` and newlines, so another command's "
            "flag is not this command's: `git checkout main && git log -- src/x.py` "
            "(the `--` is `git log`'s) and `git reset HEAD f && ls --hard` are allowed, "
            "while `x && git reset --hard` is denied exactly as `git reset --hard` is. "
            "A flag must start a word, so `git clean -nd build-final/` is a dry run on "
            "a directory whose NAME contains `-f`. The value of `--grep`, `-S`, `-G`, `-e`, `--format` "
            "or `--pretty` on a read-only git command (`log`, `show`, `diff`, `grep`, "
            "...), and an `awk` program, is data: `git log --grep='git reset --hard'` "
            "and `awk '/git stash/ {print}'` are allowed. A quoted argument of a git "
            "command that RUNS it (`submodule foreach`, `rebase --exec`, `bisect run`), "
            "a `!` alias body, an awk program calling `system`, and a format string "
            "piped into a shell are still judged. A quoted "
            "heredoc fed to `gh pr|issue|release|gist|api` or to a `while read` loop "
            "that only prints, counts or filters its input is prose too; a loop that "
            'runs its input (`eval "$l"`, `$l`, `bash -c`) is not.\n\n'
            "**PROSE describing one of these is not one of these.** What bash hands "
            "over as DATA is blanked before the command is judged, so a commit "
            "message that documents `--force`, or a `cat <<'EOF'` heredoc body naming "
            "`git reset --hard`, is not a destructive command and is not blocked. "
            "That was not always true: a commit message describing a newly added "
            "`--force` flag was denied as a force push, because the heredoc body "
            "followed `git push` on the opener line and the pattern's character "
            "class crossed the newline into it.\n\n"
            "**A heredoc is judged by what can EXECUTE its body, not by its "
            "delimiter.** `cat <<'EOF'` and `git commit -F - <<'EOF'` hand the body "
            "over as data, so it is prose. `bash <<'EOF'` runs it — the quoted "
            "delimiter only governs what the OUTER shell expands on the way in — so "
            "that body is scanned like any other command. Three things are checked, "
            "because each was a real hole: the receiver, every stage the body is "
            "piped on to (`cat <<'EOF' | bash`), and whether the command sits in a "
            "substitution (`$(cat <<'EOF' … )` puts the body's text in command "
            "position). Withholding the exemption costs a false positive; granting "
            "it wrongly cost five of these rules entirely.\n\n"
            "Three spans are deliberately still judged, because bash really does run "
            "them: a message value containing a SUBSTITUTION "
            '(`git commit -m "$(...)"` — double quotes do not stop expansion), '
            "an UNQUOTED `<<EOF` body, and a quoted heredoc fed to an interpreter. "
            "Write prose with the `Write` tool, or feed the heredoc to `cat`, and this "
            "never bites.\n\n"
            "**A force push is judged on the TOKEN, not on the letters.** Each force "
            "marker must START a whitespace-delimited argument, so a BRANCH NAME "
            "containing `-f-` is an ordinary push: `git push origin "
            "feature/lane-f-adoption` is allowed, and so is one ending `-f`. The same "
            "rule keeps `--follow-tags` and `--no-force-with-lease` out of it — the "
            "latter negates the lease rather than asking for one.\n\n"
            "**Grouped short flags ARE covered, so do not read `-f` as the only short "
            "spelling.** Git groups short options, so `git push -uf origin main` is a "
            "force push and is blocked, as are `-fu`, `-nf` and any other single-dash "
            "cluster carrying an `f`. A cluster WITHOUT one (`-nq`, `-u`) is untouched. "
            "Splitting the flag out does not change the verdict and is not a "
            "workaround.\n\n"
            "**To delete a branch, ALWAYS try `git branch -d` first.** It is allowed, "
            "it is battle-tested, and it refuses unless the branch is genuinely merged. "
            "Reach for anything else only once it has actually refused:\n\n"
            "```\n"
            "git branch -d <name>                          # ALWAYS TRY THIS FIRST\n"
            "hooks-daemon delete-branch --dry-run <name>    # only if -d refused\n"
            "hooks-daemon delete-branch <name>              # deletes only if provably safe\n"
            "```\n\n"
            "`git branch -d` refuses a branch whose commits are not ancestors of the "
            "target, which after a history rewrite or a squash merge means EVERY branch "
            "— the content is upstream but the ancestry is severed. That specific gap is "
            "what `delete-branch` fills; it is not a general replacement. It refuses by "
            "default and deletes only what it can prove is recoverable: merged, or every "
            "commit already upstream by patch-id, or every file version byte-identical to "
            "a blob still reachable from `main`. For a merged branch it delegates to "
            "`git branch -d` anyway, so git re-checks the work independently. A recovery "
            "bundle is written first unless you pass `--no-bundle`. If it refuses, it "
            "names the files whose CONTENT exists nowhere else.\n\n"
            "**Not every refusal is about content.** If another agent advances a branch "
            "after it was proved safe, `delete-branch` refuses THAT branch and names both "
            "shas — the proof described the old commit, and the recovery bundle was "
            "written before the new one exists, so it does not cover it. Re-run to "
            "reclassify against the current tip; never force past it.\n\n"
            "**A second, less obvious case where `-d` refuses**: it measures a branch "
            "against its OWN upstream when it has one, so a branch fully merged into "
            "`main` is still refused while it is ahead of `origin/<name>` — git says "
            '"not yet merged to `refs/remotes/origin/<name>`, even though it is merged '
            'to HEAD". Pushing the branch, or `delete-branch`, both resolve it; the '
            "latter reports this as the `merged-unpushed` tier and deletes it, because "
            "every one of those commits is already in `main`.\n\n"
            "**A third case, and the most ordinary of the three**: with NO upstream, git "
            "measures the branch against the checked-out `HEAD` instead — so a branch "
            "fully merged into `main` is refused whenever you are standing on some other "
            "branch, which is the normal way you notice a branch needs tidying. Git says "
            '"not fully merged" and suggests the force delete, which is blocked. '
            "`delete-branch` reports this as the `merged-not-in-head` tier and deletes "
            "it; checking out `main` first also resolves it.\n\n"
            "**Abandoning unmerged work is human-gated and you cannot complete it.** "
            "When no proof holds, the branch holds the only copy of real work, so "
            "`--allow-unproven --reason` is not enough: the command also requires a "
            "human to type a confirmation at an interactive terminal, which your "
            "non-interactive shell does not have. Those flags declare intent; consent "
            "is separate and cannot be self-granted. Report the named files to the user "
            "and ask them to run the command themselves — do not hunt for a way "
            "around it.\n\n"
            "**Safe alternatives**: `git stash` (recoverable), `git diff` / `git status` "
            "(inspect first), `git commit` (save changes permanently first)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for destructive git handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="git reset --hard",
                command="bash -n -c 'git reset --hard NONEXISTENT_REF_SAFE_TEST'",
                dispatch_as_bash=True,
                description="Blocks git reset --hard (destroys uncommitted changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"destroys.*uncommitted changes",
                ],
                safety_notes="Uses non-existent ref - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git clean -f",
                command="bash -n -c 'git clean -fd /nonexistent/safe/test/path'",
                dispatch_as_bash=True,
                description="Blocks git clean -f (permanently deletes untracked files)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Pp]ermanently deletes untracked files",
                ],
                safety_notes="Uses non-existent path - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git push --force",
                command="bash -n -c 'git push --force NONEXISTENT_REMOTE NONEXISTENT_BRANCH'",
                dispatch_as_bash=True,
                description="Blocks git push --force (overwrites remote history)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                    r"destroy.*work",
                ],
                safety_notes="Uses non-existent remote/branch - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git stash drop",
                command="bash -n -c 'git stash drop stash@{999}'",
                dispatch_as_bash=True,
                description="Blocks git stash drop (permanent deletion)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Pp]ermanently destroys",
                    r"stash",
                ],
                safety_notes="Uses non-existent stash index - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git checkout --",
                command="bash -n -c 'git checkout -- /nonexistent/safe/test/file.py'",
                dispatch_as_bash=True,
                description="Blocks git checkout -- (discards changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Dd]iscards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git restore",
                command="bash -n -c 'git restore /nonexistent/safe/test/file.py'",
                dispatch_as_bash=True,
                description="Blocks git restore (discards working tree changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Dd]iscards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git worktree remove --force",
                command="bash -n -c 'git worktree remove --force /nonexistent-safe-test-worktree'",
                dispatch_as_bash=True,
                description=(
                    "Blocks a worktree removal that cannot be proven lossless; the denial "
                    "names the branch-limit principle"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"R-GIT-WORKTREE-REMOVE-FORCE",
                    r"never so it disappears",
                ],
                safety_notes="Names a non-existent path - and bash -n -c only parses the command",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git branch -D",
                command="bash -n -c 'git branch -D NONEXISTENT_SAFE_TEST_BRANCH'",
                dispatch_as_bash=True,
                description=(
                    "Blocks git branch -D unless every named branch is on a remote; "
                    "the denial says to push first"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"remote",
                    r"git push -u origin",
                ],
                safety_notes="Uses non-existent branch - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git stash clear",
                command="bash -n -c 'git stash clear'",
                dispatch_as_bash=True,
                description="Blocks git stash clear (destroys all stashes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Pp]ermanently destroys all",
                    r"stash",
                ],
                safety_notes="bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git commit --amend",
                command="bash -n -c 'git commit --amend'",
                dispatch_as_bash=True,
                description="Blocks git commit --amend (rewrites previous commit)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"[Rr]ewrites the previous commit",
                    r"messy history",
                ],
                safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git push +refspec (plumbing force push)",
                command="bash -n -c 'git push origin +NONEXISTENT_SAFE_TEST_BRANCH:NONEXISTENT_SAFE_TEST_BRANCH'",
                dispatch_as_bash=True,
                description=(
                    "Blocks a `+`-prefixed refspec push (Plan 00205) — the plumbing "
                    "equivalent of `git push --force`"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                    r"destroy.*work",
                ],
                safety_notes="Uses non-existent branch name - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git push -uf (grouped short force flag)",
                command="bash -n -c 'git push -uf origin NONEXISTENT_SAFE_TEST_BRANCH'",
                dispatch_as_bash=True,
                description=(
                    "Blocks a force push spelled as a GROUPED short flag (issue #37). "
                    "Git groups short options, so `-uf` is `-u -f`; requiring the "
                    "literal `-f` missed it entirely"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                ],
                safety_notes="Uses non-existent branch name - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git update-ref -d refs/heads (plumbing branch delete)",
                command="bash -n -c 'git update-ref -d refs/heads/NONEXISTENT_SAFE_TEST_BRANCH'",
                dispatch_as_bash=True,
                description=(
                    "Blocks git update-ref -d refs/heads/<name> (Plan 00205) — the "
                    "plumbing equivalent of git branch -D — unless a remote holds the tip"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"remote",
                    r"git push -u origin",
                ],
                safety_notes="Uses non-existent branch - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="a commit message describing destructive flags is not a command",
                command=(
                    "git commit --dry-run --allow-empty -m 'documents --force and git reset --hard'"
                ),
                dispatch_as_bash=True,
                description=(
                    "Prose in a -m value is DATA, not shell syntax, so it must "
                    "NOT be blocked. Regression test for Plan 00377 N7, where a "
                    "commit message describing a newly added --force flag was "
                    "denied as R-GIT-PUSH-FORCE."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=("--dry-run --allow-empty: no commit is created, no side effects"),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="a substituting message value IS still judged",
                command="bash -n -c 'git commit -m \"$(git push --force)\"'",
                dispatch_as_bash=True,
                description=(
                    "Bash expands $(...) inside DOUBLE quotes, so a message "
                    "value carrying a substitution is not prose and stays "
                    "blocked. The boundary that makes N7's exemption safe."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                ],
                safety_notes=(
                    "bash -n -c only parses the command, so the substitution "
                    "inside it is never run and no push is attempted"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git push --delete (unverified remote ref deletion, human only)",
                command="bash -n -c 'git push origin --delete NONEXISTENT_SAFE_TEST_BRANCH'",
                dispatch_as_bash=True,
                description=(
                    "Blocks deleting a ref on the remote unless it is a branch already "
                    "merged into the default branch (owner rulings A6, D11); this one has "
                    "no remote-tracking ref, so the denial tells the agent to ask the "
                    "human to run it"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"REMOTE",
                    r"ask the human",
                ],
                safety_notes="Uses non-existent branch - and bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git tag -d is a local delete and is allowed",
                command="bash -n -c 'git tag -d NONEXISTENT_SAFE_TEST_TAG'",
                dispatch_as_bash=True,
                description=(
                    "A local tag delete touches only this checkout and is not blocked "
                    "(owner ruling A6); only the REMOTE deletion is human-only"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="git tag -f is not a force push",
                command="bash -n -c 'git tag -f v1.0.0-test-safe NONEXISTENT_SAFE_TEST_SHA'",
                dispatch_as_bash=True,
                description=(
                    "git tag -f force-moves a tag; it has nothing to do with "
                    "git push --force and must NOT be blocked. Regression test "
                    "for a dogfooding false positive (Plan 00200) where -f was "
                    "matched too broadly outside the git push segment."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Runs under bash -n -c, which only parses the command and never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
