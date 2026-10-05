"""Recursive searches that read a tree without naming a file in it (Plan 00483, D1).

``grep -r x .``, ``rg x``, ``find . | xargs rg x`` and ``git grep x`` read
every file under their roots, so a protected file or a quarantined DETAIL
artefact is disclosed although no word of the command names it. The text scan
of a command cannot see that; this module finds the roots such a command reads,
and which files the tool reads under them (:class:`TreeView`), and asks the
protected-file index (:mod:`protected_file_index`) whether any of them is
protected. The answer is a lookup in memory: nothing here walks the filesystem.

The roots are placed from the directory the command runs in, which follows a
literal ``cd`` earlier in the command. A root that cannot be placed (a variable,
a glob, a ``cd`` whose target is computed) is not judged.

The option reader (:func:`search_command`, :func:`scan_options`) and the
command splitter (:func:`command_segments`) live here because
``flaggable_content_channel_guard`` reads the same commands for the same
reason, and two readers of one grammar drift.

Scope, deliberately: literal spellings. A search hidden behind an obfuscated
command word (``g\\rep``, ``"grep"``, ``$G``) is dismissed (ledger 00474 N152),
and a producer other than ``find`` feeding ``xargs`` names no root.
"""

import fnmatch
import os
import posixpath
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils import linear_shlex
from claude_code_hooks_daemon.utils.bash_flags import SPAN_SEPARATORS, split_statements
from claude_code_hooks_daemon.utils.protected_file_index import (
    ExemptHook,
    ProtectedFileIndex,
    TreeView,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    peel_command_wrappers,
    split_unquoted_spans,
)

TOOL_GREP: Final[str] = "grep"
TOOL_RG: Final[str] = "rg"
TOOL_GIT: Final[str] = "git"

# grep-like: recursive only when asked (-r, -R, --recursive, -d recurse).
_GREP_COMMANDS: Final[frozenset[str]] = frozenset({"grep", "egrep", "fgrep", "zgrep", "ugrep"})
# rg-like: recursive by default, and read piped stdin instead when given no root.
_RG_COMMANDS: Final[frozenset[str]] = frozenset({"rg", "ag", "ack"})
# Global git options that move the search somewhere the payload cwd does not describe.
_GIT_RELOCATING_OPTIONS: Final[frozenset[str]] = frozenset({"-C", "--git-dir", "--work-tree"})
_GIT_OPTIONS_TAKING_VALUE: Final[frozenset[str]] = frozenset(
    {"-c", "--namespace", "--exec-path"} | _GIT_RELOCATING_OPTIONS
)
_PATTERN_OPTIONS: Final[frozenset[str]] = frozenset({"-e", "-f", "--regexp", "--file"})
# Options whose value is the next word; without this the value would be read
# as the pattern or as a search root.
_OPTIONS_TAKING_VALUE: Final[frozenset[str]] = frozenset(
    {
        "-A", "-B", "-C", "-m", "-d", "-D", "-g", "-t", "-T", "-j", "-M",
        "--after-context", "--before-context", "--context", "--max-count",
        "--directories", "--devices", "--include", "--exclude", "--exclude-dir",
        "--exclude-from", "--glob", "--iglob", "--type", "--type-not", "--color", "--label",
    }
)  # fmt: skip
_RECURSIVE_LONG_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--recursive", "--dereference-recursive"}
)
_GLOB_OPTIONS: Final[frozenset[str]] = frozenset({"-g", "--glob", "--iglob"})
_DIRECTORIES_OPTIONS: Final[frozenset[str]] = frozenset({"-d", "--directories"})
_EXCLUDE_DIR_OPTION: Final[str] = "--exclude-dir"
_EXCLUDE_OPTION: Final[str] = "--exclude"
_NEGATION: Final[str] = "!"
_END_OF_OPTIONS: Final[str] = "--"

_SHELLS: Final[frozenset[str]] = frozenset({"bash", "sh", "dash", "zsh", "ksh"})
_SHELL_COMMAND_FLAG: Final[str] = "-c"
_EVAL: Final[str] = "eval"
_XARGS: Final[str] = "xargs"
_XARGS_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J"}
)
_FIND: Final[str] = "find"
_FIND_EXEC_FLAGS: Final[frozenset[str]] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_EXEC_TERMINATORS: Final[frozenset[str]] = frozenset({";", "+"})
_FIND_LEADING_OPTIONS: Final[frozenset[str]] = frozenset({"-H", "-L", "-P"})
_FIND_EXPRESSION_STARTS: Final[frozenset[str]] = frozenset({"(", "!", ")"})
# git grep reads the working tree instead of the index with either of these.
_GIT_GREP_WORKING_TREE_FLAGS: Final[frozenset[str]] = frozenset({"--no-index", "--untracked"})
_PATHSPEC_MAGIC_PREFIX: Final[str] = ":"
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# A root carrying any of these is not one directory the command line names.
_UNPLACEABLE_ROOT: Final[re.Pattern[str]] = re.compile(r"[$`*?\[{]")


@dataclass
class SearchArguments:
    """What a grep-family invocation's arguments say about where it searches."""

    recursive: bool
    operands: list[str] = field(default_factory=list)
    exclude_dirs: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    pattern_given: bool = False

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
            position = index + 1
            relocated = False
            while position < len(words) and words[position].startswith("-"):
                option = words[position].partition("=")[0]
                relocated = relocated or option in _GIT_RELOCATING_OPTIONS
                position += 2 if words[position] in _GIT_OPTIONS_TAKING_VALUE else 1
            if position < len(words) and words[position] == "grep":
                return TOOL_GIT, position + 1, relocated
            return None
    return None


def scan_options(arguments: list[str], *, tool: str) -> SearchArguments:
    """Read options and operands of a grep-family invocation's arguments."""
    scan = SearchArguments(recursive=tool != TOOL_GREP)
    pending: str | None = None
    options_ended = False
    for word in arguments:
        if pending is not None:
            scan.take_value(pending, word)
            pending = None
        elif options_ended or not word.startswith("-") or word == "-":
            scan.operands.append(word)
        elif word == _END_OF_OPTIONS:
            options_ended = True
        elif word.startswith("--"):
            name, has_value, value = word.partition("=")
            scan.recursive = scan.recursive or name in _RECURSIVE_LONG_OPTIONS
            scan.pattern_given = scan.pattern_given or name in _PATTERN_OPTIONS
            if name in _OPTIONS_TAKING_VALUE or name in _PATTERN_OPTIONS:
                if has_value:
                    scan.take_value(name, value)
                else:
                    pending = name
        else:
            cluster = word[1:]
            for offset, char in enumerate(cluster):
                option = f"-{char}"
                if char in "rR":
                    scan.recursive = True
                elif option in _PATTERN_OPTIONS or option in _OPTIONS_TAKING_VALUE:
                    scan.pattern_given = scan.pattern_given or option in _PATTERN_OPTIONS
                    attached = cluster[offset + 1 :]
                    if attached:
                        scan.take_value(option, attached)
                    else:
                        pending = option
                    break
    if not scan.pattern_given and scan.operands:
        scan.operands = scan.operands[1:]
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
    ``skip`` is the hook for hidden and excluded entries.
    """

    root: str
    view: TreeView = TreeView.ALL
    skip: Callable[[str, bool], bool] | None = None


def search_reads(command: str, cwd: str | None) -> list[Read]:
    """Every tree a recursive search anywhere in ``command`` reads.

    Relative roots are placed from ``cwd``, moved by any literal ``cd`` that
    precedes the search; with no absolute directory to place them from they are
    left out, because a guess at where a search reads is worse than no answer.
    """
    return list(_reads(command, cwd, 0))


def protected_reached(
    reads: Sequence[Read], index: ProtectedFileIndex, *, is_exempt: ExemptHook | None = None
) -> tuple[str, str] | None:
    """``(pattern, searched root)`` when one of ``reads`` reaches a protected file in ``index``.

    ``is_exempt`` skips a protected file the caller confirmed safe to read.
    """
    for read in reads:
        hit = index.find_under(read.root, view=read.view, skip=read.skip, is_exempt=is_exempt)
        if hit is not None:
            return hit, read.root
    return None


# Nested wrappers (`bash -c "bash -c ..."`) end here rather than recursing for ever.
_MAX_WRAPPER_DEPTH: Final[int] = 4
_DIRECTORY_CHANGERS: Final[frozenset[str]] = frozenset({"cd", "pushd"})


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
    for segment, piped_in in command_segments(command):
        words = _command_words(segment)
        fed_by = feeder if piped_in else None
        feeder = None
        if not words:
            continue
        head = posixpath.basename(words[0])
        if head in _DIRECTORY_CHANGERS:
            current = _after_directory_change(words, current)
        elif head in _SHELLS and _SHELL_COMMAND_FLAG in words[1:-1]:
            inner = words[words.index(_SHELL_COMMAND_FLAG, 1) + 1]
            yield from _reads(inner, current, depth + 1)
        elif head == _EVAL:
            yield from _reads(" ".join(words[1:]), current, depth + 1)
        elif head == _FIND:
            feeder = _find_roots(words)
            if _find_execs_a_search(words):
                yield from _reads_of_roots(feeder, current)
        elif head == _XARGS:
            inner_words = _xargs_command(words)
            if inner_words and _is_search(inner_words):
                yield from _search_reads(inner_words, current, piped_in=True)
                yield from _reads_of_roots(fed_by or (), current)
        elif _is_search(words):
            yield from _search_reads(words, current, piped_in=piped_in)


def _command_words(segment: str) -> list[str]:
    """The words of the command a segment runs, past assignments and wrappers.

    An unparseable segment yields nothing: the text scan already denies an
    unclosed quote, and nothing here can place its roots.
    """
    try:
        words = linear_shlex.split(segment)
    except ValueError:
        return []
    while words and _ASSIGNMENT.match(words[0]):
        words = words[1:]
    _names, start = peel_command_wrappers(words)
    return words[start:]


def _is_search(words: list[str]) -> bool:
    """Is the command's own head a grep-family tool (not a word that merely follows)?"""
    head = posixpath.basename(words[0])
    return head in _GREP_COMMANDS or head in _RG_COMMANDS or head == TOOL_GIT


def _search_reads(words: list[str], cwd: str | None, *, piped_in: bool) -> Iterator[Read]:
    """The trees one grep-family command reads, if it recurses."""
    found = search_command(words)
    if found is None:
        return
    tool, start, relocated = found
    if relocated:
        return
    scan = scan_options(words[start:], tool=tool)
    if not scan.recursive:
        return
    if tool == TOOL_GIT:
        yield from _git_grep_reads(words[start:], scan, cwd)
        return
    roots = tuple(scan.operands)
    if not roots:
        if tool == TOOL_RG and piped_in:
            return
        roots = (".",)
    rules = _tool_rules(posixpath.basename(words[0]), words[start:], scan)
    yield from _reads_of_roots(roots, cwd, rules)


def _git_grep_reads(arguments: list[str], scan: SearchArguments, cwd: str | None) -> Iterator[Read]:
    """The trees ``git grep`` reads: tracked files, or the working tree with ``--no-index``.

    Operands before a ``--`` are revisions and pathspecs are the words after it;
    with no ``--`` an operand is a path only if it exists. A pathspec carrying
    magic (``:(exclude)``) cannot be placed and is left out, so the search is
    judged over the rest.
    """
    # `--untracked` is really tracked plus non-ignored untracked files; ALL is the safe superset.
    view = (
        TreeView.ALL
        if any(word in _GIT_GREP_WORKING_TREE_FLAGS for word in arguments)
        else TreeView.TRACKED
    )
    if _END_OF_OPTIONS in arguments:
        candidates = arguments[arguments.index(_END_OF_OPTIONS) + 1 :]
    else:
        candidates = [operand for operand in scan.operands if _exists(operand, cwd)]
    roots = tuple(c for c in candidates if not c.startswith(_PATHSPEC_MAGIC_PREFIX)) or (".",)
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


def _find_execs_a_search(words: list[str]) -> bool:
    """Does a ``find`` command run a grep-family tool on what it finds?"""
    for index, word in enumerate(words):
        if word not in _FIND_EXEC_FLAGS:
            continue
        inner: list[str] = []
        for following in words[index + 1 :]:
            if following in _FIND_EXEC_TERMINATORS:
                break
            inner.append(following)
        if inner and _is_search(inner):
            return True
    return False


def _xargs_command(words: list[str]) -> list[str]:
    """The command ``xargs`` runs: the words after its own options."""
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in _XARGS_VALUE_FLAGS else 1
    return words[index:]


def _place(root: str, cwd: str | None) -> str | None:
    """The absolute, normalised form of ``root``, or None when it cannot be placed."""
    if _UNPLACEABLE_ROOT.search(root):
        return None
    expanded = str(Path(root).expanduser())
    if not posixpath.isabs(expanded):
        if cwd is None or not posixpath.isabs(cwd):
            return None
        expanded = posixpath.join(cwd, expanded)
    return posixpath.normpath(expanded)


def _placed(roots: tuple[str, ...], cwd: str | None) -> list[str]:
    """The distinct placeable roots, in order."""
    placed: list[str] = []
    for root in roots:
        absolute = _place(root, cwd)
        if absolute is not None and absolute not in placed:
            placed.append(absolute)
    return placed


def _reads_of_roots(
    roots: tuple[str, ...], cwd: str | None, rules: _Rules = _NO_RULES
) -> Iterator[Read]:
    for root in _placed(roots, cwd):
        view = TreeView.UNIGNORED if rules.honour_ignore else TreeView.ALL
        yield Read(root, view=view, skip=rules.predicate(root))
