#!/usr/bin/env python3
"""Fail when a tree-sized git mutation runs on a fixed wall-clock budget.

The class is `fixed-budget-on-load-scaled-subprocess`. Hazard: a fixed timeout
on a subprocess whose duration scales with host load or tree size turns a slow
host into a hard failure, and when the failure path (the cleanup) spends the
same kind of short budget, the half-done work cannot be undone either.

Originating instance: ``WorktreeCreateHandler._git_worktree_add`` ran
``git worktree add`` on a 30 s budget at a host load average of about 70. It
timed out, the handler crashed into a deny, and the cleanup (5 s per call) could
not remove the half-populated checkout directory it left behind.

The rule reads code: in any function that names the git verb ``worktree add`` or
``worktree remove`` (both write a whole checkout), every ``run_git`` / ``run_fn``
call must pass a ``timeout=`` that contains a ``scaled_timeout(...)`` call, so the
budget follows the host load. A call with no ``timeout=`` takes the 5 s default
and is reported too. ``worktree list`` and other metadata reads are not covered:
they gate nothing irreversible.

A reviewed exception is declared in ``_ALLOWED`` with the reason and the ledger
entry that tracks it; an allowlist row that matches nothing is itself reported,
so the list cannot rot.

Usage:
    python scripts/qa/check_fixed_git_budget.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation, a rotted allowlist row, or no file examined
"""

from __future__ import annotations

import ast
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to
from claude_code_hooks_daemon.utils.scan_scope import vacuous_scan_failure, walk_files

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "fixed_worktree_budget.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME
_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

_RULE: Final[str] = "fixed-git-budget"
_GIT_RUNNERS: Final[frozenset[str]] = frozenset({"run_git", "run_fn"})
_SCALING_VERB: Final[str] = "worktree"
_SCALING_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"add", "remove"})
_SCALER: Final[str] = "scaled_timeout"
#: ``scaled_timeout`` and the handler's own one-line wrapper over it.
_SCALERS: Final[frozenset[str]] = frozenset({_SCALER, "_cleanup_budget"})
_TIMEOUT_KEYWORD: Final[str] = "timeout"

#: (path relative to the scan root, function name) -> why it is allowed.
_ALLOWED: Final[dict[tuple[str, str], str]] = {
    (
        "handlers/worktree_remove/worktree_remove_handler.py",
        "_remove",
    ): (
        "WorktreeRemove's budget is the event's static handler budget, which the "
        "client wait mirrors; scaling it means moving that table (ledger N621)"
    ),
}

_REMEDIATION: Final[str] = (
    "Each site above runs a tree-sized git mutation on a fixed budget. Under\n"
    "host load it times out, and a cleanup on the same short budget cannot undo\n"
    "the half-done work.\n"
    "\n"
    "Fix: pass timeout=scaled_timeout(<base>, <ceiling>) from\n"
    "claude_code_hooks_daemon.utils.load_scaling, on the mutation AND on every\n"
    "git call of its failure path, and make the failure path remove what the\n"
    "caller created even when git does not know it."
)


@dataclass(frozen=True)
class Violation:
    """One git call on a fixed budget inside a worktree-writing function."""

    file: str
    line: int
    function: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": _RULE,
            "function": self.function,
            "message": self.detail,
        }


def _string_runs(node: ast.AST) -> list[list[str]]:
    """The runs of literal strings in one tuple, list or call argument list."""
    elements: list[ast.expr]
    if isinstance(node, ast.Tuple | ast.List):
        elements = list(node.elts)
    elif isinstance(node, ast.Call):
        elements = list(node.args)
    else:
        return []
    runs: list[list[str]] = [[]]
    for element in elements:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            runs[-1].append(element.value)
        else:
            runs.append([])
    return runs


def _names_scaling_verb(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the function names ``worktree add`` or ``worktree remove`` literally."""
    for node in ast.walk(function):
        for run in _string_runs(node):
            for first, second in itertools.pairwise(run):
                if first == _SCALING_VERB and second in _SCALING_SUBCOMMANDS:
                    return True
    return False


def _runner_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _contains_scaler(expression: ast.AST, scaled_names: set[str]) -> bool:
    """Whether the expression calls a scaler or reads a name bound from one."""
    for node in ast.walk(expression):
        if isinstance(node, ast.Call) and _runner_name(node) in _SCALERS:
            return True
        if isinstance(node, ast.Name) and node.id in scaled_names:
            return True
    return False


def _scaled_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Local names assigned from an expression that calls a scaler."""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _contains_scaler(node.value, set()):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _is_scaled(call: ast.Call, scaled_names: set[str]) -> bool:
    """Whether the call's ``timeout=`` is derived from a load scaler."""
    for keyword in call.keywords:
        if keyword.arg == _TIMEOUT_KEYWORD:
            return _contains_scaler(keyword.value, scaled_names)
    return False


def scan_file(path: Path, root: Path) -> tuple[list[Violation], set[tuple[str, str]]]:
    """Violations in one module, and the allowlist keys that matched in it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path_relative_to(path, root).as_posix() if path_is_relative_to(path, root) else ""
    reported = (
        str(path_relative_to(path, _REPO_ROOT))
        if path_is_relative_to(path, _REPO_ROOT)
        else str(path)
    )
    violations: list[Violation] = []
    matched: set[tuple[str, str]] = set()
    seen: set[int] = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _names_scaling_verb(function):
            continue
        key = (relative, function.name)
        scaled = _scaled_names(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or _runner_name(node) not in _GIT_RUNNERS:
                continue
            if _is_scaled(node, scaled) or node.lineno in seen:
                continue
            seen.add(node.lineno)
            if key in _ALLOWED:
                matched.add(key)
                continue
            violations.append(
                Violation(
                    file=reported,
                    line=node.lineno,
                    function=function.name,
                    detail=(
                        f"{function.name}() writes a worktree but this git call has a fixed "
                        f"budget; wrap its timeout in {_SCALER}(...)"
                    ),
                )
            )
    return violations, matched


def scan_tree(scan_root: Path) -> tuple[list[Violation], list[Violation]]:
    """Return (violations, rotted allowlist rows)."""
    violations: list[Violation] = []
    matched: set[tuple[str, str]] = set()
    for path in walk_files(scan_root, "*.py"):
        found, used = scan_file(path, scan_root)
        violations.extend(found)
        matched |= used
    rotted = [
        Violation(
            file=file, line=0, function=function, detail=f"allowlist row matches nothing: {why}"
        )
        for (file, function), why in _ALLOWED.items()
        if (file, function) not in matched and (scan_root / file).exists()
    ]
    return violations, rotted


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    scan_root = _DEFAULT_SCAN_ROOT
    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            scan_root = Path(args[index + 1]).resolve()

    files_scanned = len(walk_files(scan_root, "*.py"))
    violations, rotted = scan_tree(scan_root)
    problems = [*violations, *rotted]
    vacuous = vacuous_scan_failure(examined=files_scanned, noun="Python files", root=scan_root)

    output = {
        "tool": "fixed_worktree_budget",
        "summary": {
            "passed": not problems and vacuous is None,
            "vacuous_scan": vacuous,
            "total_violations": len(problems),
            "files_scanned": files_scanned,
        },
        "violations": [v.to_dict() for v in problems],
    }
    if "--json" in args:
        output_file = (
            scan_root / _ARTEFACT_NAME if scan_root != _DEFAULT_SCAN_ROOT else _OUTPUT_FILE
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))

    if vacuous is not None:
        print(f"FAILED: {vacuous}")
    elif problems:
        print(f"Found {len(problems)} fixed-budget git call(s) on a worktree write:")
        for problem in problems:
            print(f"  {problem.file}:{problem.line}  {problem.detail}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No fixed-budget worktree git calls found ({files_scanned} files scanned)")
    return 1 if problems or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
