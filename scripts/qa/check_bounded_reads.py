#!/usr/bin/env python3
"""Fail when code declares a read bound but reads the file unboundedly (Plan 00231).

The defect class, stated precisely: an expression that DECLARES a bound —
``maxlen=N``, a slice — applied to a read that ignores it and materialises the
whole file.

    with open(transcript) as f:
        tail = deque(f, maxlen=20)      # wants 20 lines, reads every line

Measured on a live 74 MB session transcript: 162 ms for the ``deque`` spelling
versus 17 ms for the equivalent bounded seek. The gap is not constant — it
grows linearly and forever, because the files the daemon reads (session
transcripts, the verdict log, ``stop-events.jsonl``, notification and
background-process logs) are all append-only with no upper bound.

Why the DECLARED BOUND is the signal
------------------------------------
A whole-file read is not, on its own, a defect: loading a config or a plan
document is exactly right. What makes this shape mechanically checkable is
that the author has already written down the intent — ``maxlen=20`` says
twenty lines are wanted — immediately next to a read that fetches everything.
The contradiction is local, explicit, and needs no guess about file size. That
is what keeps this rule inside the "NO MAGIC"-style enforcement boundary in
CLAUDE.md: a shape where a wrong value is mechanically checkable AND a named
better alternative already exists to point at.

Why a checker rather than a fix
--------------------------------
Plan 00177 fixed this in ``TranscriptReader.load_tail`` by seeking to
``max(0, size - max_bytes)``. It did not fix the sibling
``has_recent_stop_hook_block`` in ``utils/stop_hook_helpers.py``, which kept
the ``deque`` spelling and went unnoticed for eight months. Fixing instances by
hand leaves the next one to be found by accident; per CLAUDE.md Standard 15
(DEFENCE BEFORE FIX) the bug worth fixing is the missing guard.

The remedy in every case is to read only the window you asked for: seek to
``max(0, size - max_bytes)`` and parse forward (see
``TranscriptReader._parse_tail``), or use ``itertools.islice`` for a head,
which stops reading at N instead of materialising first.

Known blind spot, deliberately left open
----------------------------------------
The bound must be applied DIRECTLY to the read expression. When it reaches the
read through a variable the rule does not fire::

    existing = [ln for ln in path.read_text().splitlines() if ln.strip()]
    existing.append(json.dumps(record))
    path.write_text("\\n".join(existing[-max_lines:]) + "\\n")

That is real code (``handlers/post_tool_use/background_process_tracker.py``)
and it is NOT a defect: the final line rewrites the file truncated to
``max_lines``, so the log self-rotates and the read is bounded by construction.

Widening the rule to follow variables would therefore make its very first extra
finding a false positive, because deciding the case needs a fact no AST can
see — whether the file being read is capped elsewhere. Precision is worth more
than recall for a gate that blocks commits, the same conclusion Plan 00208
reached when it demoted four ``comment_changelog`` signals to advisory after
they fired on legitimate code. If a variable-indirection defect is ever found
in practice, prefer a targeted rule keyed on the specific unbounded file over
a general dataflow chase.

Usage:
    python scripts/qa/check_bounded_reads.py [--json] [--path DIR]

Exit codes:
    0 — no violations
    1 — at least one violation
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
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "bounded_reads.json"

#: Trees whose Python runs against files with no upper bound. ``src`` is the
#: daemon runtime (transcripts, JSONL logs); ``.claude/project-handlers`` runs
#: inside that same daemon dispatch; ``scripts`` walks the repo tree. Tests are
#: deliberately excluded — their fixtures are a handful of lines, so the rule
#: would report cost that cannot exist and train readers to ignore it.
_DEFAULT_SCAN_ROOTS: Final[tuple[Path, ...]] = (
    _REPO_ROOT / "src",
    _REPO_ROOT / "scripts",
    _REPO_ROOT / ".claude" / "project-handlers",
)

#: Paths exempt from the rule, relative to the repo root.
#:
#: This checker IS the rule: its docstrings must spell out every banned shape
#: in order to define them, mirroring how ``check_python_var_guidance.py``
#: exempts itself and ``check_canonical_callers.sh`` exempts the resolver.
_EXEMPT_SUBPATHS: Final[tuple[str, ...]] = (
    "scripts/qa/check_bounded_reads.py",
    ".claude/hooks-daemon/",
    ".claude/worktrees/",
)

#: Inline escape hatch, following the project's existing marker convention.
#: Honoured on the violating line or on a comment directly above it.
_EXEMPT_MARKER: Final[str] = "bounded-read-exempt:"

_RULE_NAME: Final[str] = "bounded-intent-unbounded-read"

_REMEDIATION: Final[str] = (
    "Read only the window you asked for: seek to max(0, size - max_bytes) and "
    "parse forward (see TranscriptReader._parse_tail), or use itertools.islice "
    "for a head, which stops at N instead of materialising the file first."
)

#: Callables that materialise an ENTIRE file regardless of what is done next.
_WHOLE_FILE_READERS: Final[frozenset[str]] = frozenset({"read", "read_text", "readlines"})

#: Callables that split an already-materialised read into lines.
_SPLITTERS: Final[frozenset[str]] = frozenset({"splitlines", "split"})

#: Constructors that drain an iterable into memory.
_DRAINING_CONSTRUCTORS: Final[frozenset[str]] = frozenset({"list", "tuple"})

#: Functions that open a file and yield a lazily-iterable handle.
_OPENERS: Final[frozenset[str]] = frozenset({"open"})


@dataclass(frozen=True)
class Violation:
    """A single bounded-intent/unbounded-read occurrence."""

    file: str
    line: int
    rule: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
        }


def _is_exempt_path(path: Path) -> bool:
    # Tested explicitly rather than caught: a path outside the repo root is a
    # normal case (``--path`` accepts any directory), not an exceptional one,
    # and an except-and-continue here would be indistinguishable from hiding a
    # real resolution failure.
    relative = (
        path.relative_to(_REPO_ROOT).as_posix()
        if path.is_relative_to(_REPO_ROOT)
        else path.as_posix()
    )
    return any(relative.startswith(prefix) for prefix in _EXEMPT_SUBPATHS)


def _is_opener_call(node: ast.expr) -> bool:
    """Return True if ``node`` is ``open(...)`` or ``<expr>.open(...)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _OPENERS
    if isinstance(func, ast.Attribute):
        return func.attr in _OPENERS
    return False


def _collect_file_handles(tree: ast.AST) -> set[str]:
    """Return every name bound to an open file handle in ``tree``.

    Collected module-wide rather than per-scope. That slightly over-approximates
    — a name used as a handle in one function marks the name everywhere — which
    is the safe direction for a guard: it can only ever widen detection, and the
    shapes that consume a handle (``deque(f, maxlen=)``, ``list(f)[a:b]``) are
    already narrow enough that a collision needs the same name to be both a
    handle and a sliced sequence in one module. The inline marker covers that.
    """
    handles: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.withitem):
            if _is_opener_call(node.context_expr) and isinstance(node.optional_vars, ast.Name):
                handles.add(node.optional_vars.id)
        elif isinstance(node, ast.Assign) and _is_opener_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    handles.add(target.id)
    return handles


def _has_maxlen_keyword(node: ast.Call) -> bool:
    return any(keyword.arg == "maxlen" for keyword in node.keywords)


def _is_deque_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "deque"
    if isinstance(func, ast.Attribute):
        return func.attr == "deque"
    return False


def _reads_whole_file(node: ast.expr) -> bool:
    """Return True if ``node`` materialises a whole file.

    Recognises a direct ``.read()``/``.read_text()``/``.readlines()`` call and
    the same call seen through one splitting layer
    (``path.read_text().splitlines()``).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _WHOLE_FILE_READERS:
        return True
    if func.attr in _SPLITTERS:
        return _reads_whole_file(func.value)
    return False


def _drains_handle(node: ast.expr, handles: set[str]) -> bool:
    """Return True if ``node`` is ``list(f)``/``tuple(f)`` over a file handle."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Name) or func.id not in _DRAINING_CONSTRUCTORS:
        return False
    return any(isinstance(arg, ast.Name) and arg.id in handles for arg in node.args)


def _exempt_lines(source_lines: list[str], line: int) -> bool:
    """Return True if an inline marker covers the violation at ``line``.

    Honoured on the violating line itself or on the contiguous run of comment
    lines directly above it, which is where a reader naturally writes the
    justification.
    """
    index = line - 1
    if index < len(source_lines) and _EXEMPT_MARKER in source_lines[index]:
        return True
    cursor = index - 1
    while cursor >= 0:
        stripped = source_lines[cursor].strip()
        if not stripped.startswith("#"):
            break
        if _EXEMPT_MARKER in stripped:
            return True
        cursor -= 1
    return False


def scan_file(path: Path) -> list[Violation]:
    """Return every bounded-intent/unbounded-read occurrence in ``path``."""
    if _is_exempt_path(path):
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Not this checker's job to report; ruff/py_compile own syntax.
        return []

    handles = _collect_file_handles(tree)
    source_lines = source.splitlines()
    violations: list[Violation] = []

    for node in ast.walk(tree):
        detail: str | None = None
        line: int = 0

        if isinstance(node, ast.Call) and _is_deque_call(node) and _has_maxlen_keyword(node):
            if any(isinstance(arg, ast.Name) and arg.id in handles for arg in node.args):
                detail = (
                    "deque(<file handle>, maxlen=N) declares a bound of N lines but "
                    "iterates the entire file to obtain them."
                )
                line = node.lineno
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            line = node.lineno
            if _reads_whole_file(node.value):
                detail = (
                    "A slice is applied to a whole-file read, so the file is "
                    "materialised in full and then discarded down to the window."
                )
            elif _drains_handle(node.value, handles):
                detail = (
                    "A slice is applied to a drained file handle, so every line is "
                    "read into memory and then discarded down to the window."
                )

        if detail is None:
            continue
        if _exempt_lines(source_lines, line):
            continue
        violations.append(
            Violation(
                file=str(path),
                line=line,
                rule=_RULE_NAME,
                message=f"{detail} {_REMEDIATION}",
            )
        )

    return violations


def scan_tree(root: Path) -> list[Violation]:
    """Recursively scan ``root`` for banned occurrences."""
    violations: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        if path.is_file():
            violations.extend(scan_file(path))
    return violations


def main() -> int:
    json_mode = "--json" in sys.argv
    scan_roots = _DEFAULT_SCAN_ROOTS
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == "--path" and index + 1 < len(args):
            scan_roots = (Path(args[index + 1]).resolve(),)

    violations: list[Violation] = []
    for root in scan_roots:
        if root.is_dir():
            violations.extend(scan_tree(root))

    output = {
        "tool": "bounded_reads",
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
        print(f"Found {len(violations)} bounded-intent/unbounded-read violations:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}")
        print(f"\n{_REMEDIATION}")
    else:
        print("No bounded-intent/unbounded-read violations found")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
