#!/usr/bin/env python3
"""Fail when an author-written relative path is resolved by stat-ing the join.

``Path.exists()`` stats the path exactly as written. A ``..`` segment is
therefore walked through the FILESYSTEM, so every directory along the way has
to exist for the answer to be about the target at all:

    (Path("CLAUDE/Security") / "../Routine/x.md").exists()   # False...

...False whenever ``CLAUDE/Security/`` does not exist yet -- which is precisely
the state of the FIRST document written into a new directory. The target is
right there on disk and the answer is still no.

That is not a cosmetic wrong answer. `docs_qa`'s ``pointer-resolves`` check
grades a NEW dead link as BLOCK, so the write was denied, and no retry could
succeed: the directory only comes into existence by the write being allowed.
Creating the first document in a new docs directory was impossible if it used
a ``../`` link, and the failure named the wrong thing -- a dead link -- so the
reader would go looking for a typo in a path that was correct.

**This is a chokepoint rule, not a judgement call.** It does not try to decide
which joined value can really carry a ``..`` — that needs data flow, and a rule
that guesses is a rule that argues. It says instead: in the two trees whose job
is resolving paths an author wrote, normalise before you stat, always. Seven
sites, no exceptions to weigh, no exemption marker to reach for.

The scoping is what keeps it honest. Scanning every joined-then-stat-ed path
across ``src/`` finds 17, most of them daemon-chosen paths where ``..`` cannot
arise; a rule with that ratio gets suppressed rather than fixed. An inline
string literal (``root / "README.md"``) is excluded for the same reason — it
cannot carry a ``..`` under any circumstances, so reporting it would be pure
noise. A NAMED constant holding that same filename is not excluded, because
telling the two apart is the data-flow question this rule refuses to guess at,
and normalising costs it nothing.

**Fix**: resolve ``..`` LEXICALLY before touching the filesystem, via the
canonical helper:

    from claude_code_hooks_daemon.utils.authored_paths import authored_path_exists
    if authored_path_exists(base, target):

Lexical is also the more faithful reading. A markdown renderer resolves ``..``
in a link by text, so a lexical answer is the one that matches what a reader
of the rendered document will experience.

Usage:
    python scripts/qa/check_authored_path_stat.py [--json] [--path DIR]

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
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "authored_path_stat.json"

_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

_RULE: Final[str] = "authored-path-stat"

#: Stat predicates that walk ``..`` through the filesystem. All three behave
#: identically here, so all three count.
_PREDICATES: Final[frozenset[str]] = frozenset({"exists", "is_file", "is_dir"})

#: Calls that CONSUME the target — its bytes, or its children. Added when run
#: 2026-001 measured the stat-only rule at 7 sites against 28 it could not see,
#: two of which read a document-authored path with no containment test. Reading
#: is the consume that matters most: a stat answers a question, a read makes the
#: daemon an oracle over whatever the path resolved to.
_CONSUMERS: Final[frozenset[str]] = frozenset(
    {"read_text", "read_bytes", "open", "iterdir", "glob", "rglob"}
)

#: Everything the rule reacts to, once the receiver is established.
_WATCHED: Final[frozenset[str]] = _PREDICATES | _CONSUMERS

#: Trees whose job is resolving paths an AUTHOR wrote in a document: a markdown
#: link target, a path quoted in a plan. Elsewhere in the daemon a joined path
#: is overwhelmingly one the daemon chose itself, where ``..`` cannot appear
#: and the rule would be noise.
_SCOPED_TREES: Final[tuple[str, ...]] = ("docs_qa", "plan_qa")

_REMEDIATION: Final[str] = (
    "Each site above STATS or READS a path it built by joining. A `..` in the\n"
    "joined value is walked through the filesystem, so a stat answers a\n"
    "question about the intermediate directories rather than about the target\n"
    "-- and a document written into a NEW directory has no intermediate\n"
    "directory yet.\n"
    "\n"
    "A READ is worse than a stat. It does not merely answer wrongly: it makes\n"
    "the daemon a content oracle over whatever the path resolved to, including\n"
    "somewhere the author was never meant to reach. `secret_file_guard` judges\n"
    "the path an AGENT names, and this is not one -- nothing an agent typed\n"
    "names the file when the daemon follows a marker inside a document.\n"
    "\n"
    "Fix, for an existence question: normalise lexically first, via the\n"
    "canonical helper:\n"
    "\n"
    "    from claude_code_hooks_daemon.utils.authored_paths import (\n"
    "        authored_path_exists,\n"
    "    )\n"
    "    if authored_path_exists(base, target):\n"
    "\n"
    "Fix, for a read: normalise, then establish CONTAINMENT before opening --\n"
    "normalising makes `src/../../etc/passwd` resolve faithfully to a real\n"
    "file, which is not the same as it being a file you may read.\n"
    "\n"
    "A join whose operand is an inline STRING LITERAL is not reported -- it\n"
    "cannot carry a `..` -- so there is no exemption marker here and none is\n"
    "wanted. A name bound to the join one statement earlier IS reported: that\n"
    "spelling hid 28 sites from the first version of this rule, two of them a\n"
    "live instance of the hazard."
)


@dataclass(frozen=True)
class Violation:
    """One stat predicate applied to a path that may carry ``..``."""

    file: str
    line: int
    predicate: str
    rule: str = _RULE

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": (
                f"`.{self.predicate}()` on a joined path walks any `..` through the "
                "filesystem, so a missing intermediate directory reads as a missing "
                "target; use utils.authored_paths.authored_path_exists"
            ),
        }


def _is_literal_operand(node: ast.expr) -> bool:
    """Whether the right-hand side of the join is a literal string.

    A literal can never introduce a ``..``, so the hazard does not exist and
    reporting it would be the false positive that gets this rule switched off.
    """
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_in_scope(path: Path, scan_root: Path) -> bool:
    """Whether ``path`` sits in a tree that resolves document-authored paths."""
    if not path.is_relative_to(scan_root):
        return False
    return any(part in _SCOPED_TREES for part in path.relative_to(scan_root).parts)


def _is_unsafe_join(node: ast.expr) -> bool:
    """Whether ``node`` is a ``/`` join whose right operand may carry ``..``."""
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and not _is_literal_operand(node.right)
    )


def _walk_scope(scope: ast.AST) -> list[ast.AST]:
    """Every node in ``scope``, NOT descending into a nested function.

    Without the boundary, walking the module reaches inside every function, so
    a name bound in one leaks into its siblings — which is the module-scope
    over-reporting this rule exists to avoid. Each function is visited as its
    own scope instead.

    A nested function therefore does not inherit its enclosing binding, so a
    closure over a joined local is missed. That is an under-report, and it is
    the safe direction: a rule that cries wolf gets suppressed, and a rule that
    is suppressed protects nothing.
    """
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def _joined_locals(scope: ast.AST) -> set[str]:
    """Names bound to an unsafe join in ONE scope's own body.

    Scoped deliberately. A module-wide pass over the same question reported 31
    sites where a properly scoped one reports 28: the difference is a name
    reused in an unrelated function, and a rule that over-reports on name reuse
    is one people stop believing.
    """
    bound: set[str] = set()
    for node in _walk_scope(scope):
        if isinstance(node, ast.Assign) and _is_unsafe_join(node.value):
            bound.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_unsafe_join(node.value)
            and isinstance(node.target, ast.Name)
        ):
            bound.add(node.target.id)
    return bound


def scan_file(path: Path, scan_root: Path) -> list[Violation]:
    """Every joined-then-consumed authored path in one module.

    Two shapes, because run 2026-001 measured the second as the majority:
    the join AT the call site, and a local bound to the join one statement
    earlier. The hazard is identical; only the spelling differs.
    """
    if not _is_in_scope(path, scan_root):
        return []

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        # A module that does not parse is a different defect entirely, and one
        # the lint gate reports with a better message than this rule could.
        return []

    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    scopes: list[ast.AST] = [tree]
    scopes += [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]

    seen: set[tuple[int, str]] = set()
    violations: list[Violation] = []
    for scope in scopes:
        bound = _joined_locals(scope)
        for node in _walk_scope(scope):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _WATCHED:
                continue
            receiver = node.func.value
            direct = _is_unsafe_join(receiver)
            indirect = isinstance(receiver, ast.Name) and receiver.id in bound
            if not (direct or indirect):
                continue
            key = (node.lineno, node.func.attr)
            if key in seen:
                continue
            seen.add(key)
            violations.append(Violation(file=reported, line=node.lineno, predicate=node.func.attr))
    return sorted(violations, key=lambda v: (v.file, v.line))


def scan_tree(scan_root: Path) -> list[Violation]:
    """Every violation under ``scan_root``."""
    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        violations.extend(scan_file(path, scan_root))
    return violations


def count_py_files(scan_root: Path) -> int:
    """Every Python file considered, in scope or not — the scan's denominator.

    Counted independently of :func:`scan_tree` so a rule that went inert
    (``_is_in_scope`` wrongly rejecting everything, say) still reports how much
    it looked at rather than reading identically to a clean pass.
    """
    return sum(1 for _ in scan_root.rglob("*.py"))


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
    files_scanned = count_py_files(scan_root) if scan_root.is_dir() else 0

    output = {
        "tool": "authored_path_stat",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "files_scanned": files_scanned,
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} authored path(s) resolved by stat-ing a join:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  .{violation.predicate}()")
        print(f"\n{_REMEDIATION}")
    else:
        print(f"No authored paths resolved by stat-ing a join ({files_scanned} files scanned)")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
