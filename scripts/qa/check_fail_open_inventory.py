#!/usr/bin/env python3
"""Fail when the enforcement path grows a fail-open boundary nobody declared.

The class -- `fail-open-when-the-check-cannot-run` -- is the one where the
guarded action proceeds because the guard could not reach a verdict, and where
in several instances the party the guard constrains can INDUCE the condition:
a large staged commit, an ESLint spawn, a tree-wide QA gate. "Make the guard
slow, and the guard is skipped."

**Why an inventory and not a code rule.** The discriminator is a property of
the surface, not of the code. `sensitive_content`'s staged-diff stand-down and
its `gh`-body stand-down are the same shape, and one is defensible while the
other is not -- a commit can be amended before it is pushed, a published
comment cannot be recalled. No regex sees that difference, and a general
`except`-scan over the tree is noisy enough that it would be switched off
rather than satisfied. So this script enumerates CANDIDATES mechanically over a
small, named scope, and the inventory carries the JUDGEMENT: one row per
candidate, written by someone who read the site.

Uniquely for this class, the test suite is not merely silent -- it *encodes*
the behaviour. `test_timeout_fail_open`, `test_missing_body_file_is_allowed`
and their siblings positively verify the fail-open, and read to a reviewer as
deliberate coverage of the branch. Coverage of a fail-open is not a defence
against one.

Three columns are required of every `fail-open` row: what induces it, whether
the inducing input is caller-controlled, and what trace it leaves in-band. The
third is the valuable one -- several of these boundaries currently leave a
single stderr line, which nothing downstream reads.

Scope is deliberately hard-coded rather than configurable: the scope IS the
design, and a scope that can be narrowed in config can be narrowed silently.

Usage:
    python scripts/qa/check_fail_open_inventory.py [--json] [--inventory F]

Exit codes:
    0 -- every boundary in scope is declared and every row is complete
    1 -- an undeclared boundary, an incomplete row, or a row that has rotted
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from claude_code_hooks_daemon.utils.path_predicates import TextOrReason, read_text_or_reason

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "fail_open_inventory.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME
_DEFAULT_INVENTORY: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "fail-open-boundaries.yaml"

_RULE: Final[str] = "fail-open-inventory"

#: The enforcement path: where a tool call is judged, and where a failure to
#: judge lets the call through. Named by F-BYPS in the run 2026-001 corpus.
_PYTHON_SURFACES: Final[tuple[str, ...]] = (
    "src/claude_code_hooks_daemon/core/chain.py",
    "src/claude_code_hooks_daemon/core/front_controller.py",
    "src/claude_code_hooks_daemon/daemon/controller.py",
)
_RUST_SURFACES: Final[tuple[str, ...]] = ("relay/hooks_relay.rs",)
#: `.claude/init.sh` is a symlink to this; the real file is the surface.
_SHELL_SURFACES: Final[tuple[str, ...]] = ("init.sh",)

#: A Rust fail funnel is spelled by its return type: `-> !` never returns, so
#: every call site of one is an exit decision rather than an error to handle.
_RUST_FUNNEL_RE: Final[re.Pattern[str]] = re.compile(r"^\s*fn\s+([A-Za-z0-9_]+)\s*\(.*->\s*!\s*\{")

#: Shell constructs that let a failing command pass. `2>/dev/null` is included
#: because discarding a diagnostic is how a shell boundary leaves no trace,
#: which is exactly column three.
_SHELL_SUPPRESSIONS: Final[tuple[str, ...]] = ("2>/dev/null", "|| true", "|| :", "set +e")
_SHELL_FN_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?:function\s+)?([A-Za-z0-9_.-]+)\s*\(\)")
#: A closing brace in column zero ends a shell function body. `init.sh` holds
#: twenty function headers and exactly twenty of these, so the pairing is the
#: file's actual style rather than an assumption about shell in general.
_SHELL_SCOPE_END_RE: Final[re.Pattern[str]] = re.compile(r"^\}")

_TOPLEVEL: Final[str] = "<toplevel>"

_VERDICT_FAIL_OPEN: Final[str] = "fail-open"
_VERDICT_NOT_FAIL_OPEN: Final[str] = "not-fail-open"
_VERDICTS: Final[frozenset[str]] = frozenset({_VERDICT_FAIL_OPEN, _VERDICT_NOT_FAIL_OPEN})

#: Required of a row that admits the boundary is fail-open. `caller_controlled`
#: is checked separately because `False` is a legitimate value and a blank test
#: would reject it.
_FAIL_OPEN_TEXT_FIELDS: Final[tuple[str, ...]] = ("induced_by", "trace")

_REMEDIATION: Final[str] = (
    "Each line above is a place where the guarded action proceeds because the\n"
    "guard could not reach a verdict -- and the inventory does not describe it.\n"
    "\n"
    "Add a row to scripts/qa/fail-open-boundaries.yaml. Declaring a boundary is\n"
    "NOT the same as accepting it: the row records what induces the condition,\n"
    "whether the party the guard constrains can induce it, and what trace it\n"
    "leaves in-band. A boundary whose only trace is a stderr line nothing reads\n"
    "is the finding, and the row is where that becomes visible.\n"
    "\n"
    "If the boundary is not fail-open -- it re-raises into a deny, or it runs\n"
    "before any tool call is judged -- say so with verdict: not-fail-open and a\n"
    "reason. The reason is the reviewable part; an unexplained dismissal is\n"
    "indistinguishable from an unexamined one.\n"
    "\n"
    "Do NOT widen the surface list to make a boundary disappear. The scope is\n"
    "the enforcement path, and shrinking it is how this Defence stops working."
)


@dataclass(frozen=True)
class Boundary:
    """One mechanically-found candidate in the enforcement path."""

    surface: str
    scope: str
    construct: str
    ordinal: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.surface, self.scope, self.construct, self.ordinal)


@dataclass(frozen=True)
class Violation:
    surface: str
    scope: str
    construct: str
    ordinal: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": _RULE,
            "surface": self.surface,
            "scope": self.scope,
            "construct": self.construct,
            "ordinal": self.ordinal,
            "detail": self.detail,
        }


def _enclosing_python_scopes(tree: ast.Module) -> dict[int, str]:
    """Nearest enclosing function name for each line.

    ``ast.walk`` is breadth-first, so a nested function is visited after the
    one containing it and its name overwrites the parent's -- which is the name
    a reader would use to find the handler again.
    """
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner[line] = node.name
    return owner


def _reraises(handler: ast.ExceptHandler) -> bool:
    """Does this handler propagate?

    A handler that re-raises is not a fail-open boundary -- the caller still
    gets the failure. This is the predicate that keeps the inventory to a size
    a person will fill in honestly rather than a list of every `except` in the
    file, so the test suite holds it with a control pair that differ only by
    the `raise`.
    """
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _python_boundaries(surface: str, source: str) -> list[Boundary]:
    tree = ast.parse(source)
    owner = _enclosing_python_scopes(tree)
    seen: dict[tuple[str, str], int] = {}
    found: list[Boundary] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or _reraises(node):
            continue
        caught = ast.unparse(node.type) if node.type else "bare"
        scope = owner.get(node.lineno, _TOPLEVEL)
        construct = f"except {caught}"
        ordinal = seen.get((scope, construct), 0)
        seen[(scope, construct)] = ordinal + 1
        found.append(Boundary(surface, scope, construct, ordinal))
    return found


def _rust_boundaries(surface: str, source: str) -> list[Boundary]:
    seen: dict[tuple[str, str], int] = {}
    found: list[Boundary] = []
    for line in source.splitlines():
        match = _RUST_FUNNEL_RE.match(line)
        if match is None:
            continue
        scope = match.group(1)
        construct = "diverging fail funnel"
        ordinal = seen.get((scope, construct), 0)
        seen[(scope, construct)] = ordinal + 1
        found.append(Boundary(surface, scope, construct, ordinal))
    return found


def _shell_boundaries(surface: str, source: str) -> list[Boundary]:
    """Candidates in a shell surface, each attributed to the function it is in.

    The scope ENDS at the function's closing brace. Carrying the last header
    seen forwards would attribute every top-level suppression to whichever
    function happened to be defined above it -- and a location the inventory
    reports wrongly is worse than one it omits, because it is the location the
    next reader will trust.
    """
    seen: dict[tuple[str, str], int] = {}
    found: list[Boundary] = []
    scope = _TOPLEVEL
    for line in source.splitlines():
        function = _SHELL_FN_RE.match(line)
        if function is not None:
            scope = function.group(1)
        elif _SHELL_SCOPE_END_RE.match(line):
            scope = _TOPLEVEL
        for suppression in _SHELL_SUPPRESSIONS:
            if suppression not in line:
                continue
            ordinal = seen.get((scope, suppression), 0)
            seen[(scope, suppression)] = ordinal + 1
            found.append(Boundary(surface, scope, suppression, ordinal))
    return found


def _read_surface(repo_root: Path, surface: str) -> TextOrReason:
    """Source text, or the reason it could not be read.

    Deliberately NOT `str | None`: an unreadable surface is reported as a
    violation carrying the errno, never skipped. A scope that has quietly
    stopped being scanned reads exactly like a scope with nothing in it, which
    is the failure this whole register is about -- and a bare None would make
    "missing" and "empty" indistinguishable inside this script too.
    """
    return read_text_or_reason(repo_root / surface)


def collect_boundaries(repo_root: Path) -> tuple[list[Boundary], list[Violation]]:
    """Every candidate in scope, plus a violation per surface that vanished."""
    boundaries: list[Boundary] = []
    missing: list[Violation] = []
    extractors = (
        (_PYTHON_SURFACES, _python_boundaries),
        (_RUST_SURFACES, _rust_boundaries),
        (_SHELL_SURFACES, _shell_boundaries),
    )
    for surfaces, extract in extractors:
        for surface in surfaces:
            read = _read_surface(repo_root, surface)
            if read.text is None:
                missing.append(
                    Violation(
                        surface=surface,
                        scope=_TOPLEVEL,
                        construct="surface",
                        ordinal=0,
                        detail=(
                            f"declared enforcement surface is unreadable ({read.reason}), so "
                            "nothing in it was scanned -- fix the path or remove it from the "
                            "scope deliberately"
                        ),
                    )
                )
                continue
            boundaries.extend(extract(surface, read.text))
    return boundaries, missing


def count_boundaries(repo_root: Path) -> int:
    """The denominator: how many candidates the scan actually looked at."""
    boundaries, _ = collect_boundaries(repo_root)
    return len(boundaries)


def _row_key(row: dict[str, object]) -> tuple[str, str, str, int]:
    """The identity a row claims, in the same shape a Boundary reports.

    A non-integer `ordinal` reads as 0 rather than raising: the row then fails
    to match the boundary it meant to cover and is reported as rotted, which
    says "this row does not describe anything" -- the honest outcome for a
    typo, and better than a traceback that names YAML instead of the row.
    """
    ordinal = row.get("ordinal", 0)
    return (
        str(row.get("surface", "")),
        str(row.get("scope", "")),
        str(row.get("construct", "")),
        ordinal if isinstance(ordinal, int) else 0,
    )


def load_inventory(inventory_path: Path) -> list[dict[str, object]]:
    """Rows from the inventory file, or an empty list when it holds none."""
    raw = yaml.safe_load(inventory_path.read_text(encoding="utf-8")) or {}
    rows = raw.get("boundaries") or []
    return [row for row in rows if isinstance(row, dict)]


def _blank(value: object) -> bool:
    return value is None or not str(value).strip()


def _row_violations(row: dict[str, object]) -> list[Violation]:
    """Is this row complete enough to be worth having?"""
    surface, scope, construct, ordinal = _row_key(row)
    verdict = str(row.get("verdict", "")).strip()

    def violation(detail: str) -> Violation:
        return Violation(surface, scope, construct, ordinal, detail)

    if verdict not in _VERDICTS:
        return [violation(f"verdict must be one of {sorted(_VERDICTS)}, not {verdict!r}")]

    if verdict == _VERDICT_NOT_FAIL_OPEN:
        if _blank(row.get("reason")):
            return [
                violation(
                    "a not-fail-open row needs a reason; an unexplained dismissal "
                    "is indistinguishable from an unexamined one"
                )
            ]
        return []

    missing = [field for field in _FAIL_OPEN_TEXT_FIELDS if _blank(row.get(field))]
    if "caller_controlled" not in row or not isinstance(row.get("caller_controlled"), bool):
        missing.append("caller_controlled")
    if missing:
        return [violation(f"a fail-open row needs {', '.join(sorted(missing))}")]
    return []


def scan(repo_root: Path, inventory_path: Path) -> list[Violation]:
    """Every violation: undeclared boundaries, rotted rows, and incomplete rows."""
    boundaries, violations = collect_boundaries(repo_root)
    rows = load_inventory(inventory_path)
    declared = {_row_key(row): row for row in rows}
    found = {boundary.key for boundary in boundaries}

    for boundary in boundaries:
        if boundary.key not in declared:
            violations.append(
                Violation(
                    surface=boundary.surface,
                    scope=boundary.scope,
                    construct=boundary.construct,
                    ordinal=boundary.ordinal,
                    detail="fail-open boundary in the enforcement path with no inventory row",
                )
            )

    for key, row in declared.items():
        if key not in found:
            surface, scope, construct, ordinal = key
            violations.append(
                Violation(
                    surface=surface,
                    scope=scope,
                    construct=construct,
                    ordinal=ordinal,
                    detail=(
                        "inventory row names a boundary that no longer exists -- a row that "
                        "has rotted reads as a row that passes"
                    ),
                )
            )
            continue
        violations.extend(_row_violations(row))

    return violations


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    json_mode = "--json" in args
    inventory_path = _DEFAULT_INVENTORY
    for index, arg in enumerate(args):
        if arg == "--inventory" and index + 1 < len(args):
            inventory_path = Path(args[index + 1]).resolve()

    violations = scan(_REPO_ROOT, inventory_path)
    scanned = count_boundaries(_REPO_ROOT)
    declared = len(load_inventory(inventory_path))

    output = {
        "tool": "fail_open_inventory",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "boundaries_scanned": scanned,
            "rows_declared": declared,
        },
        "violations": [violation.to_dict() for violation in violations],
    }

    if json_mode:
        # Graded against a DIFFERENT inventory, the verdict is not the one the
        # repository artefact claims to hold — "clean against our declarations"
        # and "clean against someone else's" are different facts, and llm_qa
        # publishes that artefact as this check's evidence. A run given another
        # inventory reports beside THAT file (Plan 00432).
        output_file = (
            inventory_path.parent / _ARTEFACT_NAME
            if inventory_path != _DEFAULT_INVENTORY
            else _OUTPUT_FILE
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))

    if violations:
        print(
            f"Found {len(violations)} fail-open inventory problem(s) "
            f"across {scanned} boundaries in scope:"
        )
        for violation in violations:
            print(
                f"  {violation.surface}::{violation.scope}::"
                f"{violation.construct}#{violation.ordinal}"
            )
            print(f"      {violation.detail}")
        print(f"\n{_REMEDIATION}")
    else:
        print(
            f"Every fail-open boundary in the enforcement path is declared "
            f"({scanned} scanned, {declared} rows)"
        )

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
