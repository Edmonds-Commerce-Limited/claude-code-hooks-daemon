"""Which directories a Bash command creates (Plan 00627 DESIGN.md section 8).

Shared by the PostToolUse inventory refresh (Task 5.1) and the PreToolUse
``R-SCRATCH-CAP`` rule (Task 5.4). Recognised: ``mkdir``, ``git clone``,
``git init``, ``git worktree add``, a recursive ``cp``, ``tar`` extraction and
``mktemp -d``. A redirect into a file, a heredoc body and a plain file copy are
never a directory creation. ``cd`` is not followed: every relative path is
resolved against the hook's ``cwd``.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&&", "||", "|", "&", "(", ")", "\n"})
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


def _statements(command: str) -> Iterator[list[str]]:
    lexer = shlex.shlex(_strip_heredocs(command), posix=True, punctuation_chars=";&|()")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    current: list[str] = []
    try:
        for token in lexer:
            if token in _SEPARATORS or set(token) <= set(";&|()"):
                if current:
                    yield current
                current = []
            else:
                current.append(token)
    except ValueError:
        return
    if current:
        yield current


def _positionals(args: list[str], value_options: frozenset[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg.startswith("-") and arg != "-":
            skip = arg in value_options
        else:
            out.append(arg)
    return out


def _git(args: list[str], cwd: Path) -> list[Path]:
    base = cwd
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] == "-C" and index + 1 < len(args):
            base = cwd / args[index + 1]
            index += 2
        else:
            index += 2 if args[index] in _GIT_GLOBAL_VALUE_OPTIONS else 1
    if index >= len(args):
        return []
    sub, rest = args[index], args[index + 1 :]
    if sub == "clone":
        found = _positionals(rest, _CLONE_VALUE_OPTIONS)
        if len(found) >= 2:
            return [base / found[1]]
        if found:
            name = found[0].rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            return [base / name.removesuffix(".git")]
        return []
    if sub == "init":
        found = _positionals(rest, _INIT_VALUE_OPTIONS)
        return [base / found[0]] if found else [base]
    if sub == "worktree" and rest[:1] == ["add"]:
        found = _positionals(rest[1:], _WORKTREE_VALUE_OPTIONS)
        return [base / found[0]] if found else []
    return []


def _cp(args: list[str], cwd: Path) -> list[Path]:
    flags = [a for a in args if a.startswith("-")]
    recursive = any(
        f in ("--recursive", "--archive") or (not f.startswith("--") and set(f[1:]) & set("rRa"))
        for f in flags
    )
    found = _positionals(args, frozenset({"-t", "--target-directory", "-S", "--suffix"}))
    return [cwd / found[-1]] if recursive and len(found) >= 2 else []


def _tar(args: list[str], cwd: Path) -> list[Path]:
    first = args[0] if args else ""
    extracting = (
        any(a in ("-x", "--extract", "--get") for a in args)
        or any(a.startswith("-") and not a.startswith("--") and "x" in a for a in args)
        or (bool(first) and not first.startswith("-") and "x" in first)
    )
    if not extracting:
        return []
    for index, arg in enumerate(args):
        if arg in ("-C", "--directory") and index + 1 < len(args):
            return [cwd / args[index + 1]]
        if arg.startswith("--directory="):
            return [cwd / arg.split("=", 1)[1]]
    return [cwd]


def _mktemp(args: list[str], cwd: Path) -> list[Path]:
    if not any(a in ("-d", "--directory") or re.fullmatch(r"-[a-z]*d[a-z]*", a) for a in args):
        return []
    for index, arg in enumerate(args):
        if arg in ("-p", "--tmpdir") and index + 1 < len(args):
            return [cwd / args[index + 1]]
        if arg.startswith("--tmpdir="):
            return [cwd / arg.split("=", 1)[1]]
    found = _positionals(args, frozenset({"-p", "--suffix"}))
    if found and "/" in found[0]:
        return [(cwd / found[0]).parent]
    return []


def _targets(words: list[str], cwd: Path) -> list[Path]:
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if not words:
        return []
    name, args = Path(words[0]).name, words[1:]
    if name == "mkdir":
        return [cwd / p for p in _positionals(args, frozenset({"-m", "--mode", "-Z"}))]
    if name == "git":
        return _git(args, cwd)
    if name == "cp":
        return _cp(args, cwd)
    if name == "tar":
        return _tar(args, cwd)
    if name == "mktemp":
        return _mktemp(args, cwd)
    return []


def directory_creating_targets(command: str, cwd: Path) -> tuple[Path, ...]:
    """Every directory ``command`` would create (or create inside), normalised, in order."""
    return tuple(
        Path(os.path.normpath(target))
        for words in _statements(command)
        for target in _targets(words, cwd)
    )


def creates_directory_under(command: str, cwd: Path, roots: Iterable[Path]) -> bool:
    """True when any directory ``command`` creates is at or under one of ``roots``."""
    normalised = [Path(os.path.normpath(root)) for root in roots]
    return any(
        target == root or target.is_relative_to(root)
        for target in directory_creating_targets(command, cwd)
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
