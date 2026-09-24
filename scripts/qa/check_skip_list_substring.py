#!/usr/bin/env python3
"""Fail when a skip/exclude list entry is tested against a path with bare `in`.

``in`` on two strings is SUBSTRING containment, not path-segment containment.
``"venv/" in file_path`` is also true for
``".../worktree-issue-53-venv/untracked/scratch/x.py"`` -- the guard silently
stands down for any path that merely ENDS in the skipped name, with no
decision and no advisory a client would ever see (00422 N20).

``strategies/lint/common.py``'s ``matches_skip_path`` fixed this once, by
walking the string and requiring each match to land on a `/`-preceded (or
string-start) boundary. Six other sites tested a skip/exclude list against a
path the same unbounded way and were never moved onto it -- this is the
Defence that keeps a seventh from reintroducing the class (Plan 00458,
CLAUDE/Security/AsymmetricSiblingProtection.md).

**The shape this rule looks for**: a comprehension's (or an explicit
``for``'s) own loop variable -- or a name simply DERIVED from it, see below
-- compared with ``in`` against something that looks like a path variable --
``any(entry in file_path for entry in SOME_LIST)`` or the equivalent
``for entry in SOME_LIST: ... entry in file_path``. That is precisely the
shape that makes the test a bare substring check between a LIST ITEM and a
PATH.

**Follows simple derivation, not just the raw loop variable.** The original
version of this rule required the loop variable to appear UNCHANGED, which
meant ``strategies/tdd/common.py``'s ``matches_directory`` -- ``pattern =
f"/{directory}/"`` then ``if pattern in file_path`` -- went unseen. That
DERIVED name is the same hazard wearing a different name: ``pattern`` is
still an unbounded substring test between a list entry and a path, just one
assignment away from the loop variable. So a name bound (via plain
assignment, an augmented `+=`, or a ternary) to an f-string wrapping the
loop variable, a `+` concatenation involving it, or a `.rstrip()`/`.lstrip()`/
`.strip()` call on it, is tracked as DERIVED and still triggers the rule
when compared with ``in`` against a path-like name -- however many
statements later. Only these specific, common normalisation idioms are
followed; anything else (a function call that isn't `.rstrip`/`.lstrip`/
`.strip`, a dict/list lookup, string formatting via `%` or `.format()`) is
NOT tracked, deliberately -- a rule that guesses at arbitrary data flow is a
rule that cries wolf.

The right-hand side must also look like a path (its last dotted/attribute
component matches ``PATH_NAME_PATTERN``) -- an unrelated
``any(keyword in content for keyword in KEYWORDS)`` is a different idiom
entirely and is not this class. A single FIXED literal against a path
(``"/vendor/" in file_path``, no list) is a narrower, different shape and is
out of scope for this rule -- Plan 00458's Task 1.1 audit records those sites
separately.

Fix: use the shared matcher instead of the bare `in` test:

    from claude_code_hooks_daemon.utils.path_segments import matches_path_segment
    from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root

    if matches_path_segment(file_path, strategy.skip_directories,
                             project_root=resolve_project_root()):

Usage:
    python scripts/qa/check_skip_list_substring.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation, or no Python file was examined
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.scan_scope import vacuous_scan_failure

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "skip_list_substring.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

_RULE: Final[str] = "unbounded-skip-list-membership"

#: The comparator (right-hand side of the `in`) must look like a path
#: variable: `file_path`, `path`, `abs_path`, `rel_path`, `filepath`, or any
#: identifier ending `_path`/`path`. This is what keeps an unrelated
#: substring test (`keyword in content`, `name in allowed_names`) quiet.
_PATH_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)(^|_)(file_)?path$|(^|_)filepath$")

_REMEDIATION: Final[str] = (
    "Each site above compares a skip/exclude-list entry against a path with a\n"
    'bare `in` test, which is SUBSTRING containment: `"venv/" in file_path` is\n'
    "also true for `.../worktree-issue-53-venv/...`, so the guard silently\n"
    "stands down for any path that merely ENDS in the skipped name.\n"
    "\n"
    "Fix: route through the shared, segment-bounded, project-relative matcher:\n"
    "\n"
    "    from claude_code_hooks_daemon.utils.path_segments import (\n"
    "        matches_path_segment,\n"
    "    )\n"
    "    from claude_code_hooks_daemon.utils.path_exclusion import (\n"
    "        resolve_project_root,\n"
    "    )\n"
    "    if matches_path_segment(file_path, patterns, "
    "project_root=resolve_project_root()):\n"
    "\n"
    "See CLAUDE/Plan/00458-skip-lists-match-path-segments-relative-to-the-project/."
)


@dataclass(frozen=True)
class Violation:
    """One bare substring membership test between a list entry and a path."""

    file: str
    line: int
    rule: str = _RULE

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": (
                "list entry compared against a path with bare `in` -- not "
                "segment-bounded, so a path merely ENDING in the entry name "
                "(`myvenv/` for `venv/`) silently matches; use "
                "utils.path_segments.matches_path_segment"
            ),
        }


def _identifier_of(node: ast.expr) -> str | None:
    """The trailing identifier of a `Name` or `Attribute` node, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _looks_like_path(node: ast.expr) -> bool:
    identifier = _identifier_of(node)
    return identifier is not None and bool(_PATH_NAME_PATTERN.search(identifier))


#: Method calls on a string that preserve "derived from the loop variable"
#: status: they only trim characters, never introduce new ones that could
#: turn an unrelated string into something that happens to look derived.
_TRACKED_STRIP_METHODS: Final[frozenset[str]] = frozenset({"rstrip", "lstrip", "strip"})


def _is_derived(expr: ast.expr, derived: frozenset[str]) -> bool:
    """Whether ``expr`` is the loop variable, or built from it by a simple,
    commonly-used normalisation: an f-string, ``+`` concatenation, a
    ``.rstrip``/``.lstrip``/``.strip`` call, or either arm of a ternary.

    ``derived`` is the set of names already known to carry the loop
    variable's value (starts as just the loop variable itself; grows as
    ``_track_derivations`` walks assignments in order). Recursive so a
    multi-step derivation (concatenate, then strip) is still followed.
    """
    if isinstance(expr, ast.Name):
        return expr.id in derived
    if isinstance(expr, ast.JoinedStr):
        return any(
            isinstance(value, ast.FormattedValue) and _is_derived(value.value, derived)
            for value in expr.values
        )
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _is_derived(expr.left, derived) or _is_derived(expr.right, derived)
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr in _TRACKED_STRIP_METHODS
    ):
        return _is_derived(expr.func.value, derived)
    if isinstance(expr, ast.IfExp):
        return _is_derived(expr.body, derived) or _is_derived(expr.orelse, derived)
    return False


def _is_bare_membership_of(compare: ast.Compare, derived: frozenset[str]) -> bool:
    """Whether ``compare`` is ``<derived-from-loop-var> in <path-like>``
    (either order). Requires exactly one ``in`` comparison.
    """
    if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.In):
        return False
    left, right = compare.left, compare.comparators[0]
    if _is_derived(left, derived):
        return _looks_like_path(right)
    if _is_derived(right, derived):
        return _looks_like_path(left)
    return False


def _comprehension_violations(node: ast.expr) -> list[ast.Compare]:
    """``Compare`` nodes inside a comprehension that test its own loop var
    (or something derived from it inline, e.g. ``f"/{x}/" in file_path``)."""
    if not isinstance(node, ast.GeneratorExp | ast.ListComp | ast.SetComp):
        return []
    found: list[ast.Compare] = []
    for generator in node.generators:
        if not isinstance(generator.target, ast.Name):
            continue
        derived = frozenset({generator.target.id})
        elt = node.elt
        if isinstance(elt, ast.Compare) and _is_bare_membership_of(elt, derived):
            found.append(elt)
    return found


def _assignment_target_name(stmt: ast.stmt) -> str | None:
    """The single ``Name`` a simple ``Assign``/``AugAssign``/``AnnAssign``
    binds, or ``None`` for any other shape (tuple unpacking, attribute
    targets, ...) -- those are not tracked, deliberately (see module
    docstring: only the common idioms)."""
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target = stmt.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None


def _walk_and_track(
    stmts: list[ast.stmt], derived: frozenset[str], found: list[ast.Compare]
) -> frozenset[str]:
    """Walk ``stmts`` in order, growing ``derived`` on each assignment that
    binds a derived value, and collecting every ``Compare`` violation seen
    along the way (including inside a nested ``if``, since that is where the
    real-world shape puts the boundary-adding statement:
    ``if not pattern.endswith("/"): pattern += "/"``).

    Deliberately shallow beyond ``if``: does not descend into a nested
    ``for``/``while``/function body, which keeps this from crossing into an
    unrelated inner scope's own variables.
    """
    for stmt in stmts:
        name = _assignment_target_name(stmt)
        value = getattr(stmt, "value", None)
        if name is not None:
            already_derived = name in derived
            if already_derived or (value is not None and _is_derived(value, derived)):
                derived = derived | {name}
            continue
        if isinstance(stmt, ast.If):
            if isinstance(stmt.test, ast.Compare) and _is_bare_membership_of(stmt.test, derived):
                found.append(stmt.test)
            derived = _walk_and_track(stmt.body, derived, found)
            derived = _walk_and_track(stmt.orelse, derived, found)
            continue
        if isinstance(stmt, ast.Return | ast.Expr) and stmt.value is not None:
            if isinstance(stmt.value, ast.Compare) and _is_bare_membership_of(stmt.value, derived):
                found.append(stmt.value)
    return derived


def _for_loop_violations(node: ast.For) -> list[ast.Compare]:
    """``Compare`` nodes in a ``for`` body that test the loop's own variable,
    or a name simply derived from it (see ``_is_derived``)."""
    if not isinstance(node.target, ast.Name):
        return []
    found: list[ast.Compare] = []
    _walk_and_track(node.body, frozenset({node.target.id}), found)
    return found


def scan_file(path: Path) -> list[Violation]:
    """Every unbounded skip-list membership test in one module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        # A module that does not parse is a different defect entirely, and one
        # the lint gate reports with a better message than this rule could.
        return []

    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    violations: list[Violation] = []
    seen: set[int] = set()
    for node in ast.walk(tree):
        compares: list[ast.Compare] = []
        if isinstance(node, ast.GeneratorExp | ast.ListComp | ast.SetComp):
            compares = _comprehension_violations(node)
        elif isinstance(node, ast.For):
            compares = _for_loop_violations(node)
        for compare in compares:
            if compare.lineno in seen:
                continue
            seen.add(compare.lineno)
            violations.append(Violation(file=reported, line=compare.lineno))
    return sorted(violations, key=lambda v: (v.file, v.line))


def scan_tree(scan_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        violations.extend(scan_file(path))
    return violations


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    json_mode = "--json" in args
    scan_root = _DEFAULT_SCAN_ROOT
    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            scan_root = Path(args[index + 1]).resolve()

    violations = scan_tree(scan_root) if scan_root.is_dir() else []
    files_scanned = sum(1 for _ in scan_root.rglob("*.py")) if scan_root.is_dir() else 0
    vacuous = vacuous_scan_failure(examined=files_scanned, noun="Python files", root=scan_root)

    output = {
        "tool": "skip_list_substring",
        "summary": {
            "passed": len(violations) == 0 and vacuous is None,
            "vacuous_scan": vacuous,
            "total_violations": len(violations),
            "files_scanned": files_scanned,
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        # A --path scan answers "is this DIRECTORY clean", which is not the
        # question the repository artefact answers. llm_qa publishes that
        # artefact as this check's evidence surface, so a scoped run reports
        # beside what it scanned rather than overwriting it.
        output_file = (
            scan_root / _ARTEFACT_NAME if scan_root != _DEFAULT_SCAN_ROOT else _OUTPUT_FILE
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))

    if vacuous is not None:
        print(f"FAILED: {vacuous}")
    elif violations:
        print(f"Found {len(violations)} unbounded skip-list membership test(s):")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No unbounded skip-list membership tests found ({files_scanned} files scanned)")

    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
