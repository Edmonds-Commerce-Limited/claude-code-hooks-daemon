#!/usr/bin/env python3
"""Fail when a nonzero signal goes to a pid nobody proved is the intended process.

Plan 00466 N59. A unit test's ``MagicMock`` Popen had a pid that coerces to 1,
and ``os.killpg(os.getpgid(process.pid), SIGKILL)`` killed ``tini``, the
container's init, taking every agent and session with it. Twice. A PID file is
no better a proof than a mock: it survives a container restart, and a restarted
container reuses small pids, so a stale file can name Claude Code itself.

A pid counts as PROVEN in exactly two ways:

* it was bound from ``read_pid_file(..., verify_daemon=True)`` in the same
  scope, and never rebound to anything else; or
* the signal is sent by ``claude_code_hooks_daemon.utils.safe_signal``, the one
  module that verifies a target before signalling it, or through a handle that
  module returned (``verified_daemon_process``).

Signal 0 is the existence probe, delivers nothing, and is exempt. A signal
given as anything but the literal ``0`` is treated as nonzero.

Rules:

* ``raw-signal`` -- ``os.kill``, ``os.killpg`` or ``signal.pthread_kill``,
  however imported, with an unproven target.
* ``unproven-process-handle`` -- ``.terminate()``, ``.kill()`` or
  ``.send_signal()`` on a ``psutil.Process`` built from a raw pid or taken from
  ``psutil.process_iter()``; and ``.send_signal()`` on any receiver not proven
  to be a ``subprocess.Popen`` this scope spawned (a Popen signals only its own
  unreaped child, so its methods are safe by construction).
* ``kill-command`` -- a ``kill``, ``pkill`` or ``killall`` argv run through
  ``subprocess``, other than ``kill -0``.

Usage:
    python scripts/qa/check_signal_targets.py [--json]

Exit codes:
    0 -- no violations
    1 -- at least one violation
"""

from __future__ import annotations

import ast
import json
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

#: A binding that proves a pid: the function's name, and the keyword it needs.
_VERIFIED_PID_SOURCE: Final[str] = "read_pid_file"
_VERIFIED_PID_KEYWORD: Final[str] = "verify_daemon"
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

    A provenance is the dotted name of the function whose result was bound, a
    ``read_pid_file`` call tagged by whether it verified, or :data:`_UNKNOWN`.
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
        if called is None:
            return _UNKNOWN
        if called.split(".")[-1] == _VERIFIED_PID_SOURCE:
            call = value.value if isinstance(value, ast.Await) else value
            assert isinstance(call, ast.Call)
            verified = any(
                keyword.arg == _VERIFIED_PID_KEYWORD
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            )
            return f"{_VERIFIED_PID_SOURCE}:{'verified' if verified else 'unverified'}"
        return called

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


_VERIFIED_PID: Final = frozenset({f"{_VERIFIED_PID_SOURCE}:verified"})
_PSUTIL_SOURCES: Final = frozenset({_PSUTIL_PROCESS, _PSUTIL_PROCESS_ITER})


def _is_verified_handle_source(provenance: str) -> bool:
    return provenance.split(".")[-1] == _VERIFIED_HANDLE_SOURCE


def _check_raw_signal(call: ast.Call, name: str, bindings: dict[str, list[str]]) -> str | None:
    if name not in _RAW_SIGNAL_CALLS:
        return None
    # `os.kill(*target)` hides both the pid and the signal: unknown, so reported.
    if len(call.args) < 2 or any(isinstance(arg, ast.Starred) for arg in call.args[:2]):
        return RAW_SIGNAL
    if _is_literal_zero(call.args[1]):
        return None
    if name == "os.kill" and _all(bindings, call.args[0], _VERIFIED_PID):
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
                _check_raw_signal(node, name, bindings)
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


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    files = scanned_files()
    violations = [violation for path in files for violation in scan_file(path)]
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
