"""Which directories a Bash command creates (Plan 00627 DESIGN.md section 8).

Shared by the PostToolUse inventory refresh (Task 5.1) and the PreToolUse
``R-SCRATCH-CAP`` rule (Task 5.4). Recognised: ``mkdir``, ``install -d``/``-D``,
``git clone``, ``git init``, ``git worktree add``, a recursive ``cp`` or
``rsync``, ``tar`` extraction, ``unzip``, ``mktemp -d``, and ``mv``/``ln -s``
of an existing directory. The shared wrapper table is peeled (``timeout``,
``sudo``, ``env``, ``command`` ...) and a ``bash -c`` body is scanned as a
command of its own.

``cd``/``pushd`` move the working directory for the statements after them,
and a ``( ... )`` subshell restores it. A path the scan cannot place (``$VAR``,
a backtick, ``cd -``) is UNRESOLVED: :func:`creates_directory_under` counts it
as under every root, because the cap guard fails toward detecting. A redirect
into a file, a heredoc body and a plain file copy are never a creation.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Final, TextIO, cast

from claude_code_hooks_daemon.utils.linear_shlex import LinearShlex
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    peel_command_wrappers,
)
from claude_code_hooks_daemon.utils.simple_commands import (
    SimpleCommand,
    nested_command_strings,
)

#: A creation target; ``None`` is one the scan cannot place.
Target = Path | None
Resolver = Callable[[str], Target]

_PUNCTUATION: Final[str] = ";&|()\n"
_MAX_NESTING: Final[int] = 3
_EXEC_PREFIXES: Final[frozenset[str]] = frozenset({"exec", "time", "builtin"})
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_REDIRECT_ALONE: Final[re.Pattern[str]] = re.compile(r"\d*(?:[<>]{1,2}|&>>?|>&|<&|>\|)")
_REDIRECT_GLUED: Final[re.Pattern[str]] = re.compile(r"\d*(?:[<>]{1,2}|&>>?|>&|<&)\S")
_HEREDOC: Final[re.Pattern[str]] = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_CLONE_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "-b",
        "--branch",
        "--depth",
        "-o",
        "--origin",
        "-c",
        "--config",
        "--reference",
        "--template",
        "-j",
        "--jobs",
        "--filter",
        "--separate-git-dir",
        "-u",
        "--upload-pack",
    }
)
_INIT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-b", "--initial-branch", "--template", "--separate-git-dir", "--object-format"}
)
_WORKTREE_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-b", "-B", "--reason"})
_GIT_GLOBAL_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-c", "--git-dir", "--work-tree"})
_TARGET_DIRECTORY: Final[frozenset[str]] = frozenset({"-t", "--target-directory"})
_COPY_VALUE_OPTIONS: Final[frozenset[str]] = _TARGET_DIRECTORY | {"-S", "--suffix"}
_INSTALL_VALUE_OPTIONS: Final[frozenset[str]] = _COPY_VALUE_OPTIONS | {
    "-m",
    "--mode",
    "-o",
    "--owner",
    "-g",
    "--group",
}
_RSYNC_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-e", "--rsh", "-f", "--filter", "--exclude", "--include", "--files-from", "-T"}
)


class UnparseableCommand(ValueError):
    """The statement scan reached text it cannot lex; what follows is unknown."""


class _KeepNewlineAfterComment:
    """shlex consumes a comment with ``readline``; leave its newline in the
    stream so the statement after the comment is not glued onto the one before.

    shlex reads its stream only through ``read(1)`` and ``readline()``.
    """

    def __init__(self, text: str) -> None:
        self._stream = io.StringIO(text)

    def read(self, size: int = -1) -> str:
        return self._stream.read(size)

    def readline(self) -> str:
        line = self._stream.readline()
        if line.endswith("\n"):
            self._stream.seek(self._stream.tell() - 1)
            return line[:-1]
        return line


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: their text is data, never a command."""
    kept: list[str] = []
    delimiter: str | None = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = _HEREDOC.search(line)
        if match:
            delimiter = match.group(1)
    return "\n".join(kept)


def _statements(command: str) -> Iterator[tuple[list[str], str]]:
    """Yield each simple statement's words with the separator that ends it.

    Raises :class:`UnparseableCommand` at the first text the lexer cannot read
    (an unbalanced quote, or valid bash such as ``$'it\\'s'`` that shlex
    mis-quotes); the statements already yielded stand. An unquoted newline separates statements exactly as ``;`` does, so it is a
    punctuation character to the lexer; a newline inside quotes stays in its
    word, a backslash-newline continuation is joined first, and a comment ends
    at its newline. The separator is ``""`` at the end of the command, and a
    statement may be empty when two separators meet (``(`` then ``cd``).
    """
    text = _strip_heredocs(command).replace("\\\n", " ")
    stream = cast("TextIO", _KeepNewlineAfterComment(text))
    lexer = LinearShlex(stream, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    current: list[str] = []
    try:
        for token in lexer:
            if set(token) <= set(_PUNCTUATION):
                yield current, token
                current = []
            else:
                current.append(token)
    except ValueError as exc:
        raise UnparseableCommand(f"the rest of the command could not be lexed: {exc}") from exc
    if current:
        yield current, ""


def _without_redirects(words: list[str]) -> list[str]:
    kept: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif _REDIRECT_ALONE.fullmatch(word):
            skip = True
        elif not _REDIRECT_GLUED.match(word):
            kept.append(word)
    return kept


def _command_words(words: list[str]) -> list[str]:
    """Strip assignments, redirects and wrappers to reach the command that runs."""
    words = _without_redirects(words)
    while True:
        while words and _ASSIGNMENT.fullmatch(words[0]):
            words = words[1:]
        if words and command_word(words[0]) in _EXEC_PREFIXES:
            words = words[1:]
            continue
        names, start = peel_command_wrappers(words)
        if not names:
            return words
        words = words[start:]


def peeled_statements(command: str) -> Iterator[list[str]]:
    """Each statement's words from the command that runs: assignments,
    redirects and wrappers stripped, the first word reduced to its name.

    Raises :class:`UnparseableCommand` where the text cannot be lexed."""
    for raw, _separator in _statements(command):
        words = _command_words(raw)
        if words:
            yield [command_word(words[0]), *words[1:]]


def copy_operands(args: list[str]) -> tuple[list[str], str | None, bool]:
    """``(sources, destination, into_directory)`` for ``cp``/``mv``/``install``/``ln``.

    ``into_directory`` is true when the destination is certainly a directory
    by its spelling: ``-t DIR``, a trailing ``/``, or more than one source.
    """
    target_dir = _option_value(args, _TARGET_DIRECTORY)
    found = _positionals(args, _INSTALL_VALUE_OPTIONS)
    if target_dir is not None:
        return found, target_dir, True
    if len(found) < 2:
        return found, None, False
    return found[:-1], found[-1], found[-1].endswith("/") or len(found) > 2


def _positionals(args: list[str], value_options: frozenset[str]) -> list[str]:
    out: list[str] = []
    skip = False
    options_ended = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "--" and not options_ended:
            options_ended = True
        elif not options_ended and arg.startswith("-") and arg != "-":
            skip = arg in value_options
        else:
            out.append(arg)
    return out


def _option_value(args: list[str], names: frozenset[str]) -> str | None:
    """The value of the first of ``names`` (``-t DIR``, ``--x=DIR``), if present."""
    for index, arg in enumerate(args):
        if arg in names and index + 1 < len(args):
            return args[index + 1]
        for name in names:
            if name.startswith("--") and arg.startswith(name + "="):
                return arg.split("=", 1)[1]
    return None


def _has_flag(args: list[str], long_names: Iterable[str], letters: str) -> bool:
    longs = set(long_names)
    return any(
        a in longs
        or (a.startswith("-") and not a.startswith("--") and bool(set(a[1:]) & set(letters)))
        for a in args
    )


def _git(args: list[str], resolve: Resolver) -> list[Target]:
    base = resolve(".")
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] == "-C" and index + 1 < len(args):
            base = resolve(args[index + 1])
            index += 2
        else:
            index += 2 if args[index] in _GIT_GLOBAL_VALUE_OPTIONS else 1
    if index >= len(args):
        return []
    sub, rest = args[index], args[index + 1 :]

    def under_base(word: str) -> Target:
        if Path(word).is_absolute() or "$" in word or "`" in word:
            return resolve(word)
        return None if base is None else base / word

    if sub == "clone":
        found = _positionals(rest, _CLONE_VALUE_OPTIONS)
        if len(found) >= 2:
            return [under_base(found[1])]
        if found:
            name = found[0].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            return [under_base(name.removesuffix(".git"))]
        return []
    if sub == "init":
        found = _positionals(rest, _INIT_VALUE_OPTIONS)
        return [under_base(found[0])] if found else [base]
    if sub == "worktree" and rest[:1] == ["add"]:
        found = _positionals(rest[1:], _WORKTREE_VALUE_OPTIONS)
        return [under_base(found[0])] if found else []
    return []


def _copy_destination(
    args: list[str], value_options: frozenset[str], resolve: Resolver
) -> Target | None:
    """``-t DIR`` or the last operand; ``None`` when there is no destination."""
    target_dir = _option_value(args, _TARGET_DIRECTORY)
    if target_dir is not None:
        return resolve(target_dir)
    found = _positionals(args, value_options)
    return resolve(found[-1]) if len(found) >= 2 else None


def _cp(args: list[str], resolve: Resolver) -> list[Target]:
    if not _has_flag(args, ("--recursive", "--archive"), "rRa"):
        return []
    if (
        _option_value(args, _TARGET_DIRECTORY) is None
        and len(_positionals(args, _COPY_VALUE_OPTIONS)) < 2
    ):
        return []
    return [_copy_destination(args, _COPY_VALUE_OPTIONS, resolve)]


def _rsync(args: list[str], resolve: Resolver) -> list[Target]:
    if not _has_flag(args, ("--recursive", "--archive"), "ra"):
        return []
    found = _positionals(args, _RSYNC_VALUE_OPTIONS)
    if len(found) < 2 or re.match(r"[^/]*:", found[-1]):
        return []
    return [resolve(found[-1].rstrip("/") or "/")]


def _sources_are_directories(sources: list[str], resolve: Resolver) -> bool:
    """Whether any source is an existing directory or cannot be placed."""
    for source in sources:
        path = resolve(source)
        if path is None or path.is_dir():
            return True
    return False


def _mv(args: list[str], resolve: Resolver) -> list[Target]:
    found = _positionals(args, _COPY_VALUE_OPTIONS)
    has_target_dir = _option_value(args, _TARGET_DIRECTORY) is not None
    sources = found if has_target_dir else found[:-1]
    if not sources or not _sources_are_directories(sources, resolve):
        return []
    return [_copy_destination(args, _COPY_VALUE_OPTIONS, resolve)]


def _ln(args: list[str], resolve: Resolver) -> list[Target]:
    if not _has_flag(args, ("--symbolic",), "s"):
        return []
    return _mv(args, resolve)


def _install(args: list[str], resolve: Resolver) -> list[Target]:
    found = _positionals(args, _INSTALL_VALUE_OPTIONS)
    if _has_flag(args, ("--directory",), "d"):
        return [resolve(p) for p in found]
    if "-D" in args and len(found) >= 2:
        dest = resolve(found[-1])
        return [None if dest is None else dest.parent]
    return []


def _unzip(args: list[str], resolve: Resolver) -> list[Target]:
    exdir = _option_value(args, frozenset({"-d"}))
    return [resolve(exdir if exdir is not None else ".")]


def _tar(args: list[str], resolve: Resolver) -> list[Target]:
    first = args[0] if args else ""
    extracting = (
        any(a in ("-x", "--extract", "--get") for a in args)
        or any(a.startswith("-") and not a.startswith("--") and "x" in a for a in args)
        or (bool(first) and not first.startswith("-") and "x" in first)
    )
    if not extracting:
        return []
    directory = _option_value(args, frozenset({"-C", "--directory"}))
    return [resolve(directory if directory is not None else ".")]


def _mktemp(args: list[str], resolve: Resolver) -> list[Target]:
    if not any(a in ("-d", "--directory") or re.fullmatch(r"-[a-z]*d[a-z]*", a) for a in args):
        return []
    tmpdir = _option_value(args, frozenset({"-p", "--tmpdir"}))
    if tmpdir is not None:
        return [resolve(tmpdir)]
    found = _positionals(args, frozenset({"-p", "--suffix"}))
    if found and "/" in found[0]:
        path = resolve(found[0])
        return [None if path is None else path.parent]
    return []


_MAKERS: Final[dict[str, Callable[[list[str], Resolver], list[Target]]]] = {
    "mkdir": lambda args, resolve: [
        resolve(p) for p in _positionals(args, frozenset({"-m", "--mode", "-Z"}))
    ],
    "git": _git,
    "cp": _cp,
    "rsync": _rsync,
    "mv": _mv,
    "ln": _ln,
    "install": _install,
    "unzip": _unzip,
    "tar": _tar,
    "mktemp": _mktemp,
}


def _resolver(cwd: Target) -> Resolver:
    def resolve(word: str) -> Target:
        if "$" in word or "`" in word:
            return None
        path = Path(word).expanduser()
        if path.is_absolute():
            return path
        return None if cwd is None else cwd / path

    return resolve


def _scan(command: str, cwd: Target, depth: int) -> Iterator[Target]:
    """Every creation target in ``command``, following ``cd`` and subshells.

    Text the lexer cannot read yields one UNRESOLVED target: it may create a
    directory anywhere, and the cap guard fails toward detecting.
    """
    current = cwd
    saved: list[Target] = []
    try:
        for raw, separator in _statements(command):
            words = _command_words(raw)
            if words:
                name, args = command_word(words[0]), words[1:]
                if name in ("cd", "pushd"):
                    operands = _positionals(args, frozenset())
                    if not operands:
                        current = Path.home()
                    elif operands[0] == "-":
                        current = None
                    else:
                        current = _resolver(current)(operands[0])
                else:
                    yield from _targets(name, words, current, depth)
            for char in separator:
                if char == "(":
                    saved.append(current)
                elif char == ")" and saved:
                    current = saved.pop()
    except UnparseableCommand:
        yield None


def _targets(name: str, words: list[str], cwd: Target, depth: int) -> list[Target]:
    maker = _MAKERS.get(name)
    if maker is not None:
        return maker(words[1:], _resolver(cwd))
    nested = nested_command_strings(
        SimpleCommand(verb=name, words=tuple(words), operands=tuple(words[1:]), reread=False)
    )
    if not nested:
        return []
    if depth >= _MAX_NESTING:
        return [None]
    return [target for body in nested for target in _scan(body, cwd, depth + 1)]


def _all_targets(command: str, cwd: Path) -> list[Target]:
    return [
        None if target is None else Path(os.path.normpath(target))
        for target in _scan(command, cwd, 0)
    ]


def directory_creating_targets(command: str, cwd: Path) -> tuple[Path, ...]:
    """Every directory ``command`` would create (or create inside) that the scan
    can place, normalised, in order."""
    return tuple(target for target in _all_targets(command, cwd) if target is not None)


def creates_directory_under(command: str, cwd: Path, roots: Iterable[Path]) -> bool:
    """True when any directory ``command`` creates is at or under one of ``roots``,
    or is a creation the scan cannot place."""
    normalised = [Path(os.path.normpath(root)) for root in roots]
    return any(
        target is None or target == root or path_is_relative_to(target, root)
        for target in _all_targets(command, cwd)
        for root in normalised
    )


def scratch_roots(project_root: Path) -> tuple[Path, ...]:
    """The default scratch root and the configured sweep root, deduplicated.

    The sweep root is resolved exactly as ``start_scratch_inventory_refresh``
    resolves it; an unreadable config leaves the default root only.
    """
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.core.untracked_roots import resolve_sweep_root

    default = project_root / "untracked" / "scratch"
    try:
        config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    except (OSError, ValueError):
        return (default,)
    resolved = resolve_sweep_root(
        default,
        project_root=project_root,
        config=config.scratch,
        reference_roots=tuple(config.reference_repos.roots),
    ).path
    return (default,) if resolved == default else (default, resolved)
