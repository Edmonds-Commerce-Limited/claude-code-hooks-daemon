#!/usr/bin/env python3
"""Fail when a first-party shell script runs ``python3`` / ``python`` by its bare name.

A bare ``python3`` in command position runs whatever ``PATH`` resolves first,
which may be older than the declared minimum (``requires-python``). The
scripts that install, upgrade and dispatch hooks have already resolved the
interpreter the daemon runs on (the venv's ``bin/python``, or
``HOOKS_DAEMON_PYTHON`` during an upgrade), and must run Python on that one.
The originating instance was ``eager_cleanup_stale_venvs`` in
``scripts/install/venv.sh``, which ran ``python3 "$paths_script" ...``.

**What is reported.** The word ``python`` or ``python3``, unquoted or quoted,
as the COMMAND of a simple command: at the start of a statement, after ``;``,
``&&``, ``||``, ``|``, ``&``, ``(``, ``{``, ``$(``, a backtick, ``then``,
``do``, ``else``, ``!`` and the like, and after the prefixes that hand the
command on (``VAR=x``, ``exec``, ``env``, ``sudo``, ``nohup``, ``timeout N``,
``xargs`` ...). Not reported: ``command -v python3``, ``which python3`` and
every other use as an ARGUMENT or in prose; a heredoc body (data); a comment;
a pinned ``python3.12``; a resolved path or ``"$interpreter"``.

**A bare name stored as a VALUE to be run later is the same hazard**, so it is
reported too: a default ``${VAR:-python3}`` / ``${VAR:=python3}`` / ``${1:-python3}``
(also nested), and an assignment ``VAR=python3`` / ``VAR="python3"`` (also after
``local`` / ``export`` / ``declare`` ...). A default that quietly picks the PATH
interpreter is a silent fallback. Not reported: the word in an ``echo`` / ``printf``
argument, ``${VAR:+python3}``, ``command -v python3``, a pinned or resolved value.

**Scope.** ``CLAUDE/Plan/`` is not scanned: plan prototypes and benchmarks are never
run on a client host nor by install, upgrade or dispatch, so they do not carry the
hazard. Fixture trees, gitignored state and other checkouts are skipped as well.

**Genuine bootstrap probes** (code whose job is to find or validate an
interpreter before a venv exists) are listed in ``bare-python-allowlist.json``,
one entry per probe with the REASON it carries no hazard. An entry that
matches nothing is itself a failure, so the list cannot rot.

There is no inline exemption marker.

Usage:
    python scripts/qa/check_bare_python_invocation.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation, or no file was examined
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import git_visible_paths
from claude_code_hooks_daemon.utils.path_containment import path_relative_to
from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "bare_python_invocation.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME
_ALLOWLIST_FILE: Final[Path] = Path(__file__).resolve().parent / "bare-python-allowlist.json"

_RULE: Final[str] = "bare-python-invocation"
_STALE_RULE: Final[str] = "bare-python-allowlist-stale"
_UNREADABLE_RULE: Final[str] = "bare-python-unreadable"

_FIX: Final[str] = (
    'run the interpreter the caller resolved ("$interpreter", the venv bin/python, or '
    '"$HOOKS_DAEMON_PYTHON"), not a bare python3 from PATH'
)

_BARE_NAMES: Final[frozenset[str]] = frozenset({"python", "python3"})

#: Words after which the next word is still a command.
_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"if", "then", "elif", "else", "do", "while", "until", "!", "{", "time", "coproc"}
)
#: Commands that run their first non-option argument as a command.
_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        "exec",
        "env",
        "sudo",
        "nohup",
        "nice",
        "setsid",
        "stdbuf",
        "timeout",
        "xargs",
        "command",
        # Declaration builtins hand the next word on as an assignment (``local x=python3``).
        "local",
        "export",
        "declare",
        "readonly",
        "typeset",
    }
)
#: ``command -v python3`` asks where it is; it does not run it.
_LOOKUP_FLAGS: Final[frozenset[str]] = frozenset({"-v", "-V"})
_DURATION: Final[re.Pattern[str]] = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
#: ``VAR=python3`` / ``VAR="python3"``: a bare name stored to be run later.
_BARE_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\+?=(?:python3?)$"
)
#: The inside of ``${...}``: ``VAR:-python3`` / ``VAR:=python3`` / ``1:-python3``, possibly
#: nested in another default. ``:+`` is not a default, and ``python3.12`` is a pin.
_DEFAULT_BARE: Final[re.Pattern[str]] = re.compile(
    r"""(?:^|\{)(?:[A-Za-z_]\w*|\d+):?[-=]\s*["']?python3?["']?(?:\}|$)"""
)
#: Commands whose arguments are text shown to a person, never a value that is run.
_DISPLAY_COMMANDS: Final[frozenset[str]] = frozenset({"echo", "printf"})
_HEREDOC_DELIMITER: Final[re.Pattern[str]] = re.compile(r"""^(-?)\s*(?:'([^']*)'|"([^"]*)"|\\?(\w+))""")

_SHELL_SUFFIXES: Final[frozenset[str]] = frozenset({".sh", ".bash"})
_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"sh", "bash", "dash", "zsh"})
_SHEBANG: Final[str] = "#!"
_MAX_BYTES: Final[int] = 2_000_000

#: Gitignored runtime state and other checkouts, never project source. Matched
#: on the path BELOW the scan root, never on the absolute path.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "untracked",
        "venv",
        ".venv",
        "worktrees",
    }
)
#: Fixture trees hold deliberately-defective sample files, never run.
_FIXTURE_PARTS: Final[tuple[str, ...]] = ("tests", "fixtures")
#: Plan prototypes and benchmarks are never run on client hosts, by install, upgrade or dispatch.
_PLAN_PARTS: Final[tuple[str, ...]] = ("CLAUDE", "Plan")

_REMEDIATION: Final[str] = (
    "Each site above runs a bare python3/python, so it runs whatever PATH resolves,\n"
    "which may be older than requires-python. Run the interpreter the caller already\n"
    'resolved instead ("$interpreter", the venv bin/python, "$HOOKS_DAEMON_PYTHON").\n'
    "Code whose whole job is to FIND or VALIDATE an interpreter before a venv exists\n"
    "is listed with its reason in scripts/qa/bare-python-allowlist.json; anything\n"
    "else is a defect to fix, not an entry to add. There is no inline exemption marker."
)


@dataclass(frozen=True)
class Violation:
    """One bare interpreter invocation, or one allowlist entry that matches nothing."""

    file: str
    line: int
    rule: str = _RULE
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "rule": self.rule, "message": self.message}


@dataclass(frozen=True)
class AllowEntry:
    """A genuine bootstrap probe: ``match`` is a substring of the invoking line."""

    file: str
    match: str
    reason: str


def load_allowlist_entries(raw: list[dict[str, str]]) -> list[AllowEntry]:
    """Validate the allowlist: every entry names a file, a match and a REASON."""
    entries: list[AllowEntry] = []
    for item in raw:
        entry = AllowEntry(
            file=item.get("file", "").strip(),
            match=item.get("match", ""),
            reason=item.get("reason", "").strip(),
        )
        if not entry.file or not entry.match.strip():
            raise ValueError(f"allowlist entry needs a file and a match: {item!r}")
        if not entry.reason:
            raise ValueError(f"allowlist entry for {entry.file} has no reason: {item!r}")
        entries.append(entry)
    return entries


def _load_allowlist(path: Path) -> list[AllowEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return load_allowlist_entries(data["entries"])


# -- Shell scanner --------------------------------------------------------------------------


class _Scanner:
    """A small shell tokenizer that knows quotes, heredocs and command position."""

    def __init__(self, source: str) -> None:
        self._s = source
        self._i = 0
        self._line = 1
        self.found: list[int] = []
        self._pending_heredocs: list[tuple[str, bool]] = []
        # Stack of the contexts a ``$(`` / backtick opened; the top decides what ``)`` means.
        self._cmd = True
        self._word = ""
        self._word_quoted = False
        self._word_literal = True
        self._word_line = 1
        self._prefix: str | None = None
        self._cmd_name = ""
        self._redirect_target = False
        self._depth = 0

    # -- word handling

    def _end_word(self, followed_by_close_paren: bool = False) -> None:
        if not self._word and not self._word_quoted:
            return
        word, literal = self._word, self._word_literal
        self._word, self._word_quoted, self._word_literal = "", False, True
        if self._redirect_target:
            self._redirect_target = False
            return
        if not self._cmd:
            return
        if self._prefix is not None:
            if self._prefix == "command" and word in _LOOKUP_FLAGS:
                self._cmd, self._prefix = False, None
                return
            if word.startswith("-") or (self._prefix == "timeout" and _DURATION.match(word)):
                return
        if _ASSIGNMENT.match(word) and not word.startswith("="):
            if _BARE_ASSIGNMENT.match(word):
                self.found.append(self._word_line)
            return
        if literal and word in _KEYWORDS:
            return
        if literal and word in _PREFIXES:
            self._prefix = word
            return
        self._prefix = None
        self._cmd_name = word if literal else ""
        if literal and word in _BARE_NAMES and not (followed_by_close_paren and self._depth == 0):
            self.found.append(self._word_line)
        self._cmd = False

    def _add(self, text: str, *, quoted: bool = False, literal: bool = True) -> None:
        if not self._word and not self._word_quoted:
            self._word_line = self._line
        self._word += text
        self._word_quoted = self._word_quoted or quoted
        self._word_literal = self._word_literal and literal

    def _newline(self) -> None:
        self._end_word()
        self._line += 1
        self._cmd, self._prefix, self._redirect_target = True, None, False
        if self._pending_heredocs:
            self._skip_heredoc_bodies()

    def _skip_heredoc_bodies(self) -> None:
        for delimiter, strip_tabs in self._pending_heredocs:
            while self._i < len(self._s):
                end = self._s.find("\n", self._i)
                end = len(self._s) if end == -1 else end
                text = self._s[self._i : end]
                self._i = min(end + 1, len(self._s))
                self._line += 1
                if (text.lstrip("\t") if strip_tabs else text) == delimiter:
                    break
        self._pending_heredocs = []

    # -- quoting

    def _single_quote(self) -> None:
        end = self._s.find("'", self._i)
        end = len(self._s) if end == -1 else end
        body = self._s[self._i : end]
        self._add(body, quoted=True, literal=False)
        self._line += body.count("\n")
        self._i = min(end + 1, len(self._s))

    def _double_quote(self) -> None:
        self._add("", quoted=True)
        s = self._s
        while self._i < len(s):
            ch = s[self._i]
            self._i += 1
            if ch == '"':
                return
            if ch == "\\" and self._i < len(s):
                self._add(s[self._i], literal=False)
                self._line += s[self._i] == "\n"
                self._i += 1
            elif ch == "$" and s.startswith("(", self._i):
                self._i += 1
                self._substitution(")")
            elif ch == "`":
                self._substitution("`")
            elif ch == "$" and s.startswith("{", self._i):
                self._i += 1
                self._braces()
            else:
                self._line += ch == "\n"
                self._add(ch, literal=ch != "$")

    def _braces(self) -> None:
        depth = 1
        start = self._i
        self._add("${", literal=False)
        while self._i < len(self._s) and depth:
            ch = self._s[self._i]
            self._i += 1
            depth += (ch == "{") - (ch == "}")
            self._line += ch == "\n"
        self._word_literal = False
        if _DEFAULT_BARE.search(self._s[start : self._i]) and not self._is_display_text():
            self.found.append(self._line)

    def _is_display_text(self) -> bool:
        """Whether the word being read is an argument of ``echo`` / ``printf``: text, not a value."""
        return not self._cmd and self._cmd_name in _DISPLAY_COMMANDS

    def _substitution(self, closer: str) -> None:
        """Scan a ``$( ... )`` or backtick body as its own command context."""
        saved = (self._word, self._word_quoted, self._word_literal, self._word_line)
        saved_state = (self._cmd, self._prefix, self._redirect_target, self._depth)
        saved_name = self._cmd_name
        self._word, self._word_quoted, self._word_literal = "", False, True
        self._cmd, self._prefix, self._redirect_target = True, None, False
        self._depth = 1 if closer == ")" else 0
        self._run(closer)
        self._end_word()
        self._word, self._word_quoted, self._word_literal, self._word_line = saved
        self._cmd, self._prefix, self._redirect_target, self._depth = saved_state
        self._cmd_name = saved_name
        self._word_literal = False

    # -- main loop

    def _comment(self) -> None:
        end = self._s.find("\n", self._i)
        self._i = len(self._s) if end == -1 else end

    def _heredoc(self) -> None:
        self._i += 2
        strip_tabs = self._s.startswith("-", self._i)
        match = _HEREDOC_DELIMITER.match(self._s[self._i :])
        if match is None:
            return
        self._i += match.end()
        strip_tabs = bool(match.group(1))
        delimiter = next(g for g in match.groups()[1:] if g is not None)
        self._pending_heredocs.append((delimiter, strip_tabs))
        self._redirect_target = False

    def _operator(self, ch: str) -> bool:
        """Handle a separator or redirection; True when ``ch`` was one."""
        s = self._s
        if ch in ";|&":
            self._end_word()
            if ch == "&" and s.startswith(">", self._i + 1):
                self._i += 2
                self._redirect_target = True
                return True
            run = 1
            while self._i + run < len(s) and s[self._i + run] in ";|&":
                run += 1
            self._i += run
            self._cmd, self._prefix, self._redirect_target = True, None, False
            return True
        if ch in "<>":
            digits = self._word.isdigit() and not self._word_quoted
            if not digits:
                self._end_word()
            self._word, self._word_quoted, self._word_literal = "", False, True
            if s.startswith("<<<", self._i):
                self._i += 3
                self._redirect_target = True
                return True
            if s.startswith("<<", self._i):
                self._heredoc()
                return True
            self._i += 1
            while self._i < len(s) and s[self._i] in "<>&|-":
                self._i += 1
            if s.startswith("(", self._i):
                self._i += 1
                self._substitution(")")
            else:
                self._redirect_target = True
            return True
        return False

    def _run(self, closer: str | None) -> None:
        s = self._s
        while self._i < len(s):
            ch = s[self._i]
            if closer == "`" and ch == "`":
                self._i += 1
                return
            if closer == ")" and ch == ")" and self._depth == 1:
                self._end_word(followed_by_close_paren=False)
                self._i += 1
                return
            if ch == "\n":
                self._i += 1
                self._newline()
            elif ch == "\\":
                self._backslash()
            elif ch in " \t":
                self._i += 1
                self._end_word(followed_by_close_paren=False)
            elif ch == "#" and not self._word and not self._word_quoted:
                self._comment()
            elif ch == "'":
                self._i += 1
                self._single_quote()
            elif ch == '"':
                self._i += 1
                self._double_quote()
            elif ch == "$" and s.startswith("'", self._i + 1):
                self._i += 2
                self._ansi_c_quote()
            elif ch == "$" and s.startswith("((", self._i + 1):
                self._i += 3
                self._arithmetic()
            elif ch == "$" and s.startswith("(", self._i + 1):
                self._i += 2
                self._substitution(")")
            elif ch == "$" and s.startswith("{", self._i + 1):
                self._i += 2
                self._braces()
            elif ch == "`":
                self._i += 1
                self._substitution("`")
            elif ch in "()":
                self._paren(ch)
            elif self._operator(ch):
                continue
            else:
                self._i += 1
                self._add(ch, literal=ch != "$")

    def _backslash(self) -> None:
        s = self._s
        if s.startswith("\n", self._i + 1):
            self._i += 2
            self._line += 1
            return
        self._add(s[self._i + 1 : self._i + 2], quoted=True, literal=False)
        self._i += 2

    def _ansi_c_quote(self) -> None:
        s = self._s
        self._add("", quoted=True, literal=False)
        while self._i < len(s):
            ch = s[self._i]
            self._i += 1
            if ch == "\\":
                self._i += 1
            elif ch == "'":
                return
            else:
                self._line += ch == "\n"

    def _arithmetic(self) -> None:
        depth = 2
        while self._i < len(self._s) and depth:
            ch = self._s[self._i]
            self._i += 1
            depth += (ch == "(") - (ch == ")")
            self._line += ch == "\n"
        self._add("0", literal=False)

    def _paren(self, ch: str) -> None:
        """A bare ``(`` starts a subshell; ``)`` ends a case pattern or a subshell."""
        if ch == "(":
            self._end_word()
            self._cmd, self._prefix = True, None
            self._depth += 1
        else:
            self._end_word(followed_by_close_paren=True)
            self._depth = max(self._depth - 1, 0)
            self._cmd, self._prefix = True, None
        self._i += 1

    def run(self) -> list[int]:
        self._run(None)
        self._end_word()
        return self.found


def bare_python_lines(source: str) -> Iterator[int]:
    """The 1-based line of every bare ``python`` / ``python3`` command in ``source``."""
    yield from sorted(set(_Scanner(source).run()))


# -- Walk -----------------------------------------------------------------------------------


def _is_shell(path: Path, head: str) -> bool:
    """Whether ``path`` is a shell script: by suffix, or an extensionless shebang."""
    if path.suffix in _SHELL_SUFFIXES:
        return True
    if path.suffix or not head.startswith(_SHEBANG):
        return False
    words = head[len(_SHEBANG) :].split()
    return any(Path(word).name in _SHELL_INTERPRETERS for word in words[:2])


def _is_unscanned(parts: tuple[str, ...]) -> bool:
    return (
        any(part in _SKIP_DIRS for part in parts)
        or parts[: len(_FIXTURE_PARTS)] == _FIXTURE_PARTS
        or parts[: len(_PLAN_PARTS)] == _PLAN_PARTS
    )


def _candidate_files(root: Path) -> list[Path]:
    visible = git_visible_paths(root)
    return [
        path
        for path in walk_files(root)
        if (visible is None or "/".join(relative_parts(path, root)) in visible)
        and not _is_unscanned(tuple(relative_parts(path, root)))
        and path.is_file()
        and not path.is_symlink()
        and (path.suffix in _SHELL_SUFFIXES or not path.suffix)
    ]


def _scan_file(path: Path, relative: str) -> tuple[bool, list[tuple[int, str]], list[Violation]]:
    """``(examined, (line, text) hits, unreadable violations)`` for one file."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            return False, [], []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (
            True,
            [],
            [
                Violation(
                    file=relative,
                    line=0,
                    rule=_UNREADABLE_RULE,
                    message=f"could not be read ({exc}), so it cannot be shown free of a bare python",
                )
            ],
        )
    if not _is_shell(path, text.split("\n", 1)[0]):
        return False, [], []
    lines = text.splitlines()
    return True, [(n, lines[n - 1]) for n in bare_python_lines(text)], []


def scan(root: Path, allowlist: list[AllowEntry]) -> tuple[list[Violation], int, int]:
    """``(violations, files examined, files seen)`` below ``root``."""
    seen = walk_files(root)
    violations: list[Violation] = []
    used: set[int] = set()
    examined = 0
    for path in _candidate_files(root):
        relative = path_relative_to(path, root).as_posix()
        was_examined, hits, unreadable = _scan_file(path, relative)
        examined += was_examined
        violations.extend(unreadable)
        for number, text in hits:
            allowed = [
                i
                for i, entry in enumerate(allowlist)
                if entry.file == relative and entry.match in text
            ]
            used.update(allowed)
            if not allowed:
                violations.append(
                    Violation(
                        file=relative,
                        line=number,
                        message=f"runs a bare python from PATH; {_FIX}",
                    )
                )
    violations.extend(
        Violation(
            file=entry.file,
            line=0,
            rule=_STALE_RULE,
            message=f"allowlist entry matches no bare python ({entry.match!r}); delete it",
        )
        for i, entry in enumerate(allowlist)
        if i not in used
    )
    return sorted(violations, key=lambda v: (v.file, v.line)), examined, len(seen)


def scan_tree(root: Path, allowlist: list[AllowEntry] | None = None) -> list[Violation]:
    """Every violation below ``root``; ``allowlist`` defaults to the repository's own."""
    entries = _load_allowlist(_ALLOWLIST_FILE) if allowlist is None else allowlist
    return scan(root, entries)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_REPO_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    # A --path scan has no allowlist of its own: the list names repository files.
    allowlist = _load_allowlist(_ALLOWLIST_FILE) if root == _REPO_ROOT else []
    violations, examined, seen = scan(root, allowlist)
    vacuous = vacuous_scan_failure(examined=examined, candidates=seen, noun="files", root=root)

    if args.json_output:
        output_file = root / _ARTEFACT_NAME if root != _REPO_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(
                {
                    "tool": "bare_python_invocation",
                    "summary": {
                        "passed": not violations and vacuous is None,
                        "vacuous_scan": vacuous,
                        "total_violations": len(violations),
                        "files_scanned": examined,
                    },
                    "violations": [v.to_dict() for v in violations],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if vacuous is not None:
        print(f"FAILED: {vacuous}")
    elif violations:
        print(f"Found {len(violations)} bare python invocation(s) [{_RULE}]:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  {violation.rule}: {violation.message}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No shell script runs a bare python ({examined} scanned)")
    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
