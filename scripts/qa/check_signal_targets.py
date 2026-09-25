#!/usr/bin/env python3
"""Fail when a nonzero signal goes to a pid nobody proved is the intended process.

Plan 00466 N59. A unit test's ``MagicMock`` Popen had a pid that coerces to 1,
and ``os.killpg(os.getpgid(process.pid), SIGKILL)`` killed ``tini``, the
container's init, taking every agent and session with it. Twice. A PID file is
no better a proof than a mock: it survives a container restart, and a restarted
container reuses small pids, so a stale file can name Claude Code itself.

In Python a pid counts as PROVEN only when the signal is sent by
``claude_code_hooks_daemon.utils.safe_signal``, the one module that verifies a
target before signalling it, or through a handle that module returned
(``verified_daemon_process``). ``read_pid_file(..., verify_daemon=True)`` is
NOT proof: it shows the pid is *a* daemon, not this project's.

Signal 0 is the existence probe, delivers nothing, and is exempt. A signal
given as anything but the literal ``0`` is treated as nonzero.

Python rules:

* ``raw-signal`` -- ``os.kill``, ``os.killpg`` or ``signal.pthread_kill``,
  however imported, with an unproven target.
* ``unproven-process-handle`` -- ``.terminate()``, ``.kill()`` or
  ``.send_signal()`` on a ``psutil.Process`` built from a raw pid or taken from
  ``psutil.process_iter()``; and ``.send_signal()`` on any receiver not proven
  to be a ``subprocess.Popen`` this scope spawned (a Popen signals only its own
  unreaped child, so its methods are safe by construction).
* ``kill-command`` -- a ``kill``, ``pkill`` or ``killall`` argv run through
  ``subprocess``, other than ``kill -0``.

Shell rule, over every tracked ``*.sh``/``*.bash`` file and shell-shebang
script outside ``tests/``:

* ``shell-unproven-kill`` -- ``kill``, ``pkill`` or ``killall`` in command
  position (including inside ``$( )``, backticks, a ``trap`` action and a
  ``sh -c`` string) with a nonzero signal. ``pkill`` and ``killall`` pick
  their targets by pattern and are always reported. A ``kill`` target is
  proven only when it is ``$$``, ``$!``, a ``%job``, a variable every
  non-empty binding of which in the file is ``$!``, or a variable an identity
  check (:data:`SHELL_VERIFIERS`) was run on earlier in the same function. A
  group target (``-PGID``) is proven only by an identity check, never by
  ``$!`` or ``$$``. A pid read from a file, a command substitution, ``pgrep``,
  a literal or a positional parameter is unproven.

Usage:
    python scripts/qa/check_signal_targets.py [--json]

Exit codes:
    0 -- no violations
    1 -- at least one violation
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "signal_targets.json"

#: The one module allowed to send a raw signal, because it is the verifier.
_HELPER: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "utils" / "safe_signal.py"

#: Python trees scanned recursively.
_SCAN_TREES: Final[tuple[Path, ...]] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon",
    _REPO_ROOT / "scripts",
)
#: Directories scanned one level deep: the ccy supervisor and the CLI entry points.
_SCAN_FLAT_DIRS: Final[tuple[Path, ...]] = (
    _REPO_ROOT / ".claude" / "ccy",
    _REPO_ROOT / "bin",
)

RAW_SIGNAL: Final[str] = "raw-signal"
UNPROVEN_HANDLE: Final[str] = "unproven-process-handle"
KILL_COMMAND: Final[str] = "kill-command"

_RAW_SIGNAL_CALLS: Final[frozenset[str]] = frozenset(
    {"os.kill", "os.killpg", "signal.pthread_kill"}
)
_POPEN_FACTORIES: Final[frozenset[str]] = frozenset(
    {
        "subprocess.Popen",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
    }
)
_PSUTIL_PROCESS: Final[str] = "psutil.Process"
_PSUTIL_PROCESS_ITER: Final[str] = "psutil.process_iter"
_SUBPROCESS_RUNNERS: Final[frozenset[str]] = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
    }
)
_KILL_COMMANDS: Final[frozenset[str]] = frozenset({"kill", "pkill", "killall"})
_PROBE_FLAG: Final[str] = "-0"
_HANDLE_SIGNAL_METHODS: Final[frozenset[str]] = frozenset({"terminate", "kill", "send_signal"})

#: A binding that proves a process handle.
_VERIFIED_HANDLE_SOURCE: Final[str] = "verified_daemon_process"

_REMEDIATION: Final[str] = (
    "Each site above sends a signal to a pid nothing proved is the intended\n"
    "process. A MagicMock pid coerces to 1, init's pid; a PID file survives a\n"
    "container restart and can name whatever reused that pid.\n"
    "\n"
    "Fix: route the signal through claude_code_hooks_daemon.utils.safe_signal:\n"
    "\n"
    "    signal_verified_daemon(pid, sig, project_root=root)   # a daemon pid\n"
    "    stop_verified_daemon(pid, project_root=root, grace_seconds=...)\n"
    "    signal_own_session_child(popen, sig)                  # a group kill\n"
    "\n"
    "or signal the Popen object itself (proc.terminate()), which only ever\n"
    "reaches its own unreaped child. Signal 0, the existence probe, is exempt.\n"
    "There is no exemption marker: fix the site, or fix this Detector."
)


@dataclass(frozen=True)
class Violation:
    """One signal whose target is not proven."""

    file: str
    line: int
    rule: str
    call: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": (
                f"`{self.call}` sends a nonzero signal to a target nothing proved is "
                "the intended process; use claude_code_hooks_daemon.utils.safe_signal"
            ),
        }


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> the dotted name it stands for, from every import in the module."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """``os.kill`` for ``os.kill``/``o.kill``/``kill``, resolved through imports."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value, aliases)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _called(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """The dotted name of the function ``node`` calls (through an ``await``), if any."""
    if isinstance(node, ast.Await):
        node = node.value
    if isinstance(node, ast.Call):
        return _dotted(node.func, aliases)
    return None


def _is_literal_zero(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value == 0


def _walk_scope(scope: ast.AST) -> Iterator[ast.AST]:
    """Every node in ``scope``, not descending into a nested function or class."""
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


#: A binding whose value is unknown (a parameter, a loop target over anything
#: but process_iter, an augmented assignment, ...).
_UNKNOWN: Final[str] = "<unknown>"


def _bindings(scope: ast.AST, aliases: dict[str, str]) -> dict[str, list[str]]:
    """Name -> the provenance of EVERY binding of it in ``scope``.

    A provenance is the dotted name of the function whose result was bound, or
    :data:`_UNKNOWN`.
    A name is proven only when every one of its bindings is, so a single
    rebinding to anything else makes it unproven.
    """
    found: dict[str, list[str]] = {}

    def bind(target: ast.expr, provenance: str) -> None:
        if isinstance(target, ast.Name):
            found.setdefault(target.id, []).append(provenance)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                bind(element, _UNKNOWN)
        elif isinstance(target, ast.Starred):
            bind(target.value, _UNKNOWN)

    def provenance_of(value: ast.expr) -> str:
        called = _called(value, aliases)
        return _UNKNOWN if called is None else called

    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        arguments = scope.args
        for arg in [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg else []),
            *([arguments.kwarg] if arguments.kwarg else []),
        ]:
            found.setdefault(arg.arg, []).append(_UNKNOWN)

    for node in _walk_scope(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, provenance_of(node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind(node.target, provenance_of(node.value))
        elif isinstance(node, ast.AugAssign):
            bind(node.target, _UNKNOWN)
        elif isinstance(node, ast.NamedExpr):
            bind(node.target, provenance_of(node.value))
        elif isinstance(node, ast.For | ast.AsyncFor):
            iterated = _called(node.iter, aliases)
            bind(node.target, iterated if iterated == _PSUTIL_PROCESS_ITER else _UNKNOWN)
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, provenance_of(item.context_expr))
    return found


def _all(bindings: dict[str, list[str]], node: ast.expr, accepted: frozenset[str]) -> bool:
    """Whether ``node`` is a name every binding of which has an accepted provenance."""
    if not isinstance(node, ast.Name):
        return False
    provenances = bindings.get(node.id, [])
    return bool(provenances) and all(p in accepted for p in provenances)


def _any(bindings: dict[str, list[str]], node: ast.expr, flagged: frozenset[str]) -> bool:
    """Whether ``node`` is a name any binding of which has a flagged provenance."""
    if not isinstance(node, ast.Name):
        return False
    return any(p in flagged for p in bindings.get(node.id, []))


_PSUTIL_SOURCES: Final = frozenset({_PSUTIL_PROCESS, _PSUTIL_PROCESS_ITER})


def _is_verified_handle_source(provenance: str) -> bool:
    return provenance.split(".")[-1] == _VERIFIED_HANDLE_SOURCE


def _check_raw_signal(call: ast.Call, name: str) -> str | None:
    if name not in _RAW_SIGNAL_CALLS:
        return None
    # `os.kill(*target)` hides both the pid and the signal: unknown, so reported.
    if len(call.args) < 2 or any(isinstance(arg, ast.Starred) for arg in call.args[:2]):
        return RAW_SIGNAL
    if _is_literal_zero(call.args[1]):
        return None
    return RAW_SIGNAL


def _check_handle_method(
    call: ast.Call, aliases: dict[str, str], bindings: dict[str, list[str]]
) -> str | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in _HANDLE_SIGNAL_METHODS:
        return None
    method = call.func.attr
    if method == "send_signal" and call.args and _is_literal_zero(call.args[0]):
        return None
    receiver = call.func.value
    if isinstance(receiver, ast.Name):
        provenances = bindings.get(receiver.id, [])
        if provenances and all(_is_verified_handle_source(p) for p in provenances):
            return None
    if _called(receiver, aliases) == _PSUTIL_PROCESS or _any(bindings, receiver, _PSUTIL_SOURCES):
        return UNPROVEN_HANDLE
    if method != "send_signal":
        return None
    if _all(bindings, receiver, _POPEN_FACTORIES):
        return None
    return UNPROVEN_HANDLE


def _check_kill_command(call: ast.Call, name: str) -> str | None:
    if name not in _SUBPROCESS_RUNNERS or not call.args:
        return None
    argv = call.args[0]
    if not isinstance(argv, ast.List | ast.Tuple) or not argv.elts:
        return None
    head = argv.elts[0]
    if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
        return None
    if Path(head.value).name not in _KILL_COMMANDS:
        return None
    probe = any(
        isinstance(element, ast.Constant) and element.value == _PROBE_FLAG
        for element in argv.elts[1:]
    )
    return None if probe else KILL_COMMAND


def scan_source(source: str, reported: str) -> list[Violation]:
    """Every unproven signal in one module's source."""
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    scopes: list[ast.AST] = [tree]
    scopes += [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]

    violations: list[Violation] = []
    for scope in scopes:
        bindings = _bindings(scope, aliases)
        for node in _walk_scope(scope):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func, aliases) or ""
            rule = (
                _check_raw_signal(node, name)
                or _check_handle_method(node, aliases, bindings)
                or _check_kill_command(node, name)
            )
            if rule is not None:
                violations.append(
                    Violation(file=reported, line=node.lineno, rule=rule, call=ast.unparse(node))
                )
    return sorted(violations, key=lambda v: (v.file, v.line))


def scan_file(path: Path) -> list[Violation]:
    """Every unproven signal in one file; none in the verifying helper itself."""
    if path.resolve() == _HELPER.resolve():
        return []
    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    return scan_source(path.read_text(encoding="utf-8"), reported)


def _is_python(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    with path.open("rb") as handle:
        first_line = handle.readline()
    return first_line.startswith(b"#!") and b"python" in first_line


def scanned_files() -> list[Path]:
    """Every Python file the Detector judges."""
    files: set[Path] = set()
    for tree in _SCAN_TREES:
        files.update(path for path in tree.rglob("*.py") if "__pycache__" not in path.parts)
    for directory in _SCAN_FLAT_DIRS:
        files.update(path for path in directory.iterdir() if path.is_file() and _is_python(path))
    return sorted(files)


# --- Shell -----------------------------------------------------------------

SHELL_UNPROVEN_KILL: Final[str] = "shell-unproven-kill"

#: Shell functions that establish a pid is still the process the caller means:
#: a command line and project root, a start time, a parent, or a job-table row.
SHELL_VERIFIERS: Final[frozenset[str]] = frozenset(
    {
        "_is_project_daemon_pid",
        "_is_dummy_daemon_pid",
        "_vb_process_identity",
        "_vb_job_running",
        "_venv_parent_of",
        "_rv_parent_of",
    }
)
_SHELL_KILLERS: Final[frozenset[str]] = frozenset({"kill", "pkill", "killall"})
#: Words that may precede the command itself and are not it.
_SHELL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"if", "then", "do", "else", "elif", "while", "until", "!", "{", "time"}
)
#: Commands that run the next word as the command, after their own options.
_SHELL_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"command", "builtin", "exec", "nohup", "sudo", "env", "xargs"}
)
#: Commands whose string argument is itself shell code.
_SHELL_CODE_ARGS: Final[frozenset[str]] = frozenset({"trap", "eval"})
_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"sh", "bash", "dash", "zsh"})
_SHELL_SUFFIXES: Final[frozenset[str]] = frozenset({".sh", ".bash"})
_SHELL_SHEBANG: Final = re.compile(rb"^#!.*\b(?:ba|da|z|k)?sh\b")
_SHELL_OPERATORS: Final[str] = ";&|<>()\n"
_ASSIGNMENT: Final = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.DOTALL)
_SIMPLE_TARGET: Final = re.compile(r"^(-?)\$(?:\{([A-Za-z_]\w*|[$!])\}|([A-Za-z_]\w*|[$!]))$")
_FUNCTION_START: Final = re.compile(r"^(\s*)(?:function\s+)?[\w:.-]+\s*\(\)\s*\{?\s*$")
_BACKGROUND_PID: Final[str] = "$!"
_OWN_PID: Final[str] = "$$"
_ZERO_SIGNALS: Final[frozenset[str]] = frozenset({"0", "SIG0"})
#: ``read``/``printf`` options whose next word is a value, not a variable name.
_READ_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-p", "-d", "-n", "-N", "-t", "-u", "-i"})


@dataclass(frozen=True)
class _Word:
    raw: str
    line: int


@dataclass(frozen=True)
class _Command:
    words: tuple[_Word, ...]
    seq: int


def _unquote(raw: str) -> str:
    """A word with its quote characters removed: enough to compare a literal."""
    return raw.replace('"', "").replace("'", "")


class _ShellLexer:
    """Split shell source into simple commands, including every nested one.

    Not a shell parser: it knows quoting, ``$( )``, backticks, ``${ }``,
    ``$(( ))``, redirections, heredocs and comments -- enough to tell a
    ``kill`` the shell runs from the word ``kill`` in a string, comment or
    heredoc body. An unquoted heredoc's body is scanned for substitutions,
    which the shell does run.
    """

    def __init__(self, text: str, first_line: int, commands: list[_Command]) -> None:
        self._text = text
        self._first_line = first_line
        self._commands = commands
        self._heredocs: list[tuple[str, bool, bool]] = []

    def _line(self, offset: int) -> int:
        return self._first_line + self._text.count("\n", 0, offset)

    def run(self) -> None:
        self._code(0, None)

    def _emit(self, words: list[_Word]) -> None:
        if words:
            self._commands.append(_Command(tuple(words), len(self._commands)))

    def _code(self, i: int, closer: str | None) -> int:
        """Lex commands from ``i`` to ``closer`` (or the end); return the index after it."""
        text = self._text
        words: list[_Word] = []
        depth = 0
        while i < len(text):
            char = text[i]
            if closer == "`" and char == "`":
                self._emit(words)
                return i + 1
            if char == ")" and depth == 0 and closer == ")":
                self._emit(words)
                return i + 1
            if char in " \t":
                i += 1
            elif char == "\\" and text.startswith("\\\n", i):
                i += 2
            elif char == "\n":
                self._emit(words)
                words = []
                i = self._heredoc_bodies(i + 1)
            elif char == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
                end = text.find("\n", i)
                i = len(text) if end < 0 else end
            elif char in "<>" and text.startswith("(", i + 1):
                i = self._code(i + 2, ")")
            elif char in "<>" or (char == "&" and text.startswith(">", i + 1)):
                i = self._redirection(i)
            elif char == "(":
                self._emit(words)
                words = []
                depth += 1
                i += 1
            elif char == ")":
                # A `)` closing nothing ends a case pattern, which is not a command.
                if depth > 0:
                    self._emit(words)
                    depth -= 1
                words = []
                i += 1
            elif char in ";&|":
                self._emit(words)
                words = []
                i += 1
            else:
                start = i
                i = self._word(i)
                raw = text[start:i]
                if raw.isdigit() and i < len(text) and text[i] in "<>":
                    continue  # a file descriptor number, part of the redirection
                words.append(_Word(raw, self._line(start)))
        self._emit(words)
        return i

    def _word(self, i: int) -> int:
        """Return the index after the word starting at ``i``, lexing any substitution in it."""
        text = self._text
        while i < len(text) and text[i] not in " \t" and text[i] not in _SHELL_OPERATORS:
            char = text[i]
            if char == "\\":
                i += 2
            elif char == "'":
                end = text.find("'", i + 1)
                i = len(text) if end < 0 else end + 1
            elif text.startswith("$'", i):
                i = self._ansi_c(i + 2)
            elif char == '"':
                i = self._expansions(i + 1, stop_at_quote=True, end=len(text))
            else:
                i = self._expansion(i)
        return i

    def _ansi_c(self, i: int) -> int:
        text = self._text
        while i < len(text) and text[i] != "'":
            i += 2 if text[i] == "\\" else 1
        return i + 1

    def _expansion(self, i: int) -> int:
        """Consume one character, or one whole ``$( )``/backtick/``${ }``/``$(( ))`` at ``i``."""
        text = self._text
        if text.startswith("$((", i):
            return self._balanced(i + 3, 2)
        if text.startswith("$(", i):
            return self._code(i + 2, ")")
        if text.startswith("${", i):
            return self._balanced_brace(i + 2)
        if text[i] == "`":
            return self._code(i + 1, "`")
        return i + 1

    def _expansions(self, i: int, *, stop_at_quote: bool, end: int) -> int:
        """Scan double-quoted text (or a heredoc body) for substitutions."""
        text = self._text
        while i < end:
            char = text[i]
            if char == "\\":
                i += 2
            elif stop_at_quote and char == '"':
                return i + 1
            else:
                i = self._expansion(i)
        return i

    def _balanced(self, i: int, depth: int) -> int:
        text = self._text
        while i < len(text) and depth > 0:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        return i

    def _balanced_brace(self, i: int) -> int:
        text = self._text
        depth = 1
        while i < len(text) and depth > 0:
            if text[i] == "\\":
                i += 2
                continue
            if text.startswith("$(", i) or text[i] == "`":
                i = self._expansion(i)
                continue
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        return i

    def _redirection(self, i: int) -> int:
        """Consume a redirection operator and its target word; queue a heredoc."""
        text = self._text
        if text.startswith("<<<", i):
            i += 3
        elif text.startswith("<<", i):
            strip_tabs = text.startswith("<<-", i)
            i += 3 if strip_tabs else 2
            while i < len(text) and text[i] in " \t":
                i += 1
            start = i
            i = self._word(i)
            delimiter = text[start:i]
            quoted = any(mark in delimiter for mark in "'\"\\")
            self._heredocs.append((_unquote(delimiter).replace("\\", ""), quoted, strip_tabs))
            return i
        else:
            i += 1
            while i < len(text) and text[i] in "<>&|-":
                i += 1
        while i < len(text) and text[i] in " \t":
            i += 1
        return self._word(i)

    def _heredoc_bodies(self, i: int) -> int:
        """Skip the bodies of the heredocs opened on the line just ended."""
        text = self._text
        pending, self._heredocs = self._heredocs, []
        for delimiter, quoted, strip_tabs in pending:
            body_start = i
            while i < len(text):
                end = text.find("\n", i)
                end = len(text) if end < 0 else end
                line = text[i:end]
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    if not quoted:
                        self._expansions(body_start, stop_at_quote=False, end=i)
                    i = end + 1
                    break
                i = end + 1
        return i


def _shell_commands(text: str) -> list[_Command]:
    """Every simple command in ``text``, with the code inside a trap/eval/``-c`` string."""
    commands: list[_Command] = []
    _ShellLexer(text, 1, commands).run()
    scanned = 0
    while scanned < len(commands):
        command = commands[scanned]
        scanned += 1
        code = _code_argument(command)
        if code is not None and len(code.raw) >= 2 and code.raw[0] in "'\"":
            _ShellLexer(code.raw[1:-1], code.line, commands).run()
    return commands


def _stripped(words: tuple[_Word, ...]) -> tuple[tuple[_Word, ...], bool]:
    """The command without leading keywords, assignments and wrappers.

    The flag says the command's arguments arrive on stdin (``xargs``), so they
    are whatever the previous pipeline stage printed.
    """
    piped = False
    index = 0
    while index < len(words):
        word = _unquote(words[index].raw)
        if word in _SHELL_KEYWORDS or _ASSIGNMENT.match(words[index].raw):
            index += 1
        elif word in _SHELL_WRAPPERS or word == "timeout":
            piped = piped or word == "xargs"
            index += 1
            while index < len(words) and (
                words[index].raw.startswith("-") or _ASSIGNMENT.match(words[index].raw)
            ):
                index += 1
            if word == "timeout" and index < len(words):
                index += 1  # the duration
        else:
            break
    return words[index:], piped


def _code_argument(command: _Command) -> _Word | None:
    words, _ = _stripped(command.words)
    if not words:
        return None
    head = Path(_unquote(words[0].raw)).name
    if head in _SHELL_CODE_ARGS and len(words) > 1:
        return words[1]
    if head in _SHELL_INTERPRETERS:
        for index, word in enumerate(words[:-1]):
            if word.raw == "-c":
                return words[index + 1]
    return None


def _kill_signal_and_targets(args: tuple[_Word, ...]) -> tuple[str | None, list[_Word], bool]:
    """``kill``'s signal (None when none is given), its targets, and whether it only lists."""
    signal_name: str | None = None
    targets: list[_Word] = []
    listing = False
    options_done = False
    index = 0
    while index < len(args):
        word = _unquote(args[index].raw)
        if not options_done and not targets:
            if word == "--":
                options_done = True
                index += 1
                continue
            if word in {"-l", "-L"} or word.startswith("--list"):
                listing = True
                index += 1
                continue
            if word in {"-s", "-n", "--signal"}:
                following = args[index + 1].raw if index + 1 < len(args) else ""
                signal_name = _unquote(following)
                index += 2
                continue
            if word.startswith("-") and signal_name is None:
                signal_name = word[1:]
                index += 1
                continue
        targets.append(args[index])
        index += 1
    return signal_name, targets, listing


def _pattern_kill_is_probe(args: tuple[_Word, ...]) -> bool:
    words = [_unquote(word.raw) for word in args]
    for index, word in enumerate(words):
        if word == "-0" or word == "--signal=0":
            return True
        if word in {"-s", "--signal"} and index + 1 < len(words) and words[index + 1] == "0":
            return True
    return False


def _bindings_of(commands: list[_Command]) -> dict[str, list[str]]:
    """Variable name -> the unquoted value of every binding of it in the file.

    ``read``, ``for``, ``printf -v`` and ``mapfile`` bind a value nobody can
    see, recorded as the empty-but-not-blank marker ``?``.
    """
    found: dict[str, list[str]] = {}
    for command in commands:
        for word in command.words:
            match = _ASSIGNMENT.match(word.raw)
            if match:
                found.setdefault(match.group(1), []).append(_unquote(match.group(2)))
        words, _ = _stripped(command.words)
        if not words:
            continue
        head = _unquote(words[0].raw)
        rest = [_unquote(argument.raw) for argument in words[1:]]
        if head == "for" and rest:
            found.setdefault(rest[0], []).append("?")
        elif head in {"read", "mapfile", "readarray", "printf"}:
            skip_next = False
            for index, text in enumerate(rest):
                if skip_next:
                    skip_next = False
                elif text in _READ_VALUE_OPTIONS:
                    skip_next = True
                elif re.fullmatch(r"[A-Za-z_]\w*", text) and (
                    head != "printf" or (index > 0 and rest[index - 1] == "-v")
                ):
                    found.setdefault(text, []).append("?")
    return found


def _function_spans(lines: list[str]) -> list[tuple[int, int]]:
    """``(first, last)`` 1-based line spans of each function, closed by a brace at its indent."""
    spans: list[tuple[int, int]] = []
    for number, line in enumerate(lines, start=1):
        match = _FUNCTION_START.match(line)
        if not match:
            continue
        closing = f"{match.group(1)}}}"
        last = number
        for later, candidate in enumerate(lines[number:], start=number + 1):
            if candidate.rstrip() == closing:
                last = later
                break
        spans.append((number, last))
    return spans


def _scope_of(line: int, spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    """The innermost function span holding ``line``; None at the top level."""
    holding = [span for span in spans if span[0] <= line <= span[1]]
    return max(holding, key=lambda span: span[0]) if holding else None


def _references(words: tuple[_Word, ...], name: str) -> bool:
    pattern = re.compile(rf"\$(?:\{{{name}\}}|{name}(?!\w))")
    return any(pattern.search(word.raw) for word in words)


def _verified_earlier(
    name: str, kill: _Command, commands: list[_Command], spans: list[tuple[int, int]]
) -> bool:
    """Whether an identity check on ``$name`` ran earlier in the kill's own function."""
    scope = _scope_of(kill.words[0].line, spans)
    for command in commands:
        if command.seq >= kill.seq:
            continue
        words, _ = _stripped(command.words)
        if not words or _unquote(words[0].raw) not in SHELL_VERIFIERS:
            continue
        if _scope_of(words[0].line, spans) != scope:
            continue
        if _references(words[1:], name):
            return True
    return False


def _kill_target_is_proven(
    target: _Word,
    kill: _Command,
    commands: list[_Command],
    bindings: dict[str, list[str]],
    spans: list[tuple[int, int]],
) -> bool:
    raw = _unquote(target.raw)
    if raw.startswith("%"):
        return True
    match = _SIMPLE_TARGET.match(raw)
    if not match:
        return False
    group = match.group(1) == "-"
    name = match.group(2) or match.group(3)
    if name in {_OWN_PID[1], _BACKGROUND_PID[1]}:
        return not group
    if _verified_earlier(name, kill, commands, spans):
        return True
    if group:
        return False
    values = [value for value in bindings.get(name, []) if value]
    return bool(values) and all(value in {_BACKGROUND_PID, "${!}"} for value in values)


def scan_shell_source(text: str, reported: str) -> list[Violation]:
    """Every shell ``kill``/``pkill``/``killall`` with a nonzero signal and an unproven target."""
    commands = _shell_commands(text)
    bindings = _bindings_of(commands)
    spans = _function_spans(text.splitlines())
    violations: list[Violation] = []
    for command in commands:
        words, piped = _stripped(command.words)
        if not words:
            continue
        head = Path(_unquote(words[0].raw)).name
        if head not in _SHELL_KILLERS:
            continue
        args = words[1:]
        call = " ".join(word.raw for word in words)
        if head != "kill" or piped:
            unproven = not _pattern_kill_is_probe(args)
        else:
            signal_name, targets, listing = _kill_signal_and_targets(args)
            unproven = (
                not listing
                and signal_name not in _ZERO_SIGNALS
                and any(
                    not _kill_target_is_proven(target, command, commands, bindings, spans)
                    for target in targets
                )
            )
        if unproven:
            violations.append(
                Violation(file=reported, line=words[0].line, rule=SHELL_UNPROVEN_KILL, call=call)
            )
    return sorted(violations, key=lambda v: (v.file, v.line))


def scan_shell_file(path: Path) -> list[Violation]:
    """Every unproven shell signal in one file."""
    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    return scan_shell_source(path.read_text(encoding="utf-8"), reported)


def _is_shell(path: Path) -> bool:
    if path.suffix in _SHELL_SUFFIXES:
        return True
    if path.suffix:
        return False
    with path.open("rb") as handle:
        first_line = handle.readline()
    return bool(_SHELL_SHEBANG.match(first_line))


def scanned_shell_files() -> list[Path]:
    """Every tracked shell script the Detector judges; the test suite's own are not first-party code."""
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [_REPO_ROOT / name for name in result.stdout.split("\0") if name]
    return sorted(
        path
        for path in paths
        if path.relative_to(_REPO_ROOT).parts[0] != "tests"
        and path.is_file()
        and not path.is_symlink()
        and _is_shell(path)
    )


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    python_files = scanned_files()
    shell_files = scanned_shell_files()
    files = python_files + shell_files
    violations = [violation for path in python_files for violation in scan_file(path)]
    violations += [violation for path in shell_files for violation in scan_shell_file(path)]
    output = {
        "tool": "signal_targets",
        "summary": {
            "passed": not violations,
            "total_violations": len(violations),
            "files_scanned": len(files),
        },
        "violations": [violation.to_dict() for violation in violations],
    }

    if "--json" in args:
        _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} signal(s) sent to an unproven target:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  [{violation.rule}]  {violation.call}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No signal sent to an unproven target ({len(files)} files scanned)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
