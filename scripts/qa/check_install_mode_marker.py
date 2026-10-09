#!/usr/bin/env python3
"""Fail when a file other than the two definitions decides the install mode itself.

"Is this checkout a self-install (the daemon's own repository) or a client
project" has exactly two definitions:

- ``src/claude_code_hooks_daemon/daemon/install_layout.py`` -- Python; its
  ``is_self_install_mode`` and ``get_untracked_dir``.
- ``scripts/install/mode_guard.sh`` -- shell; ``is_self_install_checkout``.

Every other file asks one of them. A file that instead TESTS whether
``src/claude_code_hooks_daemon`` exists is a third copy, and the copies drift:
three of the first four Python ones used ``.exists()`` where the rule is
``.is_dir()``, so a FILE at that path read as a self-install in one place and
as a client install in the rest.

**Deciding versus scanning.** The same path is all over this repository,
because the QA scripts SCAN the source tree
(``REPO_ROOT / "src" / "claude_code_hooks_daemon"``). Building that path, or
checking that the scanner's own tree is present, is not a decision. A decision
asks about a root the CALLER supplied: a function parameter, an attribute, the
environment, the working directory. A scan builds from where the script itself
lives. The Python half therefore flags a stat call (``exists``, ``is_dir``,
``os.path.isdir`` ...) on a path that ENDS at the package directory, directly
or through a name bound to it, unless the path's root is anchored to
``__file__`` (``_REPO_ROOT = Path(__file__)...``). A path that goes deeper
(``.../version.py``, ``.../handlers``) is a file read or a scan, not the mode
marker. The shell half flags ``[ -d ... ]``, ``[[ -e ... ]]`` and ``test -d``
on a path ending at the package directory, directly or through a variable
assigned from one.

There is no exemption marker: call the rule.

Usage:
    python scripts/qa/check_install_mode_marker.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation, or no file was examined
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.path_containment import path_relative_to
from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "install_mode_marker.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

_RULE: Final[str] = "install-mode-marker"
_UNREADABLE_RULE: Final[str] = "install-mode-marker-unreadable"

#: The marker: the daemon SOURCE directory at a project root.
_MARKER_PARTS: Final[tuple[str, str]] = ("src", "claude_code_hooks_daemon")
_MARKER_TEXT: Final[str] = "/".join(_MARKER_PARTS)

#: The two definitions, relative to the scan root. Nothing else is exempt.
_DEFINITIONS: Final[frozenset[str]] = frozenset(
    {"src/claude_code_hooks_daemon/daemon/install_layout.py", "scripts/install/mode_guard.sh"}
)

#: Gitignored runtime state and other checkouts, never project source. Matched
#: on the path BELOW the scan root (00466 N26), never on the absolute path.
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

_PYTHON_SUFFIX: Final[str] = ".py"
_SHELL_SUFFIXES: Final[frozenset[str]] = frozenset({".sh", ".bash"})
_SHEBANG: Final[str] = "#!"
_SHELL_INTERPRETERS: Final[frozenset[str]] = frozenset({"sh", "bash", "dash", "zsh"})
_MAX_BYTES: Final[int] = 2_000_000

#: Stat predicates that answer "is the marker there".
_PATH_PREDICATES: Final[frozenset[str]] = frozenset({"exists", "is_dir", "is_file", "is_symlink"})
_OS_PATH_PREDICATES: Final[frozenset[str]] = frozenset({"exists", "isdir", "isfile", "lexists"})
#: Calls that return the same path they are called on.
_PATH_IDENTITY_METHODS: Final[frozenset[str]] = frozenset({"resolve", "absolute", "expanduser"})
_PATH_WRAPPERS: Final[frozenset[str]] = frozenset({"str", "Path", "PurePath", "fspath"})
_FILE_NAME: Final[str] = "__file__"
_BINDING_DEPTH: Final[int] = 4

_PY_FIX: Final[str] = (
    "call daemon.install_layout.is_self_install_mode (or get_untracked_dir) instead of "
    "testing for src/claude_code_hooks_daemon yourself"
)
_SH_FIX: Final[str] = (
    "call is_self_install_checkout from scripts/install/mode_guard.sh instead of "
    "testing for src/claude_code_hooks_daemon yourself"
)

_REMEDIATION: Final[str] = (
    "Each site above tests whether the daemon source directory is present in order to\n"
    "DECIDE the install mode. The rule has two definitions and no third:\n"
    "\n"
    "  Python  daemon/install_layout.py    is_self_install_mode, get_untracked_dir\n"
    "  shell   scripts/install/mode_guard.sh    is_self_install_checkout\n"
    "\n"
    "A script that must run without the package loads install_layout.py by file path\n"
    "(see daemon/signal_standalone.py). Building the path to SCAN the source tree is\n"
    "not a decision and is not reported; neither is a path that goes deeper than the\n"
    "package directory. There is no exemption marker."
)


@dataclass(frozen=True)
class Violation:
    """One file deciding the install mode itself."""

    file: str
    line: int
    rule: str = _RULE
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "rule": self.rule, "message": self.message}


# ── Python ────────────────────────────────────────────────────────────────────


def _split_parts(text: str) -> list[str | None]:
    return [segment for segment in text.split("/") if segment]


class _Scope:
    """The names one function (or the module) binds, and the parameters it takes."""

    def __init__(self, node: ast.AST) -> None:
        self.bindings: dict[str, list[ast.expr]] = {}
        self.parameters: set[str] = set()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            self.parameters.update(a.arg for a in every)
            self.parameters.update(a.arg for a in (args.vararg, args.kwarg) if a is not None)
        for child in _walk_scope(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        self.bindings.setdefault(target.id, []).append(child.value)
            elif (
                isinstance(child, ast.AnnAssign)
                and child.value is not None
                and isinstance(child.target, ast.Name)
            ):
                self.bindings.setdefault(child.target.id, []).append(child.value)


def _walk_scope(scope: ast.AST) -> list[ast.AST]:
    """Every node in ``scope``, not descending into a nested function or class."""
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        nodes.append(node)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return nodes


class _Resolver:
    """Resolves a path expression to its root and its trailing components."""

    def __init__(self, module: _Scope, function: _Scope | None) -> None:
        self._module = module
        self._function = function
        self._tuples = {
            name: _constant_parts(values[-1])
            for name, values in module.bindings.items()
            if _constant_parts(values[-1]) is not None
        }

    def bindings_of(self, name: str) -> list[ast.expr]:
        if self._function is not None and name in self._function.bindings:
            return self._function.bindings[name]
        if self._function is not None and name in self._function.parameters:
            return []
        return self._module.bindings.get(name, [])

    def candidates(self, expr: ast.expr, depth: int = _BINDING_DEPTH) -> list[ast.expr]:
        """``expr``, plus what each name in it was bound to (a bounded number of hops)."""
        if isinstance(expr, ast.Name) and depth > 0:
            found: list[ast.expr] = []
            for value in self.bindings_of(expr.id):
                found.extend(self.candidates(value, depth - 1))
            return found
        return [expr]

    def flatten(self, expr: ast.expr) -> tuple[ast.expr | None, list[str | None]]:
        """``(root, trailing components)``; a component that is not a literal is ``None``."""
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return None, list(_split_parts(expr.value))
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            root, parts = self.flatten(expr.left)
            return root, [*parts, *self._component(expr.right)]
        if isinstance(expr, ast.JoinedStr):
            return self._flatten_f_string(expr)
        if isinstance(expr, ast.Call):
            return self._flatten_call(expr)
        return expr, []

    def _component(self, expr: ast.expr) -> list[str | None]:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return list(_split_parts(expr.value))
        return [None]

    def _flatten_call(self, call: ast.Call) -> tuple[ast.expr | None, list[str | None]]:
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "joinpath":
            root, parts = self.flatten(func.value)
            return root, [*parts, *self._arguments(call.args)]
        if isinstance(func, ast.Attribute) and func.attr == "join" and _is_os_path(func.value):
            if not call.args:
                return call, []
            root, parts = self.flatten(call.args[0])
            return root, [*parts, *self._arguments(call.args[1:])]
        if isinstance(func, ast.Attribute) and func.attr in _PATH_IDENTITY_METHODS:
            return self.flatten(func.value)
        if isinstance(func, ast.Name) and func.id in _PATH_WRAPPERS and call.args:
            root, parts = self.flatten(call.args[0])
            return root, [*parts, *self._arguments(call.args[1:])]
        return call, []

    def _arguments(self, args: list[ast.expr]) -> list[str | None]:
        parts: list[str | None] = []
        for arg in args:
            if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                known = self._tuples.get(arg.value.id)
                parts.extend(known if known is not None else [None])
            else:
                parts.extend(self._component(arg))
        return parts

    def _flatten_f_string(self, node: ast.JoinedStr) -> tuple[ast.expr | None, list[str | None]]:
        root: ast.expr | None = None
        text = ""
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                if root is None and not text:
                    root = value.value
                text = ""
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                text += value.value
        return root, list(_split_parts(text))

    def is_anchored(self, expr: ast.expr | None, depth: int = _BINDING_DEPTH) -> bool:
        """Whether ``expr`` is rooted where the script itself lives (``__file__``)."""
        if expr is None:
            return False
        names = [n for n in ast.walk(expr) if isinstance(n, ast.Name)]
        if any(n.id == _FILE_NAME for n in names):
            return True
        if depth == 0:
            return False
        if self._function is not None and any(n.id in self._function.parameters for n in names):
            return False
        bound = [n for n in names if self.bindings_of(n.id)]
        if not bound:
            return False
        return all(
            all(self.is_anchored(value, depth - 1) for value in self.bindings_of(n.id))
            for n in bound
        )


def _constant_parts(node: ast.expr) -> list[str | None] | None:
    """The literal strings of a tuple or list, or None when it is not one."""
    if isinstance(node, ast.Tuple | ast.List) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    ):
        return [
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    return None


def _is_os_path(node: ast.expr) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "path") or (
        isinstance(node, ast.Name) and node.id == "path"
    )


def _predicate_target(call: ast.Call) -> ast.expr | None:
    """The path a stat call asks about, or None when the call is not one."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in _OS_PATH_PREDICATES and _is_os_path(func.value) and call.args:
        return call.args[0]
    if func.attr in _PATH_PREDICATES:
        return func.value
    return None


def _ends_at_marker(parts: list[str | None]) -> bool:
    return tuple(parts[-len(_MARKER_PARTS) :]) == _MARKER_PARTS


def _decides(call: ast.Call, resolver: _Resolver) -> bool:
    target = _predicate_target(call)
    if target is None:
        return False
    for candidate in resolver.candidates(target):
        root, parts = resolver.flatten(candidate)
        if _ends_at_marker(parts) and not resolver.is_anchored(root):
            return True
    return False


def _python_decisions(tree: ast.Module) -> list[int]:
    module_scope = _Scope(tree)
    lines: set[int] = set()
    scopes: list[tuple[ast.AST, _Scope | None]] = [(tree, None)]
    scopes.extend(
        (node, _Scope(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )
    for scope_node, scope in scopes:
        resolver = _Resolver(module_scope, scope)
        lines.update(
            node.lineno
            for node in _walk_scope(scope_node)
            if isinstance(node, ast.Call) and _decides(node, resolver)
        )
    return sorted(lines)


# ── Shell ─────────────────────────────────────────────────────────────────────

_SHELL_TEST: Final[re.Pattern[str]] = re.compile(
    r"(?:\[\[?|\btest|&&|\|\||!)\s+(?:!\s+)?-[defLhs]\s+" r"(?P<arg>\"[^\"]*\"|'[^']*'|[^\s\]]+)"
)
_SHELL_ASSIGN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:(?:local|readonly|export)\s+)?(?P<name>[A-Za-z_]\w*)=(?P<value>\"[^\"]*\"|'[^']*'|\S+)"
)
_SHELL_VARIABLE: Final[re.Pattern[str]] = re.compile(r"^\$(?:\{(?P<braced>\w+)\}|(?P<bare>\w+))$")


def _ends_at_marker_text(text: str) -> bool:
    return text.rstrip("/").endswith("/" + _MARKER_TEXT) or text.rstrip("/") == _MARKER_TEXT


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _shell_decisions(source: str) -> list[int]:
    marker_variables: set[str] = set()
    lines: list[int] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        if raw.lstrip().startswith("#"):
            continue
        assignment = _SHELL_ASSIGN.match(raw)
        if assignment and _ends_at_marker_text(_unquote(assignment.group("value"))):
            marker_variables.add(assignment.group("name"))
        for test in _SHELL_TEST.finditer(raw):
            argument = _unquote(test.group("arg"))
            variable = _SHELL_VARIABLE.match(argument)
            if _ends_at_marker_text(argument) or (
                variable is not None
                and (variable.group("braced") or variable.group("bare")) in marker_variables
            ):
                lines.append(number)
                break
    return lines


# ── Walk ──────────────────────────────────────────────────────────────────────


def _is_shell(path: Path, head: str) -> bool:
    """Whether ``path`` is a shell script: by suffix, or an extensionless shebang."""
    if path.suffix in _SHELL_SUFFIXES:
        return True
    if path.suffix or not head.startswith(_SHEBANG):
        return False
    words = head[len(_SHEBANG) :].split()
    return any(Path(word).name in _SHELL_INTERPRETERS for word in words[:2])


def _candidate_files(root: Path) -> list[Path]:
    return [
        path
        for path in walk_files(root)
        if not any(part in _SKIP_DIRS for part in relative_parts(path, root))
        and path.is_file()
        and not path.is_symlink()
        and (path.suffix == _PYTHON_SUFFIX or path.suffix in _SHELL_SUFFIXES or not path.suffix)
    ]


def _unreadable(relative: str, why: str) -> Violation:
    return Violation(
        file=relative,
        line=0,
        rule=_UNREADABLE_RULE,
        message=f"could not be read ({why}), so it cannot be shown free of an install-mode test",
    )


def _scan_file(path: Path, relative: str) -> tuple[bool, list[Violation]]:
    """``(examined, violations)`` for one file; ``examined`` is False when it is not code."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            return False, []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return True, [_unreadable(relative, str(exc))]
    if path.suffix == _PYTHON_SUFFIX:
        try:
            lines = _python_decisions(ast.parse(text))
        except SyntaxError:
            # Python that does not parse cannot run, so it decides nothing; the
            # lint gate owns that defect (the tree keeps deliberate syntax-error
            # fixtures for the handlers' own loader tests).
            return True, []
        fix = _PY_FIX
    elif _is_shell(path, text.split("\n", 1)[0]):
        lines = _shell_decisions(text)
        fix = _SH_FIX
    else:
        return False, []
    if relative in _DEFINITIONS:
        return True, []
    return True, [
        Violation(file=relative, line=line, message=f"decides the install mode itself; {fix}")
        for line in lines
    ]


def scan(root: Path) -> tuple[list[Violation], int, int]:
    """``(violations, files examined, files seen)`` below ``root``."""
    seen = walk_files(root)
    violations: list[Violation] = []
    examined = 0
    for path in _candidate_files(root):
        was_examined, found = _scan_file(path, path_relative_to(path, root).as_posix())
        examined += was_examined
        violations.extend(found)
    return sorted(violations, key=lambda v: (v.file, v.line)), examined, len(seen)


def scan_tree(root: Path) -> list[Violation]:
    """Every violation below ``root``."""
    return scan(root)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_REPO_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    violations, examined, seen = scan(root)
    vacuous = vacuous_scan_failure(examined=examined, candidates=seen, noun="files", root=root)

    if args.json_output:
        # A --path scan answers "is this DIRECTORY clean", which is not the
        # question the repository artefact answers; it reports beside what it scanned.
        output_file = root / _ARTEFACT_NAME if root != _REPO_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(
                {
                    "tool": "install_mode_marker",
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
        print(f"Found {len(violations)} file(s) deciding the install mode themselves:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  {violation.message}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No file but the two definitions decides the install mode ({examined} scanned)")
    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
