#!/usr/bin/env python3
"""Fail when a handler judges a caller-supplied path with a raw stat predicate.

``pathlib`` treats a small set of stat failures as "the answer is no": ENOENT,
ENOTDIR, EBADF and ELOOP are swallowed and the predicate returns ``False``.
**EACCES is not in that set.** So ``Path.exists()``, ``Path.is_file()`` and
``Path.is_dir()`` all raise ``PermissionError`` when any directory in the parent
chain lacks ``+x`` for the daemon's user -- and handlers call those predicates on
paths taken straight from a user's tool input, where the daemon has no say in
whether it can stat them.

``chain.py`` catching the raise is not a fix. Under ``strict_mode: false`` (the
client default) the handler's guard silently stops applying; under
``strict_mode: true`` it becomes a spurious DENY attributed to a crash. Two
different wrong answers, neither a decision the handler made.

Plan 00347 converted the fourteen sites that had the defect. This check exists
because the fifteenth would reintroduce it with nothing to catch it: every
instance was individually reasonable-looking, and the whole class was invisible
until someone counted.

**Scope.** Only some handler families can receive a path the daemon did not
choose. A ``PreToolUse``/``PostToolUse`` handler reads ``tool_input.file_path``;
a worktree handler reads a path from its event payload. A ``SessionStart`` or
``status_line`` handler has no such input -- its paths come from the project
root and config by construction -- so requiring markers there would mean 38
comments asserting something already guaranteed, and noise is how a real marker
stops being read. An UNRECOGNISED family is scanned, not skipped: a gate whose
default is "skip" silently stops covering whatever is added after it was
written, which is the failure mode this plan is about.

Usage:
    python scripts/qa/check_eacces_safe_predicates.py [--json] [--path DIR]

Exit codes:
    0 -- no violations
    1 -- at least one violation
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "eacces_safe.json"

_DEFAULT_SCAN_ROOT: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon"

# Handler families whose EVENT carries a path the caller chose. Everything not
# listed here is scanned too -- this is the set that needs no justification,
# not an allowlist of the ones that do.
_FAMILIES_WITHOUT_CALLER_PATHS: Final[frozenset[str]] = frozenset(
    {
        "session_start",
        "session_end",
        "status_line",
        "stop",
        "subagent_stop",
        "pre_compact",
        "user_prompt_submit",
        "notification",
        "permission_request",
        "utils",
        "nitpick",
    }
)

_PREDICATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\.(exists|is_file|is_dir)\(\)")

_MARKER: Final[str] = "# eacces-safe-exempt:"

_REMEDIATION: Final[str] = (
    "Each site above judges a path with a raw pathlib predicate, which RAISES\n"
    "PermissionError when an ancestor directory is not traversable.\n"
    "\n"
    "Fix: go through the canonical helper, stating what this site means by\n"
    "'I could not look' -- there is no default, because the safe value differs\n"
    "by site (write_clobber_guard needs True, comment_size needs False,\n"
    "plan_qa_edit needs None):\n"
    "\n"
    "    from claude_code_hooks_daemon.utils.path_predicates import path_is_file\n"
    "    if not path_is_file(path, unreadable_means=True):\n"
    "\n"
    "If the path is daemon-controlled (config, install dir, cache) then EACCES\n"
    "is genuinely exceptional and SHOULD surface. Record that in place, with a\n"
    "reason -- an empty marker is a silencer, not a record:\n"
    "\n"
    "    # eacces-safe-exempt: <why this path is not caller-supplied>\n"
    "\n"
    "See CLAUDE/Plan/Completed/00347-handlers-raise-on-unstattable-paths/."
)


@dataclass(frozen=True)
class Violation:
    """One raw predicate on a path this checker cannot vouch for."""

    file: str
    line: int
    predicate: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": "raw-stat-predicate",
            "message": (
                f"`.{self.predicate}()` raises PermissionError on an unreadable "
                "path; use utils.path_predicates or record a reason in place"
            ),
        }


def _family_of(path: Path, scan_root: Path) -> str | None:
    """The handler family a file belongs to, or None if it is not a handler.

    The family is the directory directly under ``handlers/``. A module sitting
    at the top of ``handlers/`` (``registry.py``, ``project_loader.py``) has no
    family and is dispatched for every event, so it is scanned.
    """
    if not path.is_relative_to(scan_root):
        return None
    parts = path.relative_to(scan_root).parts
    if "handlers" not in parts:
        return None
    index = parts.index("handlers")
    remainder = parts[index + 1 :]
    return remainder[0] if len(remainder) > 1 else ""


def _is_exempt(lines: list[str], index: int) -> bool:
    """Whether a marker with a REASON covers the predicate on ``lines[index]``.

    Accepted on the predicate's own line or on any of the lines immediately
    above it, so a marker can sit above a multi-line expression.
    """
    candidates = [lines[index]]
    cursor = index - 1
    while cursor >= 0 and lines[cursor].strip().startswith("#"):
        candidates.append(lines[cursor])
        cursor -= 1

    for candidate in candidates:
        marker_at = candidate.find(_MARKER)
        if marker_at == -1:
            continue
        if candidate[marker_at + len(_MARKER) :].strip():
            return True
    return False


def scan_file(path: Path, scan_root: Path) -> list[Violation]:
    """Every unexempted raw predicate in one handler module."""
    family = _family_of(path, scan_root)
    if family is None or family in _FAMILIES_WITHOUT_CALLER_PATHS:
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    violations: list[Violation] = []
    for index, line in enumerate(lines):
        match = _PREDICATE_PATTERN.search(line)
        if match is None:
            continue
        if _is_exempt(lines, index):
            continue
        reported = (
            str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path)
        )
        violations.append(Violation(file=reported, line=index + 1, predicate=match.group(1)))
    return violations


def scan_tree(scan_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(scan_root.rglob("*.py")):
        violations.extend(scan_file(path, scan_root))
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

    violations = scan_tree(scan_root) if scan_root.is_dir() else []

    output = {
        "tool": "eacces_safe",
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
        print(f"Found {len(violations)} raw stat predicate(s) on unvouched paths:")
        for violation in violations:
            print(f"  {violation.file}:{violation.line}  .{violation.predicate}()")
        print(f"\n{_REMEDIATION}")
    else:
        print("No raw stat predicates on caller-supplied paths found")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
