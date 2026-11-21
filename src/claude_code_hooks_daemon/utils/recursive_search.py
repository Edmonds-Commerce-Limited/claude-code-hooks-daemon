"""Recursive searches that read a tree without naming a file in it (Plan 00483, D1).

``grep -r x .``, ``rg x``, ``find . | xargs rg x`` and ``git grep x`` read
every file under their roots, so a protected file or a quarantined DETAIL
artefact is disclosed although no word of the command names it. The text scan
of a command cannot see that; this module finds the roots such a command reads,
and which files the tool reads under them (:class:`TreeView`), and asks the
protected-file index (:mod:`protected_file_index`) whether any of them is
protected. The answer is a lookup in memory: nothing here walks the filesystem.

The roots are placed from the directory the command runs in, which follows a
literal ``cd`` earlier in the command, and a literal ``git -C`` for a ``git
grep`` (:func:`git_placement`). A root that cannot be placed (a variable, a
glob, a ``cd`` whose target is computed) is not judged; a ``git`` move that
cannot be placed is judged over every indexed file instead.

The option reader (:func:`search_command`, :func:`scan_options`) and the
command splitter (:func:`command_segments`) live here because
``flaggable_content_channel_guard`` reads the same commands for the same
reason, and two readers of one grammar drift.

Scope, deliberately: literal spellings. A search hidden behind an obfuscated
command word (``g\\rep``, ``"grep"``, ``$G``) is dismissed (ledger 00474 N152),
and a producer other than ``find`` feeding ``xargs`` names no root, so the directory
``xargs`` runs in is judged instead (the paths it will be handed are unknown). Commands
that hand a whole directory to a reader (``find -exec``, ``xargs``, ``tar``, ``cp``,
``diff``, ``zip``, ``rsync``, ``git diff --no-index``) are judged the same way as a search.
"""

import contextvars
import fnmatch
import logging
import os
import posixpath
import re
import stat
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from claude_code_hooks_daemon.utils import linear_shlex, path_exclusion
from claude_code_hooks_daemon.utils.bash_flags import SPAN_SEPARATORS, split_statements
from claude_code_hooks_daemon.utils.command_evasion import GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE
from claude_code_hooks_daemon.utils.command_position import SHELL_NAMES
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.find_expression import FIND_EXEC_ACTIONS, find_exec_end
from claude_code_hooks_daemon.utils.git_repo import RELOCATING_VARIABLES
from claude_code_hooks_daemon.utils.grep_option_grammar import (
    RG_CONFIG_ENV,
    grammar_for,
    parse_arguments,
)
from claude_code_hooks_daemon.utils.link_reach import LinkFollow, reached_through_links
from claude_code_hooks_daemon.utils.path_predicates import path_is_dir
from claude_code_hooks_daemon.utils.protected_file_index import (
    ExemptHook,
    ProtectedFileIndex,
    TreeView,
)
from claude_code_hooks_daemon.utils.resolution_failure import IncompleteScanError, fails_closed
from claude_code_hooks_daemon.utils.secret_file_matching import (
    CDPATH_VARIABLE,
    EXTGLOB_OPENERS,
    LINK_DIRECTORY_CAP,
    chdir_wrapper_targets,
    directory_ancestors,
    expand_directory_glob,
    link_scan_scope,
    path_mention_words,
    place_outside_project,
    scan_project_links,
    toplevel_move_length,
    toplevel_relocated,
)
from claude_code_hooks_daemon.utils.shell_expansion import (
    TooManyToEnumerateError,
    expand_braces,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    peel_command_wrappers,
    split_unquoted_spans,
)
from claude_code_hooks_daemon.utils.shell_snapshot import default_glob_semantics

logger = logging.getLogger(__name__)

# Whether the command being read names the ripgrep config variable; set by
# :func:`search_reads` for the duration of one read, so the nested readers see it.
_rg_config_named: Final[contextvars.ContextVar[bool]] = contextvars.ContextVar(
    "rg_config_named", default=False
)
# Whether the command being read names a variable that steers git (its config, its
# editor, its home): set by :func:`search_reads`. Unset, git is assumed steered.
_git_environment_named: Final[contextvars.ContextVar[bool]] = contextvars.ContextVar(
    "git_environment_named", default=True
)
_GIT_STEERING_VARIABLE: Final[re.Pattern[str]] = re.compile(r"GIT_|HOME|EDITOR|VISUAL")
# Whether the command could redefine what a later search word runs (a function, an alias,
# GREP_OPTIONS): set by :func:`search_reads`; no search is then proven to follow no link.
_follow_steering_named: Final[contextvars.ContextVar[bool]] = contextvars.ContextVar(
    "follow_steering_named", default=True
)

TOOL_GREP: Final[str] = "grep"
TOOL_RG: Final[str] = "rg"
TOOL_GIT: Final[str] = "git"

# grep-like: recursive only when asked (-r, -R, --recursive, -d recurse).
_GREP_COMMANDS: Final[frozenset[str]] = frozenset(
    {"grep", "egrep", "fgrep", "zgrep", "ugrep", "ug"}
)
# rg-like: recursive by default, and read piped stdin instead when given no root.
_RG_COMMANDS: Final[frozenset[str]] = frozenset({"rg", "ag", "ack"})
# Global git options that move the search somewhere the payload cwd does not describe.
_GIT_DASH_C: Final[str] = "-C"
_GIT_WORK_TREE: Final[str] = "--work-tree"
_GIT_DIR: Final[str] = "--git-dir"
_GIT_RELOCATING_OPTIONS: Final[frozenset[str]] = frozenset({_GIT_DASH_C, _GIT_DIR, _GIT_WORK_TREE})
# Global options whose value is the next word: read as the subcommand, it hides the search.
_GIT_OPTIONS_TAKING_VALUE: Final[frozenset[str]] = GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE | {
    "--attr-source"
}
# A configuration override naming this key moves the work tree as `--work-tree` does.
_GIT_CONFIG_OPTIONS: Final[frozenset[str]] = frozenset({"-c", "--config-env"})
_GIT_WORKTREE_KEY: Final[str] = "core.worktree"
# The root of a read that cannot be placed: every indexed file is under it.
_EVERYTHING: Final[str] = "/"
_GLOB_OPTIONS: Final[frozenset[str]] = frozenset({"-g", "--glob", "--iglob"})
_DIRECTORIES_OPTIONS: Final[frozenset[str]] = frozenset({"-d", "--directories"})
_EXCLUDE_DIR_OPTION: Final[str] = "--exclude-dir"
_EXCLUDE_OPTION: Final[str] = "--exclude"
_NEGATION: Final[str] = "!"
_END_OF_OPTIONS: Final[str] = "--"

_SHELL_COMMAND_FLAG: Final[str] = "-c"
_EVAL: Final[str] = "eval"
_XARGS: Final[str] = "xargs"
_XARGS_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J"}
)
#: Walkers with ``find``'s grammar: roots first, then an expression with ``-exec`` actions.
_FIND_COMMANDS: Final[frozenset[str]] = frozenset({"find", "gfind", "bfs"})
#: Walkers that run a command on each file they list: ``fd [OPTIONS] [PATTERN] [PATH]...``.
_FD_COMMANDS: Final[frozenset[str]] = frozenset({"fd", "fdfind"})
#: ``fd``'s options that run a command per file (``-x``) or once for all files (``-X``).
_FD_EXEC_LONG: Final[tuple[str, ...]] = ("--exec", "--exec-batch")
_FD_EXEC_TERMINATOR: Final[str] = ";"
#: ``fd`` options whose value is the next word (so it is neither the pattern nor a path).
_FD_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "-d",
        "-e",
        "-E",
        "-t",
        "-c",
        "-j",
        "-S",
        "-o",
        "--max-depth",
        "--min-depth",
        "--exact-depth",
        "--extension",
        "--exclude",
        "--type",
        "--color",
        "--threads",
        "--size",
        "--owner",
        "--changed-within",
        "--changed-before",
        "--newer",
        "--older",
        "--path-separator",
        "--ignore-file",
        "--batch-size",
        "--max-results",
        "--hyperlink",
        "--and",
        "--format",
        "--strip-cwd-prefix",
    }
)
_BRACE_OPEN: Final[str] = "{"
_FD_SEARCH_PATH: Final[str] = "--search-path"
_FD_BASE_DIRECTORY: Final[str] = "--base-directory"
_FIND_LEADING_OPTIONS: Final[frozenset[str]] = frozenset({"-H", "-L", "-P"})
_FIND_EXPRESSION_STARTS: Final[frozenset[str]] = frozenset({"(", "!", ")"})
# git grep reads the working tree instead of the index with either of these.
_GIT_GREP_WORKING_TREE_FLAGS: Final[frozenset[str]] = frozenset({"--no-index", "--untracked"})
_PATHSPEC_MAGIC_PREFIX: Final[str] = ":"
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# A root carrying any of these is not one directory the command line names.
_UNPLACEABLE_ROOT: Final[re.Pattern[str]] = re.compile(r"[$`*?\[{]")
# Of those, the ones that are not a glob: a glob root carrying one is not judged.
_EXPANSION_ROOT: Final[re.Pattern[str]] = re.compile(r"[$`{]")
_DIRECTORY_GLOB: Final[re.Pattern[str]] = re.compile(r"[*?\[]")


@dataclass
class SearchArguments:
    """What a grep-family invocation's arguments say about where it searches."""

    recursive: bool
    operands: list[str] = field(default_factory=list)
    exclude_dirs: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    pattern_given: bool = False
    uncertain: bool = False
    # Whether the tool may search its default root (the cwd) besides the operands.
    default_root_possible: bool = False

    def take_value(self, option: str, value: str) -> None:
        """Record the value of an option that takes one."""
        if option == _EXCLUDE_DIR_OPTION:
            self.exclude_dirs.append(value)
        elif option == _EXCLUDE_OPTION:
            self.excludes.append(value)
        elif option in _GLOB_OPTIONS:
            self.globs.append(value)
        elif option in _DIRECTORIES_OPTIONS and value == "recurse":
            self.recursive = True


def command_segments(command: str) -> list[tuple[str, bool]]:
    """Top-level command segments: statements, then pipe/&&/|| spans within each.

    Quote-aware and heredoc-safe via ``split_statements``/``split_unquoted_spans``.
    Each segment carries whether a pipe feeds it, because a search with no path
    operand reads that stdin instead of the working directory.
    """
    segments: list[tuple[str, bool]] = []
    for statement in split_statements(command, heredoc_bodies_executable=True):
        for start, end in split_unquoted_spans(statement, SPAN_SEPARATORS):
            segment = statement[start:end].strip()
            if not segment:
                continue
            before = statement[:start].rstrip()
            segments.append((segment, before.endswith("|") and not before.endswith("||")))
    return segments


def search_command(words: list[str]) -> tuple[str, int, bool] | None:
    """``(tool, index of the first argument, relocated)`` of a grep-family call, else None.

    ``relocated`` is True for a ``git -C``/``--git-dir``/``--work-tree`` search,
    whose working directory the payload cwd does not describe.
    """
    for index, word in enumerate(words):
        name = posixpath.basename(word)
        if name in _GREP_COMMANDS:
            return TOOL_GREP, index + 1, False
        if name in _RG_COMMANDS:
            return TOOL_RG, index + 1, False
        if name == TOOL_GIT:
            git_index = _running_git_index(words, index)
            if git_index is None:
                return None
            options = _git_global_options(words, git_index)
            relocated = any(
                word.partition("=")[0] in _GIT_RELOCATING_OPTIONS for word, _value in options
            )
            return TOOL_GIT, _git_options_end(words, git_index) + 1, relocated
    return None


def _git_options_end(words: list[str], git_index: int) -> int:
    """The index of the first word after the global options of the git at ``git_index``."""
    position = git_index + 1
    while position < len(words) and words[position].startswith("-"):
        position += 2 if words[position] in _GIT_OPTIONS_TAKING_VALUE else 1
    return position


def _running_git_index(words: list[str], start: int = 0) -> int | None:
    """The index of the ``git`` (from ``start`` on) whose subcommand is ``grep``, else None.

    A wrapper's value can be named ``git`` (``sudo -u git git -C .. grep``): that
    word is not the git that runs, so each ``git``-named word is tried in turn.
    """
    for index in range(start, len(words)):
        if posixpath.basename(words[index]) != TOOL_GIT:
            continue
        end = _git_options_end(words, index)
        if end < len(words) and words[end] == "grep":
            return index
    return None


def _git_global_options(words: list[str], git_index: int) -> list[tuple[str, str]]:
    """``(word, value)`` for each global option of the git at ``git_index``.

    ``word`` is the option as written (``--work-tree=x`` or ``-C``); ``value`` is
    its value, from after the ``=`` or from the next word.
    """
    options: list[tuple[str, str]] = []
    position = git_index + 1
    end = _git_options_end(words, git_index)
    while position < end:
        word = words[position]
        if word in _GIT_OPTIONS_TAKING_VALUE:
            options.append((word, words[position + 1] if position + 1 < len(words) else ""))
            position += 2
        else:
            _name, equals, value = word.partition("=")
            options.append((word, value if equals else ""))
            position += 1
    return options


def git_overrides_worktree(words: list[str]) -> bool:
    """Does a ``git ... grep`` in ``words`` override ``core.worktree`` (``-c``/``--config-env``)?

    Every global option is read, in any order: the override moves the tree git
    greps to one a configuration value names, which no ``-C`` describes. A
    relative ``core.worktree`` is resolved from the git dir, so ``..`` is the
    repository root wherever ``-C`` points.
    """
    git_index = _running_git_index(words)
    if git_index is None:
        return False
    return any(
        word.partition("=")[0] in _GIT_CONFIG_OPTIONS
        and value.partition("=")[0].lower() == _GIT_WORKTREE_KEY
        for word, value in _git_global_options(words, git_index)
    )


@dataclass(frozen=True)
class GitPlacement:
    """Where git's global options move a ``git ... grep`` (Plan 00618 S-1).

    ``directory`` is where git runs: the payload cwd moved by each literal ``-C``
    in turn, exactly as a ``cd`` to the same path moves it (None when a relative
    step has no absolute directory to start from, as for ``cd``). ``work_trees``
    are the literal ``--work-tree`` values, placed both where they stand and
    where git finally runs. ``foreign`` says the project's index does not
    describe what is read, so its tracked flags cannot narrow the read.
    ``unplaceable`` says where the search reads cannot be stated at all: a value
    needs an expansion, or ``--git-dir``/``core.worktree`` lets a configuration
    file choose the work tree. ``hidden`` narrows that to a ``-C`` directory
    no expansion the caller can see names: a ``~-``/``~N`` tilde, an ``xargs``
    replacement token. A caller that only warns on an expansion denies these.
    """

    directory: str | None
    work_trees: tuple[str, ...] = ()
    foreign: bool = False
    unplaceable: bool = False
    hidden: bool = False


_UNPLACEABLE_GIT: Final[GitPlacement] = GitPlacement(None, foreign=True, unplaceable=True)
_HIDDEN_GIT: Final[GitPlacement] = GitPlacement(None, foreign=True, unplaceable=True, hidden=True)
# The replacement token of `xargs -I R`/`-IR`/`--replace[=R]`/`-i[R]`, `{}` by default.
_XARGS_REPLACE_SHORT: Final[str] = "-I"
_XARGS_REPLACE_DEFAULTED: Final[tuple[str, ...]] = ("--replace", "-i")
_DEFAULT_REPLACE_TOKEN: Final[str] = "{}"
# A runner that substitutes into any word (`parallel`): no token can be ruled out.
_SUBSTITUTING_RUNNERS: Final[frozenset[str]] = frozenset({"parallel"})


def _replacement_tokens(words: list[str], git_index: int) -> list[str] | None:
    """The tokens a runner before ``git_index`` replaces in git's words; None: any word."""
    tokens: list[str] = []
    for index, word in enumerate(words[:git_index]):
        name = posixpath.basename(word)
        if name in _SUBSTITUTING_RUNNERS:
            return None
        if name != _XARGS:
            continue
        options = words[index + 1 : git_index]
        for position, option in enumerate(options):
            if option == _XARGS_REPLACE_SHORT and position + 1 < len(options):
                tokens.append(options[position + 1])
            elif option.startswith(_XARGS_REPLACE_SHORT) and option != _XARGS_REPLACE_SHORT:
                tokens.append(option[len(_XARGS_REPLACE_SHORT) :])
            elif option.startswith(_XARGS_REPLACE_DEFAULTED):
                prefix = next(p for p in _XARGS_REPLACE_DEFAULTED if option.startswith(p))
                tokens.append(option[len(prefix) :].removeprefix("=") or _DEFAULT_REPLACE_TOKEN)
    return tokens


def git_placement(words: list[str], cwd: str | None) -> GitPlacement:
    """Read the global options of the ``git`` that runs ``grep`` in ``words`` from ``cwd``."""
    git_index = _running_git_index(words)
    if git_index is None:
        return GitPlacement(cwd)
    if git_overrides_worktree(words):
        return _UNPLACEABLE_GIT
    tokens = _replacement_tokens(words, git_index)
    here = cwd
    work_trees: list[tuple[str, str | None]] = []
    for word, raw_value in _git_global_options(words, git_index):
        name = word.partition("=")[0]
        if name == _GIT_DIR:
            return _UNPLACEABLE_GIT
        if name not in (_GIT_DASH_C, _GIT_WORK_TREE):
            continue
        value = expand_tilde(raw_value)
        substituted = tokens is None or any(token and token in raw_value for token in tokens)
        if value is None or (substituted and name == _GIT_DASH_C):
            return _HIDDEN_GIT
        if _UNPLACEABLE_ROOT.search(value):
            return _UNPLACEABLE_GIT
        if name == _GIT_WORK_TREE:
            work_trees.append((value, here))
        elif value:
            # `git -C ''` is a no-op, as git documents.
            here = _place(value, here)
    placed: list[str] = []
    for value, standing in work_trees:
        for base in (standing, here):
            tree = _place(value, base)
            if tree is not None and tree not in placed:
                placed.append(tree)
    return GitPlacement(here, tuple(placed), foreign=bool(work_trees))


def git_search_directory(words: list[str], cwd: str | None) -> str | None:
    """The directory a ``git ... grep`` searches from, or None when it cannot be stated.

    None also for a search whose work tree is moved (``--work-tree``,
    ``--git-dir``, ``core.worktree``): the directory alone does not describe it.
    """
    placement = git_placement(words, cwd)
    if placement.unplaceable or placement.foreign:
        return None
    return placement.directory


def scan_options(
    arguments: list[str], *, tool: str, command: str = "", rg_config: bool = False
) -> SearchArguments:
    """Read options and operands of a grep-family invocation's arguments.

    ``command`` is the word that ran the search (``rg``, ``/usr/bin/rg``): the
    option grammar differs per tool (:mod:`grep_option_grammar`). The pattern
    operand is skipped only on positive proof. An option the grammar cannot
    place (an unknown name, an ambiguous abbreviation, an ``ug`` that reads its
    own config) keeps EVERY operand as a possible root, drops the exclusions, and
    leaves the default root possible whenever the unplaced options could have
    eaten all the operands: skipping a word on a guess hides a searched path.

    ``rg_config`` says the command names ``RIPGREP_CONFIG_PATH``: an ``rg`` then
    reads further options (a pattern among them) from a file, so it is uncertain.
    """
    chosen = grammar_for(command, git_grep=tool == TOOL_GIT, rg_config=rg_config)
    parsed = parse_arguments(chosen, arguments)
    scan = SearchArguments(recursive=tool != TOOL_GREP or parsed.recursive)
    scan.pattern_given = parsed.pattern_supplied
    scan.uncertain = parsed.uncertain
    for option, value in parsed.values:
        scan.take_value(option, value)
    operands = [arguments[position] for position in parsed.operands]
    if parsed.uncertain:
        scan.operands = operands
        scan.exclude_dirs, scan.excludes, scan.globs = [], [], []
        scan.default_root_possible = len(operands) <= 1 + parsed.maybe_consumed
        return scan
    scan.operands = operands if parsed.pattern_supplied else operands[1:]
    scan.default_root_possible = not scan.operands
    return scan


@dataclass(frozen=True)
class _Rules:
    """What a search tool leaves unread under its roots, by default and by option.

    ``negated_globs`` are ``rg -g '!glob'`` exclusions, kept only while EVERY
    glob given is negated: one positive glob could re-include what a negation
    removed, so none is tolerated.
    """

    skip_hidden: bool = False
    honour_ignore: bool = False
    exclude_dirs: tuple[str, ...] = ()
    exclude_files: tuple[str, ...] = ()
    negated_globs: tuple[str, ...] = ()

    def predicate(self, root: str) -> Callable[[str, bool], bool] | None:
        """The ``skip(path, is_dir)`` hook for a walk of ``root``, or None to read it all."""
        if not (self.skip_hidden or self.exclude_dirs or self.exclude_files or self.negated_globs):
            return None

        def skip(path: str, is_dir: bool) -> bool:
            name = posixpath.basename(path)
            if self.skip_hidden and name.startswith("."):
                return True
            names = self.exclude_dirs if is_dir else self.exclude_files
            if any(fnmatch.fnmatchcase(name, glob) for glob in names):
                return True
            relative = posixpath.relpath(path, root)
            return any(_glob_excludes(glob, relative, is_dir) for glob in self.negated_globs)

        return skip


_NO_RULES: Final[_Rules] = _Rules()


def _glob_excludes(glob: str, relative: str, is_dir: bool) -> bool:
    """Does a gitignore-style ``glob`` exclude the entry at ``relative``?

    A glob with no inner ``/`` matches an entry's name at any depth; one with a
    ``/`` is anchored at the root and matches component by component, so ``*``
    never crosses a separator. A trailing ``/**`` and a trailing ``/`` both
    name a directory, whose subtree goes with it when the walk prunes it.
    """
    if glob.endswith("/") and not is_dir:
        return False
    body = glob.removesuffix("/**").strip("/")
    if "/" not in body and not glob.startswith("/"):
        return fnmatch.fnmatchcase(posixpath.basename(relative), body)
    wanted = body.split("/")
    have = relative.split("/")
    return len(wanted) == len(have) and all(
        fnmatch.fnmatchcase(part, pattern) for part, pattern in zip(have, wanted, strict=True)
    )


def _tool_rules(name: str, arguments: list[str], scan: SearchArguments) -> _Rules:
    """The rules of the grep-family tool ``name`` for these ``arguments``.

    ``rg`` and ``ag`` skip hidden entries and honour ignore files unless told
    not to; ``grep`` reads both. ``ack`` is left unrestricted: it reads
    dotfiles, and what it ignores is not modelled.
    """
    if name == "rg":
        level = sum(len(word) - 1 for word in arguments if re.fullmatch(r"-u+", word))
        hidden = level < 2 and "--hidden" not in arguments and "-." not in arguments
        ignore = level < 1 and not any(word.startswith("--no-ignore") for word in arguments)
        globs = scan.globs
        negated = (
            tuple(glob.removeprefix(_NEGATION) for glob in globs)
            if globs and all(glob.startswith(_NEGATION) for glob in globs)
            else ()
        )
        return _Rules(skip_hidden=hidden, honour_ignore=ignore, negated_globs=negated)
    if name == "ag":
        unrestricted = any(word in ("-u", "--unrestricted") for word in arguments)
        return _Rules(
            skip_hidden=not unrestricted and "--hidden" not in arguments,
            honour_ignore=not unrestricted
            and not any(word in ("-U", "--skip-vcs-ignores") for word in arguments),
        )
    if name in _GREP_COMMANDS:
        return _Rules(
            exclude_dirs=tuple(glob.rstrip("/") for glob in scan.exclude_dirs),
            exclude_files=tuple(scan.excludes),
        )
    return _NO_RULES


@dataclass(frozen=True)
class Read:
    """One tree a search reads: a directory, which files the tool reads, and what it skips.

    ``view`` is ``TRACKED`` for ``git grep`` (the index), ``UNIGNORED`` for a
    tool that honours ignore files and ``ALL`` for one that reads everything;
    ``skip`` is the hook for hidden and excluded entries. A ``glob`` read is a glob
    ending in ``/``: ``root`` is the absolute pattern, and the directories it names
    are found in the protected-file index (:func:`protected_reached`), with the
    tool's ``rules`` deciding what each of them skips.
    """

    root: str
    view: TreeView = TreeView.ALL
    skip: Callable[[str, bool], bool] | None = None
    glob: bool = False
    rules: _Rules = field(default_factory=_Rules)
    default_expansion: bool = False
    #: The links below ``root`` the reader follows; ALL unless proven otherwise (Plan 00613).
    follows: LinkFollow = LinkFollow.ALL
    #: ``root`` is where a ``link/..`` root really points; outside the project nothing is indexed.
    physical: bool = False


@fails_closed
def search_reads(command: str, cwd: str | None) -> list[Read]:
    """Every tree a recursive search anywhere in ``command`` reads.

    Relative roots are placed from ``cwd``, moved by any literal ``cd`` that
    precedes the search; with no absolute directory to place them from they are
    left out, because a guess at where a search reads is worse than no answer.
    """
    bases = (cwd,) if cwd is not None and posixpath.isabs(cwd) else ()
    reset = _rg_config_named.set(RG_CONFIG_ENV in command)
    git_reset = _git_environment_named.set(_GIT_STEERING_VARIABLE.search(command) is not None)
    follow_reset = _follow_steering_named.set(_FOLLOW_STEERING.search(command) is not None)
    tracker = _SearchCwds(cwd, cdpath=CDPATH_VARIABLE in command, command=command)
    try:
        # One link scan for the command's many computed moves, even outside a guard's scope.
        with link_scan_scope():
            reads = list(dict.fromkeys(_reads(command, bases, 0, tracker)))
    finally:
        _follow_steering_named.reset(follow_reset)
        _git_environment_named.reset(git_reset)
        _rg_config_named.reset(reset)
    if not any(read.glob for read in reads):
        return reads
    default_expansion = default_glob_semantics(command)
    return [
        replace(read, default_expansion=default_expansion) if read.glob else read for read in reads
    ]


def protected_reached(
    reads: Sequence[Read], index: ProtectedFileIndex, *, is_exempt: ExemptHook | None = None
) -> tuple[str, str] | None:
    """``(pattern, searched root)`` when one of ``reads`` reaches a protected file in ``index``.

    ``is_exempt`` skips a protected file the caller confirmed safe to read. A read
    that follows links is also judged on what lies behind each link below its root
    (Plan 00613: a worktree's seeded links into the main checkout).
    """
    for read in reads:
        if read.physical and _outside_project(read.root, index):
            # `link/..` stepped out of a link to a place the project's index never listed
            # (a worktree-root daemon, the main checkout): no file there is vouched for.
            return (index.patterns[0], read.root) if index.patterns else None
        for searched in _directories_read(read, index):
            hit = index.find_under(
                searched.root, view=searched.view, skip=searched.skip, is_exempt=is_exempt
            )
            if hit is not None:
                return hit, searched.root
        if read.follows is LinkFollow.NONE:
            continue
        root = _glob_literal_directory(read.root) if read.glob else read.root
        hit = reached_through_links(root, read.follows, index, is_exempt=is_exempt)
        if hit is not None:
            return hit, root
    return None


def _outside_project(path: str, index: ProtectedFileIndex) -> bool:
    """Does ``path`` lie outside the project ``index`` lists, however either is spelled?"""
    tops = {index.project_root, os.path.realpath(index.project_root)}
    return not any(path == top or path.startswith(top.rstrip("/") + "/") for top in tops)


def _glob_literal_directory(pattern: str) -> str:
    """The directory an absolute glob spells before its first wildcard component.

    Every link a recursive reader of the glob's matches can follow lies below it.
    """
    literal: list[str] = []
    for part in pattern.split("/"):
        if any(char in part for char in _GLOB_CHARACTERS):
            break
        literal.append(part)
    return "/".join(literal) or "/"


def _directories_read(read: Read, index: ProtectedFileIndex) -> list[Read]:
    """``read`` itself, or for a ``glob`` read the directories of ``index`` it names.

    A recursive reader searches each directory the glob expands to as it searches a
    literal directory, with or without a trailing ``/``; only those holding a
    protected file matter.
    """
    if not read.glob:
        return [read]
    return [
        Read(directory, view=read.view, skip=read.rules.predicate(directory))
        for directory in index.directories_matching(
            read.root, default_expansion=read.default_expansion
        )
    ]


# Nested wrappers (`bash -c "bash -c ..."`) end here rather than recursing for ever.
_MAX_WRAPPER_DEPTH: Final[int] = 4
_DIRECTORY_CHANGERS: Final[frozenset[str]] = frozenset({"cd", "pushd"})
#: How many directories a search is placed from before it is judged over every indexed file.
SEARCH_DIRECTORY_CAP: Final[int] = 64
#: Wrappers with an option that runs the wrapped command elsewhere.
_CHDIR_WRAPPERS: Final[frozenset[str]] = frozenset({"env", "sudo"})
_BUILTIN: Final[str] = "builtin"
_EXEC: Final[str] = "exec"
#: ``exec -a NAME``: the option whose value is the next word.
_EXEC_NAME_OPTION: Final[str] = "-a"
_GLOB_CHARACTERS: Final[frozenset[str]] = frozenset("*?[")
#: A redirection with its file glued on (``>/dev/null``, ``2>&1``), and one without (``2>``).
_REDIRECTION_WORD: Final[re.Pattern[str]] = re.compile(r"\d*(?:&>>?|>>?|<>?|>&|<&)\S+")
_BARE_REDIRECTION: Final[re.Pattern[str]] = re.compile(r"\d*(?:&>>?|>>?|<>?|>&|<&)")


#: A segment head that opens a subshell: a ``cd`` behind it ADDS a directory.
_SUBSHELL_HEAD: Final[re.Pattern[str]] = re.compile(r"\s*(?:[A-Za-z_][A-Za-z0-9_]*=)?(?:\$\(|`|\()")
#: A segment head bash reads past to the command name, in the current shell.
_RESERVED_HEAD: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:[{!]|if|then|else|elif|do|while|until|time)(?:\s+|$)"
)
_TRAILING_CLOSERS: Final[re.Pattern[str]] = re.compile(r"[\s)}`]+$")
_QUOTED_SUBSTITUTION: Final[tuple[tuple[str, str], ...]] = (("$(", ")"), ("`", "`"))


def _unwrapped(segment: str) -> tuple[str, int, int]:
    """``segment`` without the group and keyword words around its command.

    Also how many subshells (``(``, ``$(``, a backtick) open before it and close
    after it. Review F1: ``(cd x``, ``{ cd x``, ``if cd x``, ``x=$(cd x`` and
    ``grep -r . l)`` are how a list split on its operators hands a wrapped
    command over.
    """
    opens = 0
    while True:
        opened = _SUBSHELL_HEAD.match(segment)
        if opened:
            segment, opens = segment[opened.end() :], opens + 1
            continue
        reserved = _RESERVED_HEAD.match(segment)
        if not reserved:
            break
        segment = segment[reserved.end() :]
    closers = _TRAILING_CLOSERS.search(segment)
    if closers is None:
        return segment, opens, 0
    tail = closers.group(0)
    return segment[: closers.start()], opens, tail.count(")") + tail.count("`")


def _substitution_bodies(segment: str) -> list[str]:
    """The command text inside a ``$( )`` or backtick pair a segment holds whole (quoted)."""
    bodies: list[str] = []
    for opener, closer in _QUOTED_SUBSTITUTION:
        start = segment.find(opener)
        end = segment.rfind(closer)
        if start != -1 and end > start + len(opener):
            body = segment[start + len(opener) : end]
            if " " in body:
                bodies.append(body)
    return bodies


def _directory_change(
    words: list[str], start: int, current: tuple[str, ...], cwds: "_SearchCwds"
) -> tuple[str, ...]:
    """Where a ``cd``/``pushd`` at ``words[start - 1]`` leaves the search, from each of ``current``."""
    operands = _operands(words[start:])
    if not operands or operands[0] == "-":
        return cwds.indeterminate()
    spelled = words[start:]
    while spelled and spelled[0].startswith("-"):
        spelled = spelled[1:]
    if toplevel_move_length(spelled, cwds.command) and current and not toplevel_relocated(current):
        # An ancestor of where the search is, each one kept, besides the computed-move
        # judgement, which still fails closed: config or environment the guard cannot
        # read (a split-spelled GIT_WORK_TREE, a written core.worktree) moves the top level.
        root = path_exclusion.resolve_project_root()
        above = (ancestor for base in current for ancestor in directory_ancestors(base, root))
        return tuple(dict.fromkeys((*above, *cwds.indeterminate())))
    return cwds.moved(operands[0], current)


_POPD: Final[str] = "popd"
# Words that open a group or negate before the command a segment runs: `( cd sub`, `{ cd sub`.
_GROUP_OPENERS: Final[frozenset[str]] = frozenset({"(", "{", "!"})


def shell_directory_after(words: list[str], current: str | None) -> str | None:
    """Where the shell is after the segment ``words``, starting from ``current``.

    A ``cd``/``pushd`` (also inside an opening ``(``/``{``) moves it; a ``popd``,
    or a move whose target cannot be placed, leaves it unknown (None). Leaving a
    subshell is not followed: a caller that also judges the payload cwd loses
    nothing by it.
    """
    start = 0
    while start < len(words) and words[start] in _GROUP_OPENERS:
        start += 1
    head = posixpath.basename(words[start]) if start < len(words) else ""
    if head == _POPD:
        return None
    if head in _DIRECTORY_CHANGERS:
        return _after_directory_change(words[start:], current)
    return current


def _after_directory_change(words: list[str], current: str | None) -> str | None:
    """The directory a ``cd``/``pushd`` leaves the command in; None when it cannot be told."""
    operands = [word for word in words[1:] if not word.startswith("-")]
    if not operands or operands[0] == "-":
        return None
    return _place(operands[0], current)


@dataclass(frozen=True)
class _MadeLink:
    """A link a statement of the command creates: where it leads, where it is placed.

    ``destinations`` is None when the place cannot be told, so any later reader
    may pass through it. ``origin`` is the creating statement's own words.
    """

    sources: tuple[str, ...]
    destinations: tuple[str, ...] | None
    origin: tuple[str, ...]


@dataclass
class _SearchCwds:
    """The directories a search may run in, and every ``cd`` target the command named."""

    hook_cwd: str | None
    targets: list[str] = field(default_factory=list)
    # A `cd` to a tilde the hook cannot place (`~-`) was seen: later reads judge every file.
    lost: bool = False
    # The directories passed SEARCH_DIRECTORY_CAP: later moves are not followed.
    overflowed: bool = False
    # The command names CDPATH: a relative cd may land in any directory it lists.
    cdpath: bool = False
    # A computed move's link scan did not finish: a later reader is denied (review D2).
    unscanned: bool = False
    # The whole command, for what a move's spelling depends on (git's top level).
    command: str = ""
    # The directory links a computed move's scan found: a later reader may pass through one.
    computed_links: list[str] = field(default_factory=list)
    # Links earlier statements of the command create: the filesystem the hook sees lacks them.
    made_links: list[_MadeLink] = field(default_factory=list)

    def indeterminate(self) -> tuple[str, ...]:
        """A move that cannot be placed: the project root, every named target and the hook cwd.

        A scan that did not finish marks the search ``unscanned``, also when the
        caller placed the move too (git's top level, ``~``): that placement rests
        on state the command can change (Plan 00623 review).
        """
        root = path_exclusion.resolve_project_root()
        # Reviews 614b R4, 614c N1: every project directory holding a link, and every directory link.
        scan = scan_project_links(root) if root else None
        if scan is not None and not scan.complete:
            self.unscanned = True
        if scan is not None:
            self.computed_links.extend(scan.value.directory_links)
        if scan is not None and scan.value.named is not None:
            # Past the scan cap (N669/N670) the holding directories are not listed as
            # places: as past SEARCH_DIRECTORY_CAP, every later read is judged over
            # every indexed file, and each directory link is read as a root.
            self.lost = self.overflowed = True
        linked = scan.value.directories if scan is not None else ()
        found = [root, *self.targets, self.hook_cwd, *linked]
        return tuple(dict.fromkeys(path for path in found if path and posixpath.isabs(path)))

    def moved(self, target: str, current: tuple[str, ...]) -> tuple[str, ...]:
        outside = place_outside_project(target, self.command)
        if outside:
            # Plan 00623: ~, $HOME or $TMPDIR outside the project is placed there, and
            # is still judged as computed, failing closed: the shell's value can differ.
            self.targets.extend(outside)
            return tuple(dict.fromkeys((*outside, *current, *self.indeterminate())))
        if any(opener in target for opener in EXTGLOB_OPENERS):
            # Review 614c N3: an extended glob names no directory this walk can list.
            return tuple(dict.fromkeys((*self.indeterminate(), *current)))
        if self.cdpath and not posixpath.isabs(target):
            # Review 614c N3: bash may find a relative operand under a CDPATH entry instead.
            return tuple(dict.fromkeys((*self._moved(target, current), *self.indeterminate())))
        return self._moved(target, current)

    def _moved(self, target: str, current: tuple[str, ...]) -> tuple[str, ...]:
        bases: tuple[str | None, ...] = current or (None,)
        if any(char in _GLOB_CHARACTERS for char in target):
            return self._globbed(target, bases)
        placed = [(base, _place(target, base)) for base in bases]
        result = tuple(dict.fromkeys(path for _base, path in placed if path is not None))
        if not result:
            return self.indeterminate()
        self.targets.extend(result)
        # A cd to what is not a directory fails, and a command after `;` or `||`
        # then runs where the shell already was (review 614b): that place stays.
        stayed = [
            base
            for base, path in placed
            if base is not None and (path is None or not path_is_dir(path, unreadable_means=False))
        ]
        return tuple(dict.fromkeys((*result, *stayed)))

    def _globbed(self, target: str, bases: tuple[str | None, ...]) -> tuple[str, ...]:
        """The directories a globbed ``cd`` target matches from each base, as bash expands it."""
        stayed = tuple(base for base in bases if base is not None)
        matched: dict[str, None] = {}
        for base in bases:
            placed = _place(target, base)
            if placed is None:
                continue
            found = expand_directory_glob("/", placed)
            if found.complete:
                matched.update(dict.fromkeys(found.value))
            if not found.complete or len(matched) > LINK_DIRECTORY_CAP:
                # Too wide to follow (reviews 614b, 614c X1): judged as a computed
                # move, and bash refuses a cd with several matches, so the bases stay.
                return tuple(dict.fromkeys((*self.indeterminate(), *stayed)))
        if not matched:
            return self.indeterminate()
        self.targets.extend(matched)
        # The cd may still fail (several matches are too many arguments): the base stays too.
        return tuple(dict.fromkeys((*matched, *stayed)))


def _reads(command: str, cwds: tuple[str, ...], depth: int, tracker: _SearchCwds) -> Iterator[Read]:
    """Every tree a search anywhere in ``command`` reads, from each of ``cwds``.

    A ``cd`` REPLACES the directories, inside a subshell (``(``, ``$(``, a
    backtick) as at the top level. When a subshell closes, the directories it
    left are ADDED to those it started from rather than dropped: the list is
    split on its operators, so which closer ends which group is a guess, and
    a wrong guess must over-approximate (``(cd a && true); cd b && cat l``).
    """
    if depth > _MAX_WRAPPER_DEPTH:
        # N664 (Plan 00623): a body past the limit is not walked, so one that could
        # read a tree is unknown, never "no read"; a harmless body still ends here.
        if _could_read(command):
            raise IncompleteScanError("a search is nested deeper than the walk follows")
        return
    feeder: tuple[str, ...] | None = None
    current = cwds
    saved: list[tuple[str, ...]] = []
    for raw, piped_in in command_segments(command):
        for body in _substitution_bodies(raw):
            yield from _reads(body, current, depth + 1, tracker)
        segment, opens, closes = _unwrapped(raw)
        saved.extend([current] * opens)
        fed_by = feeder if piped_in else None
        # The segment as written is judged too: unwrapping is a guess that can
        # misread one (`FOO=$(true) grep -r x .`, `grep -r x a\(1\)`), and it
        # may only ever add reads.
        for judged in dict.fromkeys((raw, segment)):
            yield from _segment_reads(judged, piped_in, fed_by, current, depth, tracker)
        feeder, current = _segment_state(segment, fed_by, current, tracker)
        if len(current) > SEARCH_DIRECTORY_CAP:
            # Each failed `cd` keeps its base beside its target, so the set can double
            # per `cd`. Past the cap every later read is judged over every indexed file.
            # Where a read is placed then makes no difference, so the set is cut.
            tracker.lost = tracker.overflowed = True
            current = current[:SEARCH_DIRECTORY_CAP]
        for _ in range(min(closes, len(saved))):
            current = tuple(dict.fromkeys((*saved.pop(), *current)))


def _segment_state(
    segment: str, fed_by: tuple[str, ...] | None, current: tuple[str, ...], tracker: _SearchCwds
) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    """The roots a segment feeds the next one, and the directories it leaves the command in.

    A stage that is not a ``find`` passes the producer's roots on
    (``find d | sort | xargs cat``).
    """
    words = _command_words(segment)
    if not words:
        return fed_by, current
    head = posixpath.basename(words[0])
    if head in _DIRECTORY_CHANGERS:
        # A `cd ~-` (a tilde the hook cannot place) loses the directory: every later read fails closed.
        tracker.lost = tracker.lost or any(unknown_tilde(word) for word in words[1:])
        if tracker.overflowed:
            # Every later read is judged over every indexed file: the move is not followed.
            return fed_by, current
        return fed_by, _directory_change(words, 1, current, tracker)
    if head in _FIND_COMMANDS:
        return _find_roots(words), current
    return fed_by, current


def _segment_reads(
    segment: str,
    piped_in: bool,
    fed_by: tuple[str, ...] | None,
    current: tuple[str, ...],
    depth: int,
    tracker: _SearchCwds,
) -> Iterator[Read]:
    """The trees the one command of ``segment`` reads, from each of ``current``."""
    words = _command_words(segment)
    if not words:
        # `$(<file)` runs no command word and still reads its redirect (re-review R4).
        yield from _reads_through_made_links(words, segment, current, tracker)
        return
    here = current
    relocating_env = _assigns_a_relocating_variable(segment, words)
    # `env -C dir cmd` runs cmd in dir; the wrapper is peeled from `words`. The
    # segment already split cleanly into `words`, so this split cannot raise.
    raw_words = _past_command_prefix(linear_shlex.split(segment))
    wrapper = posixpath.basename(raw_words[0]) if raw_words else ""
    if wrapper in _CHDIR_WRAPPERS:
        for target in chdir_wrapper_targets(wrapper, raw_words, 1):
            here = tracker.moved(target, here)
        # The scan reads a `-C` of the wrapped command as the wrapper's too
        # (`env git -C d grep`), and git places its own `-C`: where the command
        # started stays a base, so a move read twice never loses the real one.
        here = tuple(dict.fromkeys((*here, *current)))
    head = posixpath.basename(words[0])
    if tracker.unscanned and head not in _DIRECTORY_CHANGERS and _reads_files(words, head):
        # Review D2: the reader may run from a directory the unfinished scan never reached.
        raise IncompleteScanError(
            "a computed directory change's link scan stopped before it finished"
        )
    if tracker.computed_links and head not in _DIRECTORY_CHANGERS and _reads_files(words, head):
        # Round 6 class sweep: after a computed move the shell may sit above a directory
        # link, and a deeper root (`sub/a/dl`) reaches it; each such link is read as a root.
        for link in dict.fromkeys(tracker.computed_links):
            yield Read(link, view=TreeView.ALL)
    if tracker.lost and head not in _DIRECTORY_CHANGERS and _reads_files(words, head):
        yield Read(_EVERYTHING, view=TreeView.ALL)
        # A directory link out of the project is under no indexed file: each place a
        # move could have reached, the links among them, is read as a root too.
        for directory in tracker.indeterminate():
            yield Read(directory, view=TreeView.ALL)
    yield from _reads_through_made_links(words, segment, here, tracker)
    made = _made_link(words, here, segment)
    if made is not None and made not in tracker.made_links:
        tracker.made_links.append(made)
    if head in SHELL_NAMES and _SHELL_COMMAND_FLAG in words[1:-1]:
        inner = words[words.index(_SHELL_COMMAND_FLAG, 1) + 1]
        yield from _reads(inner, here, depth + 1, tracker)
    elif head == _EVAL:
        yield from _reads(" ".join(words[1:]), here, depth + 1, tracker)
    elif head in _FIND_COMMANDS:
        if _find_execs_a_reader(words):
            # find hands each link it lists to its command, which may follow it
            # (`-exec grep -r {}`, `-exec cat {}/x`): no find proves it follows none.
            yield from _reads_from_each(_find_roots(words), here)
    elif (fd_roots := _fd_exec_roots(words)) is not None:
        # fd hands each file it lists to its `-x`/`-X` command, as find does.
        yield from _reads_from_each(fd_roots, here)
    elif head == _XARGS:
        inner_words = _xargs_command(words)
        if inner_words and _is_search(inner_words):
            for base in here or (None,):
                yield from _search_reads(inner_words, base, piped_in=True)
        if _runs_a_reader(inner_words):
            # Fed by `find`, xargs reads what `find` lists. Fed by anything else the paths are
            # unknown, so the tree it runs in is judged.
            yield from _reads_from_each(fed_by or (".",), here)
    elif (directory_roots := _directory_reader_roots(words)) is not None:
        yield from _reads_from_each(directory_roots, here)
    elif _is_search(words):
        for base in here or (None,):
            yield from _search_reads(words, base, piped_in=piped_in, relocating_env=relocating_env)


# --- A link made earlier in the same command (Plan 00613 F-BYPS F5) ------------------------------
#
# The hook judges the filesystem as it is before the command runs, so a link the command makes
# (`ln -s main/conf conf2 && cat conf2/vault.txt`) does not exist yet when a later statement is
# placed. Each link-making statement is recorded with where it leads and where it lands; a later
# statement that names that place, or a place above or below it, is judged as a read of where
# the link leads. A link that leads outside the project fails closed (see `Read.physical`).

#: Every ``ln``/``link`` makes a link, whatever its flags (re-review R4: an
#: abbreviated ``--sym`` is still ``--symbolic``, and a hard link is a link too).
_LINK_COMMANDS: Final[frozenset[str]] = frozenset({"ln", "link"})
_SYMBOLIC_COPY: Final[str] = "cp"
_SYMBOLIC_COPY_LONG: Final[str] = "--symbolic-link"
#: ``install -l <flags>`` (BSD) links instead of copying; ``-l`` takes a value.
_INSTALL: Final[str] = "install"
_INSTALL_LINK_OPTION: Final[str] = "-l"
#: ``mv`` relocates an existing link (a seeded one): its target is read from where it lands.
_MOVE: Final[str] = "mv"
#: Multi-call binaries that run the applet named by their first argument.
_MULTI_CALL: Final[frozenset[str]] = frozenset({"busybox", "toybox"})
_TARGET_DIRECTORY_OPTIONS: Final[frozenset[str]] = frozenset({"-t", "--target-directory"})
_SUFFIX_OPTIONS: Final[frozenset[str]] = frozenset({"-S", "--suffix"})
_SEED_WORKTREE: Final[str] = "seed-worktree"
_HOOKS_DAEMON: Final[str] = "hooks-daemon"
_INPUT_REDIRECT: Final[str] = "<"
#: An interpreter one-liner that may make a link: its operands cannot be placed (N683 class),
#: so the link is judged as leading anywhere and landing anywhere.
_INTERPRETER: Final[re.Pattern[str]] = re.compile(
    r"(?:python|pypy)[0-9.]*|node(?:js)?|deno|bun|perl|ruby|php|lua"
)
#: A call of a link-making function (``os.symlink(``, ``fs.symlinkSync(``,
#: ``Path.symlink_to(``, ``os.link(``, perl ``symlink "a", "b"``) or an ``ln``
#: run as a quoted program; ``unlink``/``readlink``/``islink``/``is_symlink``
#: are not link-makers, hence the lookbehind.
_INTERPRETER_LINK_CALL: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z_])(?:symlink(?:Sync|_to)?|(?:hard)?link(?:Sync|_to)?)(?=\s*[(\"'$])" r"|[\"']ln\b"
)


def _made_link(words: list[str], here: tuple[str, ...], segment: str) -> _MadeLink | None:
    """The link a statement creates or relocates, or None.

    ``ln``/``link`` (any flags), ``cp -s``, ``install -l``, ``mv`` of what may be a
    link, an interpreter one-liner calling a link function, and
    ``hooks-daemon seed-worktree``; a ``busybox``/``toybox`` applet is its applet.
    """
    head = posixpath.basename(words[0])
    if head in _MULTI_CALL and len(words) > 1:
        words = words[1:]
        head = posixpath.basename(words[0])
    if head == _HOOKS_DAEMON:
        operands = _link_operands(words[1:])[0]
        if not operands or operands[0] != _SEED_WORKTREE:
            return None
        destinations = _places(operands[1:2], here)
        # What a seed list links is the project's configuration: every file may be behind one.
        return _MadeLink((_EVERYTHING,), destinations, tuple(words))
    if _INTERPRETER.fullmatch(head) and _INTERPRETER_LINK_CALL.search(segment):
        return _MadeLink((_EVERYTHING,), None, tuple(words))
    if head == _MOVE:
        return _moved_link(words, here)
    if not _makes_a_link(head, words[1:]):
        return None
    valued = frozenset({_INSTALL_LINK_OPTION}) if head == _INSTALL else frozenset()
    operands, target_directory = _link_operands(words[1:], valued)
    if target_directory is not None:
        sources, destination_words = operands, [target_directory]
    elif len(operands) >= 2:
        sources, destination_words = operands[:-1], [operands[-1]]
    elif operands:
        sources, destination_words = operands, [posixpath.basename(operands[0])]
    else:
        return None
    destinations = _places(destination_words, here)
    # A link's relative target is read from the directory the link lands in.
    anchors = (
        *here,
        *(posixpath.dirname(place) for place in destinations or ()),
        *(destinations or ()),
    )
    placed: dict[str, None] = {}
    for source in sources:
        found = [
            place
            for anchor in dict.fromkeys(anchors or (None,))
            if (place := _place(source, anchor)) is not None
        ]
        placed.update(dict.fromkeys(found or [_EVERYTHING]))
    return _MadeLink(tuple(placed), destinations, tuple(words))


def _makes_a_link(head: str, arguments: list[str]) -> bool:
    """Does the command make a link: any ``ln``, a ``cp -s``, an ``install -l``?

    A ``cp`` long option is matched by any unambiguous abbreviation (``--sy``),
    as GNU getopt accepts one.
    """
    if head in _LINK_COMMANDS:
        return True
    if head not in (_SYMBOLIC_COPY, _INSTALL):
        return False
    letter = "s" if head == _SYMBOLIC_COPY else _INSTALL_LINK_OPTION[1]
    for word in arguments:
        if word == _END_OF_OPTIONS:
            return False
        name = word.partition("=")[0]
        if head == _SYMBOLIC_COPY and len(name) > 3 and _SYMBOLIC_COPY_LONG.startswith(name):
            return True
        if word.startswith("-") and not word.startswith("--") and letter in word[1:]:
            return True
    return False


def _moved_link(words: list[str], here: tuple[str, ...]) -> _MadeLink | None:
    """What an ``mv`` relocates, judged as a link made where it lands.

    A renamed link keeps its target text, and a relative target is then read
    from the new directory; a moved directory may hold such links. A link or a
    directory that changes directory is judged as leading anywhere; one renamed
    in place, or a plain file, leads where the source does now.
    """
    operands, target_directory = _link_operands(words[1:])
    if target_directory is not None:
        sources, destination_words = operands, [target_directory]
    elif len(operands) >= 2:
        sources, destination_words = operands[:-1], [operands[-1]]
    else:
        return None
    destinations = _places(destination_words, here)
    stays = target_directory is None and len(sources) == 1
    placed: dict[str, None] = {}
    for base in here or (None,):
        for source in sources:
            place = _place(source, base)
            if place is None:
                placed[_EVERYTHING] = None
                continue
            same_parent = (
                stays
                and destinations is not None
                and all(
                    posixpath.dirname(landed) == posixpath.dirname(place) for landed in destinations
                )
            )
            relocates = _may_hold_links(place) and not same_parent
            placed[_EVERYTHING if relocates else place] = None
    return _MadeLink(tuple(placed), destinations, tuple(words))


def _may_hold_links(path: str) -> bool:
    """Is ``path`` a link or a directory (which may hold links)? Unreadable counts."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return stat.S_ISLNK(mode) or stat.S_ISDIR(mode)


def _link_operands(
    arguments: list[str], valued: frozenset[str] = frozenset()
) -> tuple[list[str], str | None]:
    """The operands of an ``ln``/``cp``/``mv``/``hooks-daemon`` command, and its ``-t`` directory.

    ``valued`` names further options that take the next word as their value.
    """
    operands: list[str] = []
    target_directory: str | None = None
    options_ended = False
    skip_value = False
    take_target = False
    for word in arguments:
        if skip_value:
            skip_value = False
            if take_target:
                target_directory = word
            continue
        if options_ended or not word.startswith("-") or word == _LONE_DASH:
            operands.append(word)
        elif word == _END_OF_OPTIONS:
            options_ended = True
        elif word in _TARGET_DIRECTORY_OPTIONS or word in _SUFFIX_OPTIONS or word in valued:
            skip_value, take_target = True, word in _TARGET_DIRECTORY_OPTIONS
        elif word.startswith("--target-directory="):
            target_directory = word.partition("=")[2]
    return operands, target_directory


def _places(words: list[str], here: tuple[str, ...]) -> tuple[str, ...] | None:
    """Where each of ``words`` lies from each of ``here``; None when one cannot be placed."""
    placed: dict[str, None] = {}
    for base in here or (None,):
        for word in words:
            place = _place(word, base)
            if place is None:
                return None
            placed[place] = None
    return tuple(placed)


def _reads_through_made_links(
    words: list[str], segment: str, here: tuple[str, ...], tracker: _SearchCwds
) -> Iterator[Read]:
    """The places earlier-made links lead to, when this statement names where they land.

    Besides the operands, every path-shaped word of the statement counts, split
    as the direct mention scan splits it (re-review R4): a leading or attached
    redirect, ``dd if=``, an interpreter literal, a ``file://`` URL. Any input
    redirect makes the statement a reader, whatever its command: ``$(<file)``
    reads even with no command word, or inside an ``echo``.
    """
    if not tracker.made_links:
        return
    head = posixpath.basename(words[0]) if words else ""
    if words and head in _DIRECTORY_CHANGERS:
        return
    if _INPUT_REDIRECT not in segment and not _runs_a_reader(words):
        return
    recursive = bool(words) and _reads_files(words, head)
    candidates = [*_path_operands(words[1:]), *(["."] if recursive else [])]
    mentioned = path_mention_words(segment)
    named: list[str | None] = []
    for base in here or (None,):
        named.extend(_place(word, base) for word in candidates)
        # A crude word that cannot be placed is not a path operand: it is dropped.
        named.extend(place for word in mentioned if (place := _place(word, base)) is not None)
    for link in tracker.made_links:
        if link.origin == tuple(words):
            continue
        if link.destinations is None or any(
            place is None or any(_overlaps(place, landed) for landed in link.destinations)
            for place in named
        ):
            for source in link.sources:
                yield Read(source, view=TreeView.ALL, physical=True)


def _overlaps(place: str, landed: str) -> bool:
    """Is ``place`` the directory ``landed``, below it, or above it?"""
    return (
        place == landed
        or place.startswith(landed.rstrip("/") + "/")
        or landed.startswith(place.rstrip("/") + "/")
    )


def _reads_from_each(
    roots: tuple[str, ...], bases: tuple[str, ...], *, follows: LinkFollow = LinkFollow.ALL
) -> Iterator[Read]:
    for base in bases or (None,):
        yield from _reads_of_roots(roots, base, follows=follows)


def _could_read(command: str) -> bool:
    """Could any command in ``command``, or in a body nested inside it, read a tree?

    A ``bash -c`` or ``eval`` body is looked into rather than counted as a reader,
    so a harmless body stays harmless however deep; each level is shorter text,
    so this ends.
    """
    for raw, _piped_in in command_segments(command):
        if any(_could_read(body) for body in _substitution_bodies(raw)):
            return True
        for text in dict.fromkeys((raw, _unwrapped(raw)[0])):
            words = _command_words(text)
            if not words:
                continue
            head = posixpath.basename(words[0])
            if head in SHELL_NAMES and _SHELL_COMMAND_FLAG in words[1:-1]:
                inner = words[words.index(_SHELL_COMMAND_FLAG, 1) + 1]
                # A body no shorter than its command is not looked into: it may read.
                if len(inner) >= len(command) or _could_read(inner):
                    return True
                continue
            if head == _EVAL:
                if _could_read(" ".join(words[1:])):
                    return True
                continue
            if _reads_files(words, head):
                return True
    return False


def _reads_files(words: list[str], head: str) -> bool:
    """Could the segment ``words`` read a tree, by any of the routes :func:`_reads` judges?"""
    return (
        head in _FIND_COMMANDS
        or head in (_XARGS, _EVAL)
        or _fd_exec_roots(words) is not None
        or (head in SHELL_NAMES and _SHELL_COMMAND_FLAG in words[1:-1])
        or _directory_reader_roots(words) is not None
        or (_is_search(words) and not _git_reads_no_tree(words))
    )


@dataclass(frozen=True)
class _GitOptionGrammar:
    """The options of one subcommand trusted to print no file content.

    An allowlist, not a denylist of diff options: an option this does not
    name, an abbreviation included, keeps the command a reader.
    """

    flags: frozenset[str]
    long_flags: frozenset[str]
    long_valued: frozenset[str] = frozenset()
    short_valued: frozenset[str] = frozenset()
    # A short option whose value is the rest of its word only (`-uno`).
    short_attached: frozenset[str] = frozenset()
    message_options: frozenset[str] = frozenset()


# Subcommands that read the index and lstat the work tree, never through a link
# (Plan 00623 probes #350/#351). A commit is trusted only with a message
# given, so no editor shows its template, and with no dry run, which under
# `commit.verbose` from any config git reads prints the diff (review 3).
_GIT_TREELESS_GRAMMARS: Final[dict[str, _GitOptionGrammar]] = {
    "status": _GitOptionGrammar(
        flags=frozenset("sbz"),
        short_attached=frozenset("u"),
        long_flags=frozenset(
            {
                "short",
                "branch",
                "porcelain",
                "long",
                "null",
                "show-stash",
                "ahead-behind",
                "no-ahead-behind",
                "untracked-files",
                "ignored",
                "ignore-submodules",
                "column",
                "no-column",
                "renames",
                "no-renames",
                "find-renames",
            }
        ),
    ),
    "commit": _GitOptionGrammar(
        flags=frozenset("aqsn"),
        short_valued=frozenset("mF"),
        long_flags=frozenset(
            {
                "all",
                "quiet",
                "signoff",
                "no-signoff",
                "no-verify",
                "verify",
                "allow-empty",
                "allow-empty-message",
                "amend",
                "no-edit",
                "include",
                "only",
                "reset-author",
                "no-gpg-sign",
            }
        ),
        long_valued=frozenset({"message", "file", "author", "date", "cleanup"}),
        message_options=frozenset({"m", "F", "message", "file"}),
    ),
}
# Global options that change only how git prints.
_GIT_PRINT_ONLY_OPTIONS: Final[frozenset[str]] = frozenset({"--no-pager", "-P"})
# Characters through which bash may turn a word into another (`$V`, `$'-v'`,
# `{-v,-v}`, a glob): a word holding one may become a diff option.
_GIT_NON_LITERAL: Final[re.Pattern[str]] = re.compile(r"[$`*?\[\]{}\\~()!]")


def _git_reads_no_tree(words: list[str]) -> bool:
    """Is ``words`` a ``git commit``/``git status`` that recurses into no tree and prints no file?

    ``git`` is otherwise a possible reader after a computed move, so every
    directory link is judged as a root of it. Only a literal subcommand, after
    print-only global options, with every option in its allowlist and every
    word literal, is trusted; and only in a command naming no variable that
    steers git (``GIT_*``, ``HOME``, an editor). A file operand (``-F``, a
    pathspec) is a word the mention scan resolves through every link from
    every effective cwd, which this does not change.
    """
    if _git_environment_named.get() or posixpath.basename(words[0]) != TOOL_GIT:
        return False
    position = 1
    while position < len(words) and words[position] in _GIT_PRINT_ONLY_OPTIONS:
        position += 1
    if position >= len(words):
        return False
    grammar = _GIT_TREELESS_GRAMMARS.get(words[position])
    if grammar is None:
        return False
    named = _git_options_named(words[position + 1 :], grammar)
    if named is None:
        return False
    return not grammar.message_options or bool(named & grammar.message_options)


def _git_options_named(arguments: list[str], grammar: _GitOptionGrammar) -> set[str] | None:
    """The options ``arguments`` name, or ``None`` when one is outside ``grammar`` or not literal."""
    named: set[str] = set()
    expects_value = False
    for word in arguments:
        if _GIT_NON_LITERAL.search(word):
            return None
        if expects_value:
            expects_value = False
            continue
        if word == _END_OF_OPTIONS:
            break
        if word.startswith("--"):
            name, has_value, _value = word[2:].partition("=")
            if name in grammar.long_valued:
                expects_value = not has_value
            elif name not in grammar.long_flags or (has_value and name not in _GIT_OPTIONAL_VALUED):
                return None
            named.add(name)
        elif word.startswith("-") and len(word) > 1:
            cluster = _git_short_cluster(word[1:], grammar)
            if cluster is None:
                return None
            letters, expects_value = cluster
            named.update(letters)
    return None if expects_value else named


# Long status options whose value is optional and attached (`--porcelain=v2`).
_GIT_OPTIONAL_VALUED: Final[frozenset[str]] = frozenset(
    {
        "porcelain",
        "untracked-files",
        "ignored",
        "ignore-submodules",
        "column",
        "find-renames",
    }
)


def _git_short_cluster(cluster: str, grammar: _GitOptionGrammar) -> tuple[set[str], bool] | None:
    """The letters of a short cluster and whether the next word is its value, or ``None``."""
    letters: set[str] = set()
    for index, letter in enumerate(cluster):
        letters.add(letter)
        if letter in grammar.short_attached:
            return letters, False
        if letter in grammar.short_valued:
            return letters, index == len(cluster) - 1
        if letter not in grammar.flags:
            return None
    return letters, False


def _assigns_a_relocating_variable(segment: str, words: list[str]) -> bool:
    """Does ``segment`` set ``GIT_DIR``/``GIT_WORK_TREE``/... before the command ``words`` run?

    The assignments are the words :func:`_command_words` stripped: those the
    segment holds before its command word, as a prefix or after ``env``.
    """
    try:
        every_word = linear_shlex.split(segment)
    except ValueError:
        return False
    stripped = every_word[: len(every_word) - len(words)]
    return any(
        _ASSIGNMENT.match(word) and word.partition("=")[0] in RELOCATING_VARIABLES
        for word in stripped
    )


def _command_words(segment: str) -> list[str]:
    """The words of the command a segment runs, past assignments and wrappers.

    An unparseable segment yields nothing: the text scan already denies an
    unclosed quote, and nothing here can place its roots.
    """
    try:
        words = linear_shlex.split(segment)
    except ValueError:
        return []
    while True:
        words = _past_command_prefix(words)
        _names, start = peel_command_wrappers(words)
        if start == 0:
            return words
        # ``env VAR=x rg ...``: assignments can follow a wrapper too.
        words = words[start:]


def _past_command_prefix(words: list[str]) -> list[str]:
    """``words`` from the command name: past assignments, redirections and ``builtin``.

    Review 614b R3: ``>/dev/null cd x`` and ``builtin cd x`` run ``cd``.
    """
    while words:
        head = words[0]
        if head == _EXEC:
            # Review D4: `exec [-cl] [-a NAME] cmd` runs cmd.
            words = words[1:]
            while words and words[0].startswith("-") and words[0] != "-":
                words = words[2:] if words[0] == _EXEC_NAME_OPTION else words[1:]
        elif _ASSIGNMENT.match(head) or head == _BUILTIN or _REDIRECTION_WORD.fullmatch(head):
            words = words[1:]
        elif _BARE_REDIRECTION.fullmatch(words[0]):
            words = words[2:]
        else:
            break
    return words


def _operands(words: list[str]) -> list[str]:
    """The words of ``words`` that are operands: not options, redirections or their files."""
    operands: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if _BARE_REDIRECTION.fullmatch(word):
            index += 2
            continue
        if not _REDIRECTION_WORD.fullmatch(word) and (not word.startswith("-") or word == "-"):
            operands.append(word)
        index += 1
    return operands


def _is_search(words: list[str]) -> bool:
    """Is the command's own head a grep-family tool (not a word that merely follows)?"""
    head = posixpath.basename(words[0])
    return head in _GREP_COMMANDS or head in _RG_COMMANDS or head == TOOL_GIT


def _search_reads(
    words: list[str], cwd: str | None, *, piped_in: bool, relocating_env: bool = False
) -> Iterator[Read]:
    """The trees one grep-family command reads, if it recurses."""
    found = search_command(words)
    if found is None:
        return
    tool, start, _relocated = found
    scan = scan_options(
        words[start:], tool=tool, command=words[start - 1], rg_config=_rg_config_named.get()
    )
    if not scan.recursive:
        return
    if tool == TOOL_GIT:
        yield from _relocated_git_grep_reads(words, start, scan, cwd, relocating_env)
        return
    roots = tuple(scan.operands)
    if scan.default_root_possible and not (tool == TOOL_RG and piped_in):
        roots = (*roots, ".")
    rules = (
        _NO_RULES
        if scan.uncertain
        else _tool_rules(posixpath.basename(words[0]), words[start:], scan)
    )
    follows = _search_link_follow(posixpath.basename(words[start - 1]), words[start:], scan)
    yield from _reads_of_roots(roots, cwd, rules, follows=follows)


def _relocated_git_grep_reads(
    words: list[str], start: int, scan: SearchArguments, cwd: str | None, relocating_env: bool
) -> Iterator[Read]:
    """The trees a ``git grep`` reads once git's global options have moved it.

    A literal ``-C`` is judged as the ``cd`` it equals. A move that cannot be
    placed (an expansion, ``--git-dir``, ``core.worktree``, a relocating
    environment variable) fails closed: every indexed file is read.
    """
    placement = git_placement(words, cwd)
    if placement.unplaceable or relocating_env:
        yield Read(_EVERYTHING, view=TreeView.ALL)
        return
    yield from _git_grep_reads(words[start:], scan, placement.directory, foreign=placement.foreign)
    for tree in placement.work_trees:
        yield Read(tree, view=TreeView.ALL)


def _git_grep_reads(
    arguments: list[str], scan: SearchArguments, cwd: str | None, *, foreign: bool = False
) -> Iterator[Read]:
    """The trees ``git grep`` reads: tracked files, or the working tree with ``--no-index``.

    Operands before a ``--`` are revisions and pathspecs are the words after it;
    with no ``--`` an operand is a path only if it exists. A pathspec carrying
    magic (``:(exclude)``) cannot be placed and is left out, so the search is
    judged over the rest. ``foreign`` (a moved work tree) reads every file,
    because the project's index does not say what that tree tracks.
    """
    if any(unknown_tilde(word) for word in arguments):
        # A pathspec or path under `~-`/`~+` names a tree the hook cannot place: fail closed.
        yield Read(_EVERYTHING, view=TreeView.ALL)
        return
    # `--untracked` is really tracked plus non-ignored untracked files; ALL is the safe superset.
    view = (
        TreeView.ALL
        if foreign or any(word in _GIT_GREP_WORKING_TREE_FLAGS for word in arguments)
        else TreeView.TRACKED
    )
    if _END_OF_OPTIONS in arguments:
        candidates = arguments[arguments.index(_END_OF_OPTIONS) + 1 :]
    else:
        candidates = [operand for operand in scan.operands if _exists(operand, cwd)]
    roots = tuple(c for c in candidates if not c.startswith(_PATHSPEC_MAGIC_PREFIX))
    if not roots or scan.default_root_possible:
        roots = (*roots, ".")
    # git reads a tracked link as a link; only a working-tree read is not proven so.
    follows = LinkFollow.ALL if view is TreeView.ALL else LinkFollow.NONE
    for root in _placed(roots, cwd):
        yield Read(root, view=view, follows=follows)


def _exists(operand: str, cwd: str | None) -> bool:
    placed = _place(operand, cwd)
    return placed is not None and os.path.lexists(placed)


def _find_roots(words: list[str]) -> tuple[str, ...]:
    """The starting points of a ``find`` command (``.`` when it names none)."""
    roots: list[str] = []
    for word in words[1:]:
        if word in _FIND_LEADING_OPTIONS and not roots:
            continue
        if word.startswith("-") or word in _FIND_EXPRESSION_STARTS:
            break
        roots.append(word)
    return tuple(roots) or (".",)


def _find_execs_a_reader(words: list[str]) -> bool:
    """Does any ``-exec``-style action of a ``find`` command run a reader on what it finds?"""
    for index, word in enumerate(words):
        if word not in FIND_EXEC_ACTIONS:
            continue
        end = find_exec_end(words, index + 1)
        if _runs_a_reader(words[index + 1 : end]):
            return True
    return False


def _fd_exec_roots(words: list[str]) -> tuple[str, ...] | None:
    """Where ``fd`` walks when it runs a reader on each file, or None when it does not.

    ``fd [OPTIONS] [PATTERN] [PATH]...``: the first operand is the pattern, the
    rest (and each ``--search-path``) are roots, and with none it walks the
    current directory. ``-x``/``--exec`` and ``-X``/``--exec-batch`` take a
    command up to ``;``. An option this does not know is read as an operand,
    which can only add a root.
    """
    if posixpath.basename(words[0]) not in _FD_COMMANDS:
        return None
    operands: list[str] = []
    searched: list[str] = []
    base = ""
    runs_reader = False
    index = 1
    while index < len(words):
        word = words[index]
        index += 1
        if word == _END_OF_OPTIONS:
            operands.extend(words[index:])
            break
        command_start = _fd_exec_start(word)
        if command_start is not None:
            first = [command_start] if command_start else []
            end = next(
                (i for i in range(index, len(words)) if words[i] == _FD_EXEC_TERMINATOR),
                len(words),
            )
            runs_reader = runs_reader or _runs_a_reader([*first, *words[index:end]])
            index = end + 1
        elif word in (_FD_SEARCH_PATH, _FD_BASE_DIRECTORY) and index < len(words):
            if word == _FD_SEARCH_PATH:
                searched.append(words[index])
            else:
                base = words[index]
            index += 1
        elif word.startswith(_FD_SEARCH_PATH + "="):
            searched.append(word.partition("=")[2])
        elif word.startswith(_FD_BASE_DIRECTORY + "="):
            base = word.partition("=")[2]
        elif word in _FD_VALUE_OPTIONS:
            index += 1
        elif not word.startswith("-") or word == _LONE_DASH:
            operands.append(word)
    if not runs_reader:
        return None
    roots = (*operands[1:], *searched) or (".",)
    return tuple(posixpath.join(base, root) for root in roots) if base else roots


def _fd_exec_start(word: str) -> str | None:
    """The first word of the command an ``fd`` option runs, ``""`` when it follows, else None.

    ``-x``, ``-X`` (also clustered, ``-uX``), ``--exec`` and ``--exec-batch`` take
    the command from the next words; ``--exec=cat`` carries its first word.
    """
    if word.startswith("--"):
        name, equals, value = word.partition("=")
        if name not in _FD_EXEC_LONG:
            return None
        return value if equals else ""
    if word.startswith("-") and len(word) > 1 and word[1:].isalpha() and word[-1] in "xX":
        return ""
    return None


def _xargs_command(words: list[str]) -> list[str]:
    """The command ``xargs`` runs: the words after its own options."""
    index = 1
    while index < len(words) and words[index].startswith("-"):
        takes_value = words[index] in _XARGS_VALUE_FLAGS | _XARGS_LONG_VALUE_FLAGS
        index += 2 if takes_value else 1
    return words[index:]


# --- Readers of a whole directory that are not a search -----------------------------------------
#
# A command that hands a directory to `find -exec`, `xargs`, an archiver, a copier or a
# directory diff puts every file under it into its output, whatever flags it carries. The
# rule is fail closed: only a command on the short allowlist below is known to open no file
# for its content, so every other command word (an unresolvable one, a wrapper around
# nothing, a shell, an interpreter) counts as a reader of every root it is handed.

_XARGS_LONG_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--arg-file",
        "--delimiter",
        "--max-args",
        "--max-procs",
        "--max-lines",
        "--max-chars",
        "--eof",
        "--process-slot-var",
    }
)
# Matched on the exact bare word: `./ls` and `/tmp/ls` are not `ls`.
_CONTENT_FREE_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "echo",
        "printf",
        "true",
        "false",
        "ls",
        "stat",
        "basename",
        "dirname",
        "test",
        "[",
        "rm",
        "rmdir",
        "chmod",
        "chown",
        "touch",
        "mkdir",
    }
)
_DIFF_COMMANDS: Final[frozenset[str]] = frozenset({"diff", "sdiff", "diff3", "colordiff"})
_ARCHIVE_COMMANDS: Final[frozenset[str]] = frozenset({"zip", "7z", "7za", "7zr"})
_TAR_COMMANDS: Final[frozenset[str]] = frozenset({"tar", "gtar", "bsdtar"})
# The last operand of these is where the copy goes, which is not read.
_COPY_COMMANDS: Final[frozenset[str]] = frozenset({"cp", "rsync", "scp"})
_CP: Final[str] = "cp"
_COPY_TARGET_DIRECTORY_OPTION: Final[str] = "--target-directory"
_TAR_DIRECTORY_OPTIONS: Final[frozenset[str]] = frozenset({"-C", "--directory"})
_GIT_DIFF_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"diff", "difftool"})
_GIT_NO_INDEX_FLAG: Final[str] = "--no-index"
_LONE_DASH: Final[str] = "-"
_PARENT: Final[str] = ".."
_LONG_OPTION_PREFIX: Final[str] = "--"


def _runs_a_reader(command: list[str]) -> bool:
    """Does the command a ``find -exec`` or ``xargs`` runs possibly open what it is handed?

    An empty command runs nothing (``xargs`` alone runs ``echo``). A command made only of
    wrappers has no command word to prove harmless, so it counts.
    """
    if not command:
        return False
    _wrappers, start = peel_command_wrappers(command)
    if start >= len(command):
        return True
    return command[start] not in _CONTENT_FREE_COMMANDS


def _directory_reader_roots(words: list[str]) -> tuple[str, ...] | None:
    """The paths a directory-reading command is handed, or None when it is not one.

    Every path operand counts, whatever the flags: ``diff a b`` compares the files of two
    directories without ``-r``, and an archiver takes a directory whole. An option's value
    is counted too (it costs nothing when it names no directory with a protected file).
    ``git diff --no-index`` is the only ``git`` form here: without it the diff reads
    history and the index, which this module does not judge.
    """
    head = posixpath.basename(words[0])
    arguments = words[1:]
    if head in _DIFF_COMMANDS or head in _ARCHIVE_COMMANDS:
        return tuple(_path_operands(arguments))
    if head in _TAR_COMMANDS:
        return _tar_roots(arguments)
    if head in _COPY_COMMANDS:
        return _copy_sources(head, arguments)
    if head == TOOL_GIT:
        return _git_no_index_roots(arguments)
    return None


def _path_operands(arguments: list[str]) -> list[str]:
    """The words of ``arguments`` that can be a path: operands, and values attached to ``--opt=``."""
    operands: list[str] = []
    options_ended = False
    for word in arguments:
        if options_ended:
            operands.append(word)
        elif word == _END_OF_OPTIONS:
            options_ended = True
        elif word.startswith(_LONG_OPTION_PREFIX):
            _option, equals, value = word.partition("=")
            if equals and value:
                operands.append(value)
        elif word != _LONE_DASH and not word.startswith("-"):
            operands.append(word)
    return operands


def _copy_sources(command: str, arguments: list[str]) -> tuple[str, ...]:
    """The operands of ``cp``/``rsync``/``scp`` that are read: all but the destination.

    The destination is the ``-t``/``--target-directory`` value of ``cp`` (for ``rsync``
    ``-t`` is ``--times``, which takes no value), else the last operand; a lone operand
    is judged (the command is malformed or reads it).
    """
    operands: list[str] = []
    destination_is_option = False
    skip_next = False
    for word in arguments:
        if skip_next:
            skip_next = False
            continue
        is_short_target = (
            command == _CP
            and word.startswith("-")
            and not word.startswith(_LONG_OPTION_PREFIX)
            and word.endswith("t")
        )
        if (word == _COPY_TARGET_DIRECTORY_OPTION and command == _CP) or is_short_target:
            destination_is_option = True
            skip_next = True
        elif command == _CP and word.startswith(_COPY_TARGET_DIRECTORY_OPTION + "="):
            destination_is_option = True
        else:
            operands.extend(_path_operands([word]))
    if not destination_is_option and len(operands) > 1:
        operands = operands[:-1]
    return tuple(operands)


def _tar_roots(arguments: list[str]) -> tuple[str, ...]:
    """The paths ``tar`` reads, each placed under the ``-C`` directory in force where it stands.

    A leading bundle without a dash (``tar cf - deep``) is the mode, not a path.
    """
    roots: list[str] = []
    base: str | None = None
    words = arguments[1:] if arguments and not arguments[0].startswith("-") else arguments
    index = 0
    while index < len(words):
        word = words[index]
        directory: str | None = None
        if word in _TAR_DIRECTORY_OPTIONS and index + 1 < len(words):
            directory = words[index + 1]
            index += 1
        elif word.startswith("--directory="):
            directory = word.partition("=")[2]
        elif word.startswith("-C") and not word.startswith(_LONG_OPTION_PREFIX) and len(word) > 2:
            directory = word[2:]
        if directory is not None:
            base = _under(base, directory)
            roots.append(base)
        else:
            roots.extend(_under(base, operand) for operand in _path_operands([word]))
        index += 1
    return tuple(roots)


def _git_no_index_roots(arguments: list[str]) -> tuple[str, ...] | None:
    """The two paths of ``git diff --no-index``, or None for any other ``git`` command."""
    base: str | None = None
    position = 0
    while position < len(arguments) and arguments[position].startswith("-"):
        option = arguments[position]
        if option == "-C" and position + 1 < len(arguments):
            base = _under(base, arguments[position + 1])
        position += 2 if option in _GIT_OPTIONS_TAKING_VALUE else 1
    if position >= len(arguments) or arguments[position] not in _GIT_DIFF_SUBCOMMANDS:
        return None
    rest = arguments[position + 1 :]
    if _GIT_NO_INDEX_FLAG not in rest:
        return None
    return tuple(_under(base, operand) for operand in _path_operands(rest))


def _under(base: str | None, path: str) -> str:
    """``path`` read from ``base``: unchanged when absolute or when there is no base."""
    if base is None or posixpath.isabs(path):
        return path
    return posixpath.join(base, path)


def _place(
    root: str, cwd: str | None, *, unplaceable: re.Pattern[str] = _UNPLACEABLE_ROOT
) -> str | None:
    """The absolute, normalised form of ``root``, or None when it cannot be placed."""
    anchored = _anchored(root, cwd, unplaceable)
    return None if anchored is None else posixpath.normpath(anchored)


_TILDE: Final[str] = "~"
_TILDE_SHELL_STATE: Final[tuple[str, ...]] = ("+", "-")


def expand_tilde(word: str) -> str | None:
    """``word`` with a ``~`` or ``~user`` prefix expanded; None when the hook cannot place it.

    Plan 00618 S-1 second review: ``Path('~+').expanduser()`` raises, reading
    ``+`` as a user name. Bash expands ``~+``, ``~-``, ``~N``, ``~+N`` and
    ``~-N`` from the shell's own state ($PWD, $OLDPWD, the directory stack),
    and an unknown ``~user`` is left as written: every one of them fails closed.
    """
    if not word.startswith(_TILDE):
        return word
    name = word.partition("/")[0][1:]
    if name.startswith(_TILDE_SHELL_STATE) or name.isdigit():
        return None
    expanded = posixpath.expanduser(word)
    return None if expanded.startswith(_TILDE) else expanded


def unknown_tilde(word: str) -> bool:
    """Does ``word`` start with a tilde this hook cannot place (``~+``, ``~-``, ``~2``)?"""
    return expand_tilde(word) is None


def _anchored(root: str, cwd: str | None, unplaceable: re.Pattern[str]) -> str | None:
    """``root`` made absolute but not normalised (``a/link/..`` keeps its ``..``)."""
    if unplaceable.search(root):
        return None
    expanded = expand_tilde(root)
    if expanded is None:
        return None
    if not posixpath.isabs(expanded):
        if cwd is None or not posixpath.isabs(cwd):
            return None
        expanded = posixpath.join(cwd, expanded)
    return expanded


def _physical_root(root: str, cwd: str | None) -> str | None:
    """Where a root with a ``..`` really points once the links before it are followed.

    ``normpath`` removes ``link/..`` as if it were the link's parent; a command's own path
    lookup steps out of the link's TARGET. None when the root has no ``..`` (the lexical
    form is then the whole answer: a link as the root itself is resolved by the index).
    """
    if _PARENT not in root.split("/"):
        return None
    anchored = _anchored(root, cwd, _UNPLACEABLE_ROOT)
    return None if anchored is None else os.path.realpath(anchored)


def _placed(roots: tuple[str, ...], cwd: str | None) -> list[str]:
    """The distinct placeable roots, in order."""
    placed: list[str] = []
    for root in roots:
        absolute = _place(root, cwd)
        if absolute is not None and absolute not in placed:
            placed.append(absolute)
    return placed


def _place_directory_glob(root: str, cwd: str | None) -> str | None:
    """The absolute form of a glob root, or None when ``root`` is not one.

    A glob ending in ``/`` expands to directories only. One without it can expand to a
    directory too, and a recursive reader follows that, so both are placed the same way.
    A glob carrying a variable, a substitution or a brace is not placed, as for any
    other root.
    """
    if not _DIRECTORY_GLOB.search(root) or _EXPANSION_ROOT.search(root):
        return None
    placed = _place(root, cwd, unplaceable=_EXPANSION_ROOT)
    return None if placed is None else placed.rstrip("/") + "/"


def _view_for(rules: _Rules) -> TreeView:
    return TreeView.UNIGNORED if rules.honour_ignore else TreeView.ALL


def _brace_spellings(roots: tuple[str, ...]) -> tuple[str, ...]:
    """``roots`` with each brace operand replaced by the words bash expands it to.

    The shell expands ``{conf,docs}`` before any search sees it, so the search
    reads each spelling: a file read judges them the same way. Raises
    :class:`TooManyToEnumerateError` when one cannot be listed.
    """
    spelled: dict[str, None] = {}
    for root in roots:
        if _BRACE_OPEN not in root:
            spelled[root] = None
            continue
        spelled.update(dict.fromkeys(expand_braces(root)))
    return tuple(spelled)


def _reads_of_roots(
    roots: tuple[str, ...],
    cwd: str | None,
    rules: _Rules = _NO_RULES,
    *,
    follows: LinkFollow = LinkFollow.ALL,
) -> Iterator[Read]:
    unlistable = False
    try:
        roots = _brace_spellings(roots)
    except TooManyToEnumerateError as exc:
        log_and_continue(
            logger,
            exc,
            reason="a brace operand that cannot be listed (past the cap, or quoting that "
            "hides a group) fails closed: every indexed file is judged",
            level=logging.DEBUG,
        )
        unlistable = True
    if unlistable:
        yield Read(_EVERYTHING, view=TreeView.ALL, follows=follows)
        return
    if any(unknown_tilde(root) for root in roots):
        # `~-`/`~N` is a real directory this hook cannot see: judge every indexed file.
        yield Read(_EVERYTHING, view=TreeView.ALL, follows=follows)
    for root in roots:
        glob_root = _place_directory_glob(root, cwd)
        if glob_root is not None:
            # Answered from the index when judged: no directory is listed here. The shell
            # expands it to command-line operands, which every reader follows, so it is
            # judged as following every link below its literal directory.
            yield Read(glob_root, view=_view_for(rules), glob=True, rules=rules)
    placed = _placed(roots, cwd)
    for root in placed:
        yield Read(root, view=_view_for(rules), skip=rules.predicate(root), follows=follows)
    for root in roots:
        physical = _physical_root(root, cwd)
        if physical is not None and physical not in placed:
            yield Read(
                physical,
                view=_view_for(rules),
                skip=rules.predicate(physical),
                follows=follows,
                physical=True,
            )


# --- Which links below its roots a reader follows (Plan 00613) -----------------------------------
#
# Every reader follows every link unless its own options prove otherwise: a miss here is a
# protected file read through a seeded link, so only the shapes below are proven not to.

#: Short options that make a grep-family tool follow every link it meets while recursing
#: (``S`` too for grep: BSD grep's ``-S`` follows every link under ``-r``).
_GREP_FOLLOW_SHORT: Final[dict[str, str]] = {
    "grep": "RS",
    "egrep": "RS",
    "fgrep": "RS",
    "zgrep": "RS",
    "ugrep": "RS",
    "ug": "RS",
    "rg": "L",
    "ag": "f",
}
#: Long options (and any abbreviation of them) that make one follow links.
_FOLLOW_LONG: Final[tuple[str, ...]] = (
    "--dereference-recursive",
    "--dereference-files",
    "--dereference",
    "--follow",
)
#: Words that let a command change what a later ``grep``/``rg`` word runs or reads.
_FOLLOW_STEERING: Final[re.Pattern[str]] = re.compile(
    r"GREP_OPTIONS|\(\s*\)|\bfunction\b|\balias\b"
)


def _search_link_follow(tool: str, arguments: list[str], scan: SearchArguments) -> LinkFollow:
    """Which links a grep-family search follows; ALL unless its words prove it follows none.

    ``grep -r``, ``rg`` and ``ag`` skip every link below their roots (a root named on
    the command line is resolved by :meth:`ProtectedFileIndex.find_under` itself).
    An option that could be a follow flag, an abbreviation of one, an uncertain parse,
    a ripgrep config, or a command that defines a function or alias proves nothing.
    """
    shorts = _GREP_FOLLOW_SHORT.get(tool)
    steered = _follow_steering_named.get()
    if shorts is None or scan.uncertain or steered or _rg_config_named.get():
        return LinkFollow.ALL
    for word in arguments:
        if word == _END_OF_OPTIONS:
            break
        if word.startswith("--"):
            name = word.partition("=")[0]
            if len(name) > 2 and any(
                full.startswith(name) or name.startswith(full) for full in _FOLLOW_LONG
            ):
                return LinkFollow.ALL
        elif word.startswith("-") and any(flag in word[1:] for flag in shorts):
            return LinkFollow.ALL
    return LinkFollow.NONE
