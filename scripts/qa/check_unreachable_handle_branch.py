#!/usr/bin/env python3
"""Fail when a handler's ``handle()`` does work under ``if not self.matches(...)``.

The chain calls ``handle()`` only after ``matches()`` returned True
(``core/chain.py``, ``core/front_controller.py``). A branch in ``handle()``
guarded by ``not self.matches(...)`` therefore runs only when a caller invokes
``handle()`` directly, which in this repository means a unit test. A bare
``return`` there is a harmless defensive guard. Anything else is behaviour that
the tests exercise and the product never executes, so the tests pass while the
product is broken.

Plan 00422 N29 is the originating instance: ``write_clobber_guard`` recorded a
successful ``Write`` in that branch, ``matches()`` returned False for exactly
those Writes, and a session that created a file with ``Write`` was denied
``R-WRITE-CLOBBER`` when it rewrote the file. Its unit test called ``handle()``
directly and passed.

The rule is syntactic and narrow on purpose: the ``if`` test must be
``not self.matches(...)`` and the body must hold anything other than one
``return``. A handler that re-checks its gate some other way is not seen.

Usage:
    python scripts/qa/check_unreachable_handle_branch.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "unreachable_handle_branch.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

_HANDLE_METHOD: Final[str] = "handle"
_MATCHES_METHOD: Final[str] = "matches"
_SELF: Final[str] = "self"
_RULE: Final[str] = "unreachable-handle-branch"

_REMEDIATION: Final[str] = (
    "Each site above does work in handle() on a branch taken only when\n"
    "matches() is False. The chain never calls handle() in that case, so the\n"
    "work runs in unit tests that call handle() directly and never in the\n"
    "daemon.\n"
    "\n"
    "Fix: make matches() return True for every input handle() must see, and\n"
    "let handle() choose the decision. Keep the `if not self.matches(...)`\n"
    "branch, if at all, as a bare `return` of an ALLOW.\n"
    "\n"
    "Test through the gate the chain applies: call handle() only when\n"
    "matches() returned True. See\n"
    "tests/unit/handlers/pre_tool_use/test_write_clobber_guard_dispatch.py."
)


@dataclass(frozen=True)
class Violation:
    """One ``if not self.matches(...)`` branch in ``handle()`` that does work."""

    file: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": _RULE,
            "message": (
                "handle() does work under `if not self.matches(...)`, a branch the "
                "chain never reaches; move the input into matches()"
            ),
        }


def _is_negated_self_matches(test: ast.expr) -> bool:
    """Whether ``test`` is ``not self.matches(...)``."""
    if not isinstance(test, ast.UnaryOp) or not isinstance(test.op, ast.Not):
        return False
    call = test.operand
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return False
    receiver = call.func.value
    return (
        call.func.attr == _MATCHES_METHOD
        and isinstance(receiver, ast.Name)
        and receiver.id == _SELF
    )


def _is_bare_return(body: list[ast.stmt]) -> bool:
    """Whether a branch body is one ``return``, allowing a leading docstring-style string."""
    statements = [
        statement
        for statement in body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]
    return len(statements) == 1 and isinstance(statements[0], ast.Return)


def _handle_methods(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for member in node.body:
            if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                if member.name == _HANDLE_METHOD:
                    methods.append(member)
    return methods


def scan_file(path: Path) -> list[Violation]:
    """Every offending branch in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    violations: list[Violation] = []
    for method in _handle_methods(tree):
        for node in ast.walk(method):
            if not isinstance(node, ast.If) or not _is_negated_self_matches(node.test):
                continue
            if _is_bare_return(node.body):
                continue
            violations.append(Violation(file=reported, line=node.lineno))
    return violations


def scan_tree(scan_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        violations.extend(scan_file(path))
    return violations


def main() -> int:
    json_mode = "--json" in sys.argv
    scan_root = _DEFAULT_SCAN_ROOT
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            scan_root = Path(args[index + 1]).resolve()

    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    files_scanned = len(list(scan_root.rglob("*.py"))) if scan_root.is_dir() else 0
    violations = scan_tree(scan_root) if scan_root.is_dir() else []

    output = {
        "tool": "unreachable_handle_branch",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "files_scanned": files_scanned,
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        # A --path scan reports beside what it scanned rather than overwriting
        # the repository artefact llm_qa publishes as this check's evidence.
        output_file = (
            scan_root / _ARTEFACT_NAME if scan_root != _DEFAULT_SCAN_ROOT else _OUTPUT_FILE
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} handle() branch(es) the chain never reaches:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  if not self.matches(...)")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No unreachable handle() branches found ({files_scanned} files scanned)")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
