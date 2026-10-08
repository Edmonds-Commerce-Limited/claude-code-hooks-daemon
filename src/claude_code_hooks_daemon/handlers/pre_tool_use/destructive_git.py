"""DestructiveGitHandler - blocks destructive git commands that permanently destroy data."""

import logging
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_INVOCATION,
    SUBCOMMAND_SEPARATOR_CHARS,
    remove_word_quoting,
)
from claude_code_hooks_daemon.utils.command_position import command_position_view
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, branch_ref, run_git
from claude_code_hooks_daemon.utils.git_sync import default_branch
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
        rf"{_GIT_INVOCATION}clean\s+.*-[a-z]*f",
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
        rf"{_GIT_INVOCATION}checkout\s+.*--\s+\S",
        "git checkout [REF] -- file discards all local changes to that file permanently",
    ),
    # git restore with file paths discards working-tree changes.
    # Does NOT match the staged-only forms (safe - they only unstage):
    #   git restore --staged file.txt   (long flag)
    #   git restore -S file.txt          (short flag, equivalent to --staged)
    (
        rf"{_GIT_INVOCATION}restore\s+(?!--staged\b)(?!-S\b).*\S",
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
    "A forced branch delete skips git's merge check, so a branch whose tip is on no remote "
    "would lose its commits with no recovery.\n\n"
    "It is ALLOWED when every named branch's tip is reachable from a remote-tracking ref "
    "(`git for-each-ref --contains <tip> refs/remotes/` is non-empty), judged in the "
    "repository the command runs in (`git -C <dir>` and a `cd` in the same command are "
    "honoured). Anything the check cannot establish is denied.\n\n"
    "To proceed: push each branch named below (`git push -u origin <name>`), then retry. "
    "`git branch -d` (lowercase) remains the merge-checked delete."
)
# A remote ref deletion removes the ref from the SHARED repository, where this
# checkout's reflog cannot bring it back and other people may be working from it.
# Owner ruling A6: a human runs it; ruling D11 (niggle N362) carves out ONE lossless case --
# a branch whose remote tip is already merged into the default branch. Tags stay human-only.
_PUSH_DELETE_VERBOSE: Final[str] = (
    "This command deletes a branch or tag on the REMOTE repository. Other people and other "
    "machines share that ref, and nothing in this checkout (reflog included) restores it.\n\n"
    "It is ALLOWED when every named branch's remote-tracking ref is already merged into the "
    "default branch (`git merge-base --is-ancestor`) AND `git ls-remote` shows the remote's "
    "live tip equal to it (a stale tracking ref is denied: run `git fetch` and retry), judged "
    "in the repository the command runs in; nothing is lost then. Tags, the default branch, an unmerged branch and anything "
    "the check cannot establish are denied.\n\n"
    "Otherwise do not run it, and do not look for another spelling of it. Stop and ask the "
    "human to run it themselves: tell them the remote, the ref and why it should go.\n\n"
    "Local clean-up is not affected: `git tag -d <tag>` and `git branch -d <name>` only touch "
    "this checkout and are allowed."
)
_VERBOSE_OVERRIDES: Final[dict[str, str]] = {
    RuleID.GIT_BRANCH_FORCE_DELETE: _BRANCH_DELETE_VERBOSE,
    RuleID.GIT_PUSH_DELETE_REMOTE: _PUSH_DELETE_VERBOSE,
}


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


def _not_on_a_remote(directory: Path, name: str) -> bool:
    """True unless a remote-tracking ref in ``directory`` reaches branch ``name``'s tip.

    Fails closed: a missing branch, a failing git and a timeout all answer True.
    """
    tip = run_git(
        directory,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{branch_ref(name)}^{{commit}}",
        timeout=Timeout.GIT_CONTEXT,
    )
    if tip.returncode != 0 or not tip.stdout.strip():
        return True
    holders = run_git(
        directory,
        "for-each-ref",
        "--contains",
        tip.stdout.strip(),
        "--count=1",
        "--format=%(refname)",
        "refs/remotes/",
        timeout=Timeout.GIT_CONTEXT,
    )
    return holders.returncode != 0 or not holders.stdout.strip()


def _unverified(reason: str) -> str:
    return f"This delete could not be verified as safe: {reason}. {_UNVERIFIED_ADVICE}"


def _branch_delete_note(command: str, cwd: Path) -> str | None:
    """None when every forced deletion names only branches a remote holds, else why not."""
    if _SUBSTITUTION.search(command):
        return _unverified("a command or process substitution can run a delete this reading misses")
    try:
        deletions = _deleted_branches(command)
    except _Unverifiable as exc:
        return _unverified(str(exc))
    if not deletions:
        return _unverified("no `git branch -D` / `git update-ref -d` invocation could be read")
    stranded: list[str] = []
    for run, names in deletions:
        problem = placement_problem(run)
        if problem is not None:
            return _unverified(problem)
        directory = invocation_directory(run, cwd)
        if not names:
            return _unverified("it names no branch")
        if not path_is_dir(directory, unreadable_means=False):
            return _unverified(f"`{directory}` is not a directory")
        for name in names:
            if not _LITERAL_BRANCH_NAME.fullmatch(name):
                return _unverified(f"`{name}` is not a literal branch name")
            if _not_on_a_remote(directory, name):
                where = "" if directory == cwd else f"-C {directory} "
                stranded.append(f"`{name}` (push it: `git {where}push -u origin {name}`)")
    if not stranded:
        return None
    return (
        "Not deleted: these branches are not on any remote (or could not be checked), so the "
        "delete could lose commits: " + "; ".join(stranded) + ". Push each one first, then retry."
    )


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


def _remote_branch_problem(directory: Path, remote: str, ref: str, default: str) -> str | None:
    """Why remote branch ``ref`` may not be deleted, or None when it is merged.

    Merged means: the remote-tracking ref ``refs/remotes/<remote>/<ref>`` exists and
    is an ancestor of the default branch (its remote-tracking ref or the local one).
    Fails closed: a missing ref, a failing git and a timeout all give a reason.
    """
    name = ref.removeprefix(HEADS_PREFIX)
    if not _LITERAL_BRANCH_NAME.fullmatch(remote):
        return f"`{remote}` is not a literal remote name"
    if name.startswith(_TAGS_PREFIX) or not _LITERAL_BRANCH_NAME.fullmatch(name):
        return f"`{ref}` is not a literal branch name (tags are never deleted by an agent)"
    if name == default:
        return f"`{name}` is the default branch"
    tag = run_git(
        directory,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{_TAGS_PREFIX}{name}",
        timeout=Timeout.GIT_CONTEXT,
    )
    if tag.returncode == 0:
        return f"`{name}` is also the name of a tag, so the delete is ambiguous"
    tracking = f"{_REMOTES_PREFIX}{remote}/{name}"
    tip = run_git(
        directory,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{tracking}^{{commit}}",
        timeout=Timeout.GIT_CONTEXT,
    )
    if tip.returncode != 0 or not tip.stdout.strip():
        return f"`{name}` has no remote-tracking ref `{tracking}` here"
    for target in (f"{_REMOTES_PREFIX}{remote}/{default}", branch_ref(default)):
        merged = run_git(
            directory,
            "merge-base",
            "--is-ancestor",
            tip.stdout.strip(),
            target,
            timeout=Timeout.GIT_CONTEXT,
        )
        if merged.returncode == 0:
            return _remote_tip_problem(directory, remote, name, tip.stdout.strip())
    return f"`{name}` is not merged into `{default}`"


def _remote_tip_problem(directory: Path, remote: str, name: str, local_tip: str) -> str | None:
    """Why the remote's live tip of ``name`` is not the merged ``local_tip``, else None.

    The remote-tracking ref is only as fresh as the last fetch: a commit pushed since
    would be lost by the delete. ``git ls-remote`` asks the remote itself; it never
    fetches. Fails closed: a mismatch, an absent branch, a failure and a timeout all
    give a reason.
    """
    listing = run_git(
        directory,
        "ls-remote",
        remote,
        f"{HEADS_PREFIX}{name}",
        timeout=Timeout.GIT_CONTEXT,
        env={"GIT_TERMINAL_PROMPT": "0"},
    )
    lines = listing.stdout.strip().splitlines() if listing.returncode == 0 else []
    if lines == [f"{local_tip}\t{HEADS_PREFIX}{name}"]:
        return None
    return (
        f"the remote tip of `{name}` could not be confirmed as merged (it differs from "
        f"`{_REMOTES_PREFIX}{remote}/{name}`, is gone, or `git ls-remote {remote}` failed); "
        "run `git fetch` and retry"
    )


def _remote_delete_note(command: str, cwd: Path) -> str | None:
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
        problem = placement_problem(run)
        if problem is not None:
            return _unverified(problem)
        directory = invocation_directory(run, cwd)
        if not path_is_dir(directory, unreadable_means=False):
            return _unverified(f"`{directory}` is not a directory")
        default = default_branch(directory)
        if default is None:
            return _unverified("the default branch could not be determined")
        for ref in refs:
            problem = _remote_branch_problem(directory, remote, ref, default)
            if problem is not None:
                problems.append(problem)
    if not problems:
        return None
    return (
        "Not deleted: " + "; ".join(problems) + ". A remote branch that is already merged into "
        "the default branch may be deleted by an agent; an unmerged branch (or any tag) is "
        "human-only, so ask the human to run it."
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
        "into the default branch, or of a tag",
        "Deletes a branch or tag in the shared remote repository, beyond any local recovery",
        "A branch already merged into the default branch is deleted freely; otherwise do not "
        "run it, stop and ask the human to run it themselves",
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

    @property
    def destructive_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Compiled destructive-command patterns (derived from the single mapping)."""
        return tuple(pattern for pattern, _reason in self._pattern_reasons)

    @staticmethod
    def _scan_target(command: str) -> str:
        """The command with every span bash hands over as DATA blanked out.

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
        """
        return remove_word_quoting(command_position_view(command))

    def _match_reason(self, command: str) -> str | None:
        """Return the reason for the first matching destructive pattern, or None."""
        target = self._scan_target(command)
        for pattern, reason in self._pattern_reasons:
            if pattern.search(target):
                return reason
        return None

    def _match_rule_id(self, command: str) -> str | None:
        """Return the RuleID for the first matching destructive pattern, or None.

        Mirrors ``_match_reason`` exactly — same ordered pattern list, and the
        same blanked scan target — so the two can never disagree about which
        pattern matched first, nor about what counted as a command.
        """
        target = self._scan_target(command)
        for pattern, rule_id in self._pattern_rule_ids:
            if pattern.search(target):
                return rule_id
        return None

    def _match_rule_ids(self, command: str) -> list[str]:
        """Every distinct RuleID whose pattern matches, in pattern order."""
        target = self._scan_target(command)
        matched = (rule_id for pattern, rule_id in self._pattern_rule_ids if pattern.search(target))
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

        return self._match_reason(command) is not None

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

        # Both matches() and handle() consume the same ordered mapping, so they
        # can never drift on which pattern matched first.
        rule_ids = self._match_rule_ids(command)
        # A forced branch delete is the ONLY destructive rule with a safe case: when
        # every named tip is on a remote nothing can be lost. It is judged only when
        # no other rule matched too, so a compound command cannot ride the allowance,
        # and the denial then names the rule that actually blocks it.
        others = [matched for matched in rule_ids if matched != RuleID.GIT_BRANCH_FORCE_DELETE]
        rule_id = others[0] if others else (rule_ids[0] if rule_ids else None)
        if rule_id is None:
            # Defensive only: handle() is normally invoked exclusively after
            # matches() returned True, so this path is unreachable via the
            # daemon's dispatch. Kept for callers that invoke handle() directly
            # with a command none of the patterns matches.
            return GatingResult(
                decision=Decision.DENY,
                reason=f"BLOCKED: {_GENERIC_DESTRUCTIVE_REASON}",
            )
        rule = self._rules_by_id[rule_id]

        note: str | None = None
        # A remote delete has the same safe case, judged only when it is the sole rule.
        check = (
            _branch_delete_note
            if not others
            else _remote_delete_note if rule_ids == [RuleID.GIT_PUSH_DELETE_REMOTE] else None
        )
        if check is not None:
            try:
                note = check(command, self._cwd(hook_input))
            except RuntimeError as exc:
                logger.warning("destructive_git: delete not verified: %s", exc)
                note = _unverified("the directory the command runs in is unknown")
            if note is None:
                return GatingResult(decision=Decision.ALLOW)

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
        )

    def get_claude_md(self) -> str | None:
        return (
            "## destructive_git — blocked git commands\n\n"
            "The following git commands are blocked (a forced branch delete has one "
            "exception, in its row):\n\n"
            "| Command | Reason |\n"
            "|---------|--------|\n"
            "| `git reset --hard` | Permanently destroys all uncommitted changes |\n"
            "| `git clean -f` | Permanently deletes untracked files |\n"
            "| `git checkout -- <file>` | Discards all local changes to that file |\n"
            "| `git restore <file>` | Discards local changes (`--staged` is allowed) |\n"
            "| `git stash drop` | Permanently destroys stashed changes |\n"
            "| `git stash clear` | Permanently destroys all stashes |\n"
            "| `git push --force` / `git push <remote> +<refspec>` "
            "| Can overwrite remote history and destroy teammates' work |\n"
            "| `git branch -D` / `git update-ref -d refs/heads/<name>` "
            "| ALLOWED when every named branch's tip is reachable from a remote-tracking "
            "ref, judged in the repository the command runs in (`git -C`, `cd`); otherwise "
            "denied, naming each branch to push first (`git push -u origin <name>`). Any "
            "check failure denies. Lowercase `-d` is the merge-checked delete |\n"
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
            "(its `refs/remotes/<remote>/<name>` is an ancestor of the default branch, "
            "and `git ls-remote` confirms the remote's live tip equals it, so a stale "
            "tracking ref is denied until `git fetch`; `git -C` and `cd` are honoured). "
            "Otherwise HUMAN ONLY — an "
            "unmerged branch, a tag, the default branch, a missing remote-tracking ref or "
            "any check failure is denied: stop and ask the human to run it. Local "
            "`git tag -d` and `git reset --keep` are allowed |\n\n"
            "The last four rows close spellings that reached an outcome this handler "
            "already guarded: `git checkout -- <file>` was blocked while "
            "`git checkout -f` was not, and the reflog rules matter because the "
            "safety advice above ('can recover later') assumes a reflog still "
            "exists. Branch-switching itself is never blocked — `git switch main`, "
            "`git checkout -b feature` and `git gc --auto` all pass.\n\n"
            "If the user needs to run one of these, ask them to do it manually. "
            "Do not attempt to work around the block.\n\n"
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
