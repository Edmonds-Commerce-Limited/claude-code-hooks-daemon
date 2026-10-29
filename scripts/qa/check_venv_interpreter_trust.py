#!/usr/bin/env python3
"""Fail when a venv interpreter is trusted without a major.minor check.

Plan 00555. The system Python moved from 3.11 to 3.13; a venv built under 3.11
kept a ``bin/python`` symlink that now ran 3.13 and could not see
``lib/python3.11/site-packages``. The daemon could not import itself, and
because every check asked only "does it exist / is it executable / does
``import sys`` work", the venv still resolved and the self-heal never fired.

A venv interpreter counts as USABLE only when the interpreter that will run it
has the major.minor the venv was built for (``pyvenv.cfg`` ``version_info`` /
``version``). Two rules report code that judges one usable without that:

* ``venv-exec-bit-trust`` -- an existence or executable test on a venv
  interpreter path (a path expression ending ``bin/python`` or ``bin/python3``,
  a variable bound from one, a ``for`` variable over such paths or over
  ``("python", "python3")``, or a variable bound from the venv resolver).
  Shell: ``[ -x|-f|-e ... ]``, ``[[ ... ]]``, ``test``. Python: ``.is_file()``,
  ``.exists()``, ``os.access`` and ``os.path.isfile``/``exists``.
* ``venv-weak-liveness-probe`` -- an interpreter run as ``-c "import sys"``,
  ``--version`` or ``-V`` and nothing else. It passes for a symlink to any
  Python at all.

PROOF exempts a finding: the SAME function (for shell top level, the same
top-level code) either reads ``pyvenv.cfg`` and compares a version (Python:
a string or name for ``pyvenv.cfg``, a ``version`` / ``version_info`` /
major-minor reference and a comparison, ignoring docstrings; shell: ``pyvenv.cfg``
and ``version`` outside comments), or calls a gate in :data:`GATES`. A gate is
proof only if its OWN body passes the same test, computed from the source by
:func:`proven_gates`; a gate that merely probes proves nothing, so the gates
are themselves findings until they compare the version.

There is no exemption marker: fix the site, or fix this Detector.

Scope: every tracked first-party ``*.py``, ``*.sh``, ``*.bash`` and
shell/python-shebang file, except ``tests/`` (test code builds and asserts on
fake venvs and selects no interpreter to run the product), any
``fixtures``/``assets`` directory, ``.claude/worktrees/``, ``untracked/`` and
vendored code. See :func:`in_scope`.

Usage:
    python scripts/qa/check_venv_interpreter_trust.py [--json]

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Final

try:
    import check_signal_targets as _sig
except ModuleNotFoundError:
    # Loaded by file path (e.g. importlib in tests): prime this script's own
    # directory so the sibling Detector, whose shell lexer this reuses, resolves.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_signal_targets as _sig

_REPO_ROOT: Final[Path] = _sig._REPO_ROOT
_OUTPUT_FILE: Final[Path] = _REPO_ROOT / "untracked" / "qa" / "venv_interpreter_trust.json"

_DOC: Final[str] = "CLAUDE/Security/UntrustedVenvInterpreter.md"

RULE_EXEC_BIT: Final[str] = "venv-exec-bit-trust"
RULE_WEAK_PROBE: Final[str] = "venv-weak-liveness-probe"

#: The gates that may prove a venv interpreter's version, and the file holding
#: each. A gate is proof only when its own body passes the version test; see
#: :func:`proven_gates`.
GATES: Final[Mapping[str, str]] = {
    "venv_interpreter_usable": "src/claude_code_hooks_daemon/daemon/paths.py",
    "venv_python_usable": "scripts/lib/resolve_venv.sh",
    "_rv_cached_venv_current": "scripts/lib/resolve_venv.sh",
}

#: Functions whose result is a venv interpreter path.
_RESOLVER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "resolve_venv_python",
        "resolve_existing_venv_python",
        "resolve_existing_venv_python_with_diagnostics",
    }
)
_RESOLVER_CALL: Final = re.compile(r"\b(?:" + "|".join(sorted(_RESOLVER_NAMES)) + r")\b")

_TOP_DIRS: Final[frozenset[str]] = frozenset({"tests", "untracked"})
_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    _sig._EXCLUDED_DIR_NAMES | {"vendor", "node_modules", ".venv", "site-packages"}
)
_WORKTREES_PREFIX: Final[str] = ".claude/worktrees/"

_INTERP_NAME: Final = re.compile(r"python(?:3(?:\.\d+)?)?")
_INTERP_TAIL: Final = re.compile(r"bin/(?:python(?:3(?:\.\d+)?)?|\{python[^}]*\})\*?$")
_VENV_BIN_VARIABLE: Final = re.compile(r"venv.*/bin/\$\{?\w+\}?$", re.IGNORECASE)
_METADATA_PYTHON_KEY: Final[str] = "python_path"
_PACKAGE: Final[str] = "claude_code_hooks_daemon"
_SYS_PATH_EDIT: Final[str] = "sys.path"
_SH_PACKAGE_IMPORT: Final = re.compile(
    r"-c\s+[\"']import " + _PACKAGE + r"\b(?![^\"']*" + re.escape(_SYS_PATH_EDIT) + ")"
)
_PROBE_HEAD_HINT: Final = re.compile(r"python|interp|candidate|venv", re.IGNORECASE)
_VERSION_FLAGS: Final[frozenset[str]] = frozenset({"--version", "-V"})
_IMPORT_SYS: Final[str] = "import sys"

_PY_CFG_NAME: Final = re.compile(r"pyvenv", re.IGNORECASE)
_PY_VERSION_STRING: Final = re.compile(r"version|major.?minor", re.IGNORECASE)
_PY_VERSION_NAME: Final = re.compile(r"version_info|major_?minor", re.IGNORECASE)
_SH_PYVENV_CFG: Final = re.compile(r"pyvenv\.cfg")
_SH_VERSION: Final = re.compile(r"version", re.IGNORECASE)

_EXISTENCE_METHODS: Final[frozenset[str]] = frozenset({"is_file", "exists"})
_EXISTENCE_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"os.access", "os.path.isfile", "os.path.exists"}
)
_SHELL_TEST_HEADS: Final[frozenset[str]] = frozenset({"[", "[[", "test"})
_SHELL_TEST_OPERATORS: Final[frozenset[str]] = frozenset({"-x", "-f", "-e"})
_PATH_WRAPPERS: Final[frozenset[str]] = frozenset({"Path", "PurePath", "str", "fspath"})
_PATH_PASSTHROUGH_METHODS: Final[frozenset[str]] = frozenset({"resolve", "absolute", "expanduser"})

_MESSAGES: Final[Mapping[str, str]] = {
    RULE_EXEC_BIT: (
        "`{call}` judges a venv interpreter usable by existence or exec bit; "
        "nothing compares its major.minor with pyvenv.cfg"
    ),
    RULE_WEAK_PROBE: (
        "`{call}` is a liveness probe any Python passes; "
        "nothing compares the venv's major.minor with pyvenv.cfg"
    ),
}


@dataclass(frozen=True)
class Violation:
    """One venv interpreter trusted without a major.minor check."""

    file: str
    line: int
    rule: str
    call: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": f"{_MESSAGES[self.rule].format(call=self.call)}; {_DOC}",
        }


_REMEDIATION: Final[str] = (
    "Each site above treats a venv interpreter as usable on evidence that holds\n"
    "when the interpreter behind bin/python has changed minor version.\n"
    "\n"
    "Fix: compare pyvenv.cfg's version (major.minor) with the interpreter that\n"
    "will run it in the same function, or call a gate that does\n"
    "(_venv_interpreter_runs, _rv_candidate_runs, _rv_cached_venv_current).\n"
    "There is no exemption marker: fix the site, or fix this Detector.\n"
    f"Rules and proofs: {_DOC}"
)


def _dedupe(violations: list[Violation]) -> list[Violation]:
    """One violation per (line, rule), sorted by position."""
    seen: set[tuple[int, str]] = set()
    unique: list[Violation] = []
    for violation in sorted(violations, key=lambda v: (v.file, v.line, v.rule)):
        key = (violation.line, violation.rule)
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return unique


# --- Python ----------------------------------------------------------------


@dataclass(frozen=True)
class _Var:
    """A name standing in a path expression."""

    name: str


_Part = str | _Var | None


def _split(text: str) -> list[_Part]:
    return [part for part in text.split("/") if part]


def _parts(node: ast.expr) -> list[_Part]:
    """The path components of ``node``: literals, variables and unknowns (None)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _split(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div | ast.Add):
        return [*_parts(node.left), *_parts(node.right)]
    if isinstance(node, ast.JoinedStr):
        pieces: list[_Part] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                pieces.extend(_split(str(value.value)))
            elif isinstance(value, ast.FormattedValue):
                inner = value.value
                pieces.append(_Var(ast.unparse(inner)) if isinstance(inner, ast.Name) else None)
        return pieces
    if isinstance(node, ast.Name | ast.Attribute):
        return [_Var(ast.unparse(node))]
    if isinstance(node, ast.Call):
        return _call_parts(node)
    return [None]


def _call_parts(call: ast.Call) -> list[_Part]:
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return [None]
    if name in _PATH_WRAPPERS:
        return [part for arg in call.args for part in _parts(arg)] or [None]
    if isinstance(func, ast.Attribute):
        if name == "joinpath":
            return [*_parts(func.value), *(part for arg in call.args for part in _parts(arg))]
        if name == "join":
            return [part for arg in call.args for part in _parts(arg)]
        if name in _PATH_PASSTHROUGH_METHODS and not call.args:
            return _parts(func.value)
    return [None]


def _python_names(scope: ast.AST) -> frozenset[str]:
    """Loop variables iterating over ``("python", "python3")``-style names."""
    names: set[str] = set()
    for node in _sig._walk_scope(scope):
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Tuple | ast.List)
            and any(
                isinstance(e, ast.Constant)
                and isinstance(e.value, str)
                and _INTERP_NAME.fullmatch(e.value)
                for e in node.iter.elts
            )
        ):
            names.add(node.target.id)
    return frozenset(names)


def _is_interpreter_path(parts: list[_Part], python_names: frozenset[str]) -> bool:
    if len(parts) < 2 or parts[-2] != "bin":
        return False
    last = parts[-1]
    if isinstance(last, str):
        return _INTERP_NAME.fullmatch(last) is not None
    return isinstance(last, _Var) and last.name in python_names


def _unwrap(node: ast.expr) -> ast.expr:
    """``x`` for ``str(x)``/``Path(x)``."""
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _PATH_WRAPPERS
        and len(node.args) == 1
    ):
        node = node.args[0]
    return node


def _reads_metadata_python_path(node: ast.expr) -> bool:
    """``meta["python_path"]`` or ``meta.get("python_path", ...)``."""
    if isinstance(node, ast.Subscript):
        key = node.slice
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        key = node.args[0]
    else:
        return False
    return isinstance(key, ast.Constant) and key.value == _METADATA_PYTHON_KEY


def _is_interpreter(node: ast.expr, interp_vars: set[str], python_names: frozenset[str]) -> bool:
    node = _unwrap(node)
    if _reads_metadata_python_path(node):
        return True
    if isinstance(node, ast.Name | ast.Attribute) and ast.unparse(node) in interp_vars:
        return True
    return _is_interpreter_path(_parts(node), python_names)


def _calls_resolver(node: ast.expr, aliases: dict[str, str]) -> bool:
    called = _sig._called(node, aliases)
    return called is not None and called.split(".")[-1] in _RESOLVER_NAMES


def _interpreter_variables(
    scope: ast.AST, aliases: dict[str, str], python_names: frozenset[str]
) -> set[str]:
    """Names (and attribute chains) bound from a venv interpreter path in ``scope``."""
    found: set[str] = set()
    binders = sorted(
        (
            node
            for node in _sig._walk_scope(scope)
            if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr | ast.For)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for _ in range(2):
        for node in binders:
            if isinstance(node, ast.For):
                if isinstance(node.iter, ast.Tuple | ast.List) and any(
                    _is_interpreter(e, found, python_names) for e in node.iter.elts
                ):
                    found.add(ast.unparse(node.target))
                continue
            value = node.value
            if value is None:
                continue
            if _is_interpreter(value, found, python_names) or _calls_resolver(value, aliases):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                found.update(
                    ast.unparse(target)
                    for target in targets
                    if isinstance(target, ast.Name | ast.Attribute)
                )
    return found


def _is_version_proof_scope(scope: ast.AST, aliases: dict[str, str], gates: frozenset[str]) -> bool:
    """Whether ``scope`` reads pyvenv.cfg and compares a version, or calls a proven gate."""
    nodes = list(_sig._walk_scope(scope))
    docstrings = {
        id(node.value)
        for node in nodes
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    has_cfg = has_version = has_compare = False
    for node in nodes:
        if isinstance(node, ast.Call):
            called = _sig._dotted(node.func, aliases)
            if called is not None and called.split(".")[-1] in gates:
                return True
        elif isinstance(node, ast.Compare):
            has_compare = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            has_cfg = has_cfg or "pyvenv.cfg" in node.value
            has_version = has_version or _PY_VERSION_STRING.search(node.value) is not None
        elif isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            has_cfg = has_cfg or _PY_CFG_NAME.search(name) is not None
            has_version = has_version or _PY_VERSION_NAME.search(name) is not None
    return has_cfg and has_version and has_compare


def _runs_package_import(scope: ast.AST, aliases: dict[str, str]) -> bool:
    """Whether ``scope`` runs ``[interp, "-c", "import <package>..."]`` without editing sys.path.

    A venv built for another minor cannot see its own site-packages, so
    importing the package under the interpreter fails on a mismatch.
    """
    for node in _sig._walk_scope(scope):
        if not (
            isinstance(node, ast.Call)
            and (_sig._dotted(node.func, aliases) or "") in _sig._SUBPROCESS_RUNNERS
            and node.args
            and isinstance(node.args[0], ast.List | ast.Tuple)
        ):
            continue
        for flag, code in pairwise(node.args[0].elts):
            if (
                isinstance(flag, ast.Constant)
                and flag.value == "-c"
                and isinstance(code, ast.Constant)
                and isinstance(code.value, str)
                and code.value.strip().startswith(f"import {_PACKAGE}")
                and _SYS_PATH_EDIT not in code.value
            ):
                return True
    return False


def _weak_probe_argv(argv: ast.expr) -> bool:
    """Whether ``argv`` is ``[interp, "-c", "import sys"]`` or ``[interp, "--version"|"-V"]``."""
    if not isinstance(argv, ast.List | ast.Tuple) or len(argv.elts) < 2:
        return False
    head, *rest = argv.elts
    values = [e.value if isinstance(e, ast.Constant) else None for e in rest]
    if isinstance(head, ast.Constant) and not (isinstance(head.value, str) and "/" in head.value):
        return False
    if ast.unparse(head) == "sys.executable":
        return False
    if len(values) == 2 and values[0] == "-c":
        return isinstance(values[1], str) and values[1].strip() == _IMPORT_SYS
    if len(values) == 1 and values[0] in _VERSION_FLAGS:
        return _PROBE_HEAD_HINT.search(ast.unparse(head)) is not None
    return False


def _python_rule(
    call: ast.Call, aliases: dict[str, str], interp_vars: set[str], python_names: frozenset[str]
) -> str | None:
    name = _sig._dotted(call.func, aliases) or ""
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in _EXISTENCE_METHODS
        and not call.args
        and _is_interpreter(call.func.value, interp_vars, python_names)
    ):
        return RULE_EXEC_BIT
    if (
        name in _EXISTENCE_FUNCTIONS
        and call.args
        and _is_interpreter(call.args[0], interp_vars, python_names)
    ):
        return RULE_EXEC_BIT
    if name in _sig._SUBPROCESS_RUNNERS and call.args and _weak_probe_argv(call.args[0]):
        return RULE_WEAK_PROBE
    return None


def scan_python_source(
    source: str, reported: str, gates: frozenset[str] = frozenset()
) -> list[Violation]:
    """Every venv interpreter trusted without a version check in one module's source."""
    tree = ast.parse(source)
    aliases = _sig._import_aliases(tree)
    scopes: list[ast.AST] = [tree]
    scopes += [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    violations: list[Violation] = []
    for scope in scopes:
        python_names = _python_names(scope)
        interp_vars = _interpreter_variables(scope, aliases, python_names)
        proven: bool | None = None
        for node in _sig._walk_scope(scope):
            if not isinstance(node, ast.Call):
                continue
            rule = _python_rule(node, aliases, interp_vars, python_names)
            if rule is None:
                continue
            if proven is None:
                proven = _is_version_proof_scope(scope, aliases, gates) or _runs_package_import(
                    scope, aliases
                )
            if not proven:
                violations.append(
                    Violation(file=reported, line=node.lineno, rule=rule, call=ast.unparse(node))
                )
    return _dedupe(violations)


# --- Shell -----------------------------------------------------------------

_SIMPLE_VARIABLE: Final = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def _is_interpreter_word(raw: str, interp_vars: set[str]) -> bool:
    text = _sig._unquote(raw)
    if _INTERP_TAIL.search(text) or _VENV_BIN_VARIABLE.search(text):
        return True
    match = _SIMPLE_VARIABLE.fullmatch(text)
    return match is not None and (match.group(1) or match.group(2)) in interp_vars


_SHELL_LOCAL_DECLARATIONS: Final = frozenset({"local", "declare", "typeset"})


def _shell_local_names(commands: list[_sig._Command]) -> set[str]:
    """Names a ``local``/``declare``/``typeset`` in ``commands`` makes function-private."""
    names: set[str] = set()
    for command in commands:
        words, _ = _sig._stripped(command.words)
        if not words or _sig._unquote(words[0].raw) not in _SHELL_LOCAL_DECLARATIONS:
            continue
        for word in words[1:]:
            text = _sig._unquote(word.raw)
            if not text.startswith("-"):
                names.add(text.split("=", 1)[0])
    return names


def _shell_interpreter_variables(
    commands: list[_sig._Command], seed: frozenset[str] = frozenset()
) -> set[str]:
    found: set[str] = set(seed)
    for _ in range(3):
        for command in commands:
            for word in command.words:
                match = _sig._ASSIGNMENT.match(word.raw)
                if match and (
                    _is_interpreter_word(match.group(2), found)
                    or _RESOLVER_CALL.search(match.group(2))
                ):
                    found.add(match.group(1))
            words, _ = _sig._stripped(command.words)
            if (
                len(words) > 3
                and _sig._unquote(words[0].raw) == "for"
                and _sig._unquote(words[2].raw) == "in"
                and any(_is_interpreter_word(w.raw, found) for w in words[3:])
            ):
                found.add(_sig._unquote(words[1].raw))
    return found


def _shell_existence_test(
    words: tuple[_sig._Word, ...], interp_vars: set[str], continuation: bool = False
) -> bool:
    """Whether ``words`` test an interpreter; ``continuation`` is the tail of a ``[[ a || b ]]``."""
    if not continuation and _sig._unquote(words[0].raw) not in _SHELL_TEST_HEADS:
        return False
    return any(
        _sig._unquote(word.raw) in _SHELL_TEST_OPERATORS
        and _is_interpreter_word(operand.raw, interp_vars)
        for word, operand in pairwise(words if continuation else words[1:])
    )


def _shell_weak_probe(words: tuple[_sig._Word, ...], interp_vars: set[str]) -> bool:
    head = _sig._unquote(words[0].raw)
    if "/" not in head and "$" not in head:
        return False
    args = [_sig._unquote(word.raw).strip() for word in words[1:]]
    if args == ["-c", _IMPORT_SYS]:
        return True
    if len(args) == 1 and args[0] in _VERSION_FLAGS:
        return _is_interpreter_word(words[0].raw, interp_vars) or bool(
            _PROBE_HEAD_HINT.search(head)
        )
    return False


def _shell_scope_text(lines: list[str], numbers: list[int]) -> str:
    """The code (comment lines dropped) on the 1-based line ``numbers``."""
    return "\n".join(
        lines[number - 1] for number in numbers if not lines[number - 1].lstrip().startswith("#")
    )


def _shell_scope_is_proven(
    commands: list[_sig._Command],
    lines: list[str],
    spans: list[tuple[int, int]],
    scope: tuple[int, int] | None,
    gates: frozenset[str],
) -> bool:
    if scope is None:
        inside = {n for first, last in spans for n in range(first, last + 1)}
        numbers = [n for n in range(1, len(lines) + 1) if n not in inside]
    else:
        numbers = list(range(scope[0], scope[1] + 1))
    text = _shell_scope_text(lines, numbers)
    if _SH_PYVENV_CFG.search(text) and _SH_VERSION.search(text):
        return True
    if _SH_PACKAGE_IMPORT.search(text):
        return True
    for command in commands:
        words, _ = _sig._stripped(command.words)
        if (
            words
            and _sig._unquote(words[0].raw) in gates
            and _sig._scope_of(words[0].line, spans) == scope
        ):
            return True
    return False


def scan_shell_source(
    text: str, reported: str, gates: frozenset[str] = frozenset()
) -> list[Violation]:
    """Every venv interpreter trusted without a version check in one script."""
    commands = _sig._shell_commands(text)
    lines = text.splitlines()
    spans = _sig._function_spans(lines)
    file_vars = _shell_interpreter_variables(commands)
    scope_vars: dict[tuple[int, int] | None, set[str]] = {}

    def interpreter_variables(scope: tuple[int, int] | None) -> set[str]:
        """File-wide interpreter variables, minus names the function declares local.

        A name declared local is a fresh variable: the outer binding does not reach it.
        A local that the function itself binds to an interpreter is found again here.
        """
        if scope is None:
            return file_vars
        if scope not in scope_vars:
            own = [
                c for c in commands if c.words and _sig._scope_of(c.words[0].line, spans) == scope
            ]
            visible = frozenset(file_vars - _shell_local_names(own))
            scope_vars[scope] = _shell_interpreter_variables(own, visible)
        return scope_vars[scope]

    proof: dict[tuple[int, int] | None, bool] = {}
    violations: list[Violation] = []
    in_double_bracket = False
    for command in commands:
        words, _ = _sig._stripped(command.words)
        if not words:
            continue
        continuation = in_double_bracket
        texts = [_sig._unquote(word.raw) for word in words]
        if "[[" in texts:
            in_double_bracket = "]]" not in texts[texts.index("[[") :]
        elif "]]" in texts:
            in_double_bracket = False
        line = words[0].line
        scope = _sig._scope_of(line, spans)
        interp_vars = interpreter_variables(scope)
        if _shell_existence_test(words, interp_vars, continuation):
            rule = RULE_EXEC_BIT
        elif _shell_weak_probe(words, interp_vars):
            rule = RULE_WEAK_PROBE
        else:
            continue
        if scope not in proof:
            proof[scope] = _shell_scope_is_proven(commands, lines, spans, scope, gates)
        if not proof[scope]:
            call = " ".join(word.raw for word in words)
            violations.append(Violation(file=reported, line=line, rule=rule, call=call))
    return _dedupe(violations)


# --- Gates -----------------------------------------------------------------


def _python_gate_is_proven(source: str, name: str) -> bool:
    tree = ast.parse(source)
    aliases = _sig._import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return _is_version_proof_scope(node, aliases, frozenset())
    return False


def _shell_gate_is_proven(text: str, name: str) -> bool:
    lines = text.splitlines()
    definition = re.compile(rf"^\s*(?:function\s+)?{re.escape(name)}\s*\(\)")
    for first, last in _sig._function_spans(lines):
        if definition.match(lines[first - 1]):
            body = _shell_scope_text(lines, list(range(first, last + 1)))
            return bool(_SH_PYVENV_CFG.search(body) and _SH_VERSION.search(body))
    return False


def proven_gates(gates: Mapping[str, str], read: Callable[[str], str]) -> frozenset[str]:
    """The gates whose own body reads pyvenv.cfg and compares a version.

    ``gates`` maps a gate name to the file defining it; ``read`` returns a
    file's text. A gate that is missing, or only probes, is not proof.
    """
    proven: set[str] = set()
    for name, path in gates.items():
        source = read(path)
        check = _python_gate_is_proven if path.endswith(".py") else _shell_gate_is_proven
        if check(source, name):
            proven.add(name)
    return frozenset(proven)


def _read_repo_file(path: str) -> str:
    return (_REPO_ROOT / path).read_text(encoding="utf-8")


# --- Files and entry point -------------------------------------------------


def in_scope(relative: str) -> bool:
    """Whether the repo-relative ``relative`` path is first-party code this Detector judges."""
    parts = relative.split("/")
    if parts[0] in _TOP_DIRS or relative.startswith(_WORKTREES_PREFIX):
        return False
    return not (_EXCLUDED_DIRS & set(parts[:-1]))


def scanned_files() -> tuple[list[Path], list[Path]]:
    """The tracked Python files and the tracked shell files the Detector judges."""
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    names = [name for name in result.stdout.split("\0") if name and in_scope(name)]
    paths = [_REPO_ROOT / name for name in names]
    candidates = [path for path in paths if path.is_file() and not path.is_symlink()]
    python = [path for path in candidates if _sig._is_python(path)]
    python_set = set(python)
    shell = [path for path in candidates if path not in python_set and _sig._is_shell(path)]
    return (
        sorted(_sig._without_protected_paths(python)),
        sorted(_sig._without_protected_paths(shell)),
    )


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    python_files, shell_files = scanned_files()
    gates = proven_gates(GATES, _read_repo_file)
    violations: list[Violation] = []
    for path in python_files:
        reported = str(_sig._repo_relative(path))
        violations += scan_python_source(path.read_text(encoding="utf-8"), reported, gates)
    for path in shell_files:
        reported = str(_sig._repo_relative(path))
        violations += scan_shell_source(path.read_text(encoding="utf-8"), reported, gates)
    violations.sort(key=lambda v: (v.file, v.line, v.rule))
    files_scanned = len(python_files) + len(shell_files)
    output = {
        "tool": "venv_interpreter_trust",
        "summary": {
            "passed": not violations,
            "total_violations": len(violations),
            "files_scanned": files_scanned,
        },
        "violations": [violation.to_dict() for violation in violations],
    }

    if "--json" in args:
        _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} venv interpreter(s) trusted without a version check:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  [{violation.rule}]  {violation.call}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No venv interpreter trusted without a version check ({files_scanned} files)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
