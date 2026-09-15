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

#: Trees whose job is resolving paths an AUTHOR wrote in a document: a markdown
#: link target, a path quoted in a plan. Elsewhere in the daemon a joined path
#: is overwhelmingly one the daemon chose itself, where ``..`` cannot appear
#: and the rule would be noise.
_SCOPED_TREES: Final[tuple[str, ...]] = ("docs_qa", "plan_qa")

_REMEDIATION: Final[str] = (
    "Each site above answers 'does this target exist?' by stat-ing a path it\n"
    "built by joining. A `..` in the joined value is then walked through the\n"
    "filesystem, so the answer depends on the intermediate directories\n"
    "existing rather than on the target existing -- and a document being\n"
    "written into a NEW directory has no intermediate directory yet.\n"
    "\n"
    "Fix: normalise lexically first, via the canonical helper:\n"
    "\n"
    "    from claude_code_hooks_daemon.utils.authored_paths import (\n"
    "        authored_path_exists,\n"
    "    )\n"
    "    if authored_path_exists(base, target):\n"
    "\n"
    "A join whose operand is a LITERAL filename is not reported -- it cannot\n"
    "carry a `..` -- so there is no exemption marker here and none is wanted."
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


def scan_file(path: Path, scan_root: Path) -> list[Violation]:
    """Every joined-then-stat-ed authored path in one module."""
    if not _is_in_scope(path, scan_root):
        return []

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        # A module that does not parse is a different defect entirely, and one
        # the lint gate reports with a better message than this rule could.
        return []

    reported = str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _PREDICATES:
            continue
        receiver = node.func.value
        if not (isinstance(receiver, ast.BinOp) and isinstance(receiver.op, ast.Div)):
            continue
        if _is_literal_operand(receiver.right):
            continue
        violations.append(Violation(file=reported, line=node.lineno, predicate=node.func.attr))
    return sorted(violations, key=lambda v: (v.file, v.line))


def scan_tree(scan_root: Path) -> list[Violation]:
    """Every violation under ``scan_root``."""
    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        violations.extend(scan_file(path, scan_root))
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

    output = {
        "tool": "authored_path_stat",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
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
        print("No authored paths resolved by stat-ing a join")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
