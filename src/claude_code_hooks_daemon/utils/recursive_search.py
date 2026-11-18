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
import os
import posixpath
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from claude_code_hooks_daemon.utils import linear_shlex
from claude_code_hooks_daemon.utils.bash_flags import SPAN_SEPARATORS, split_statements
from claude_code_hooks_daemon.utils.command_evasion import GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE
from claude_code_hooks_daemon.utils.command_position import SHELL_NAMES
from claude_code_hooks_daemon.utils.find_expression import FIND_EXEC_ACTIONS, find_exec_end
from claude_code_hooks_daemon.utils.git_repo import RELOCATING_VARIABLES
from claude_code_hooks_daemon.utils.grep_option_grammar import (
    RG_CONFIG_ENV,
    grammar_for,
    parse_arguments,
)
from claude_code_hooks_daemon.utils.protected_file_index import (
    ExemptHook,
    ProtectedFileIndex,
    TreeView,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    peel_command_wrappers,
    split_unquoted_spans,
)
from claude_code_hooks_daemon.utils.shell_snapshot import default_glob_semantics

# Whether the command being read names the ripgrep config variable; set by
# :func:`search_reads` for the duration of one read, so the nested readers see it.
_rg_config_named: Final[contextvars.ContextVar[bool]] = contextvars.ContextVar(
    "rg_config_named", default=False
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
_FIND: Final[str] = "find"
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


def search_reads(command: str, cwd: str | None) -> list[Read]:
    """Every tree a recursive search anywhere in ``command`` reads.

    Relative roots are placed from ``cwd``, moved by any literal ``cd`` that
    precedes the search; with no absolute directory to place them from they are
    left out, because a guess at where a search reads is worse than no answer.
    """
    reset = _rg_config_named.set(RG_CONFIG_ENV in command)
    try:
        reads = list(_reads(command, cwd, 0))
    finally:
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

    ``is_exempt`` skips a protected file the caller confirmed safe to read.
    """
    for read in reads:
        for searched in _directories_read(read, index):
            hit = index.find_under(
                searched.root, view=searched.view, skip=searched.skip, is_exempt=is_exempt
            )
            if hit is not None:
                return hit, searched.root
    return None


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


def _reads(command: str, cwd: str | None, depth: int) -> Iterator[Read]:
    """Every tree a search anywhere in ``command`` reads."""
    if depth > _MAX_WRAPPER_DEPTH:
        return
    feeder: tuple[str, ...] | None = None
    current = cwd
    # A `cd ~-` (a tilde the hook cannot place) loses the directory: every later read fails closed.
    lost = False
    for segment, piped_in in command_segments(command):
        words = _command_words(segment)
        fed_by = feeder if piped_in else None
        # A stage that is not a `find` passes the producer's roots on (`find d | sort | xargs cat`).
        feeder = fed_by
        if not words:
            continue
        relocating_env = _assigns_a_relocating_variable(segment, words)
        head = posixpath.basename(words[0])
        if lost and head not in _DIRECTORY_CHANGERS and _reads_files(words, head):
            yield Read(_EVERYTHING, view=TreeView.ALL)
        if head in _DIRECTORY_CHANGERS:
            lost = lost or any(unknown_tilde(word) for word in words[1:])
            current = _after_directory_change(words, current)
        elif head in SHELL_NAMES and _SHELL_COMMAND_FLAG in words[1:-1]:
            inner = words[words.index(_SHELL_COMMAND_FLAG, 1) + 1]
            yield from _reads(inner, current, depth + 1)
        elif head == _EVAL:
            yield from _reads(" ".join(words[1:]), current, depth + 1)
        elif head == _FIND:
            feeder = _find_roots(words)
            if _find_execs_a_reader(words):
                yield from _reads_of_roots(feeder, current)
        elif head == _XARGS:
            inner_words = _xargs_command(words)
            if inner_words and _is_search(inner_words):
                yield from _search_reads(inner_words, current, piped_in=True)
            if _runs_a_reader(inner_words):
                # Fed by `find`, xargs reads what `find` lists. Fed by anything else the paths are
                # unknown, so the tree it runs in is judged.
                yield from _reads_of_roots(fed_by or (".",), current)
        elif (directory_roots := _directory_reader_roots(words)) is not None:
            yield from _reads_of_roots(directory_roots, current)
        elif _is_search(words):
            yield from _search_reads(
                words, current, piped_in=piped_in, relocating_env=relocating_env
            )


def _reads_files(words: list[str], head: str) -> bool:
    """Could the segment ``words`` read a tree, by any of the routes :func:`_reads` judges?"""
    return (
        head in (_FIND, _XARGS, _EVAL)
        or (head in SHELL_NAMES and _SHELL_COMMAND_FLAG in words[1:-1])
        or _directory_reader_roots(words) is not None
        or _is_search(words)
    )


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
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        _names, start = peel_command_wrappers(words)
        if start == 0:
            return words
        # ``env VAR=x rg ...``: assignments can follow a wrapper too.
        words = words[start:]


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
    yield from _reads_of_roots(roots, cwd, rules)


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
    for root in _placed(roots, cwd):
        yield Read(root, view=view)


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


def _reads_of_roots(
    roots: tuple[str, ...], cwd: str | None, rules: _Rules = _NO_RULES
) -> Iterator[Read]:
    if any(unknown_tilde(root) for root in roots):
        # `~-`/`~N` is a real directory this hook cannot see: judge every indexed file.
        yield Read(_EVERYTHING, view=TreeView.ALL)
    for root in roots:
        glob_root = _place_directory_glob(root, cwd)
        if glob_root is not None:
            # Answered from the index when judged: no directory is listed here.
            yield Read(glob_root, view=_view_for(rules), glob=True, rules=rules)
    placed = _placed(roots, cwd)
    for root in placed:
        yield Read(root, view=_view_for(rules), skip=rules.predicate(root))
    for root in roots:
        physical = _physical_root(root, cwd)
        if physical is not None and physical not in placed:
            yield Read(physical, view=_view_for(rules), skip=rules.predicate(physical))
