#!/usr/bin/env python3
"""Check that no doc tells an agent to `cd` into `.claude/hooks-daemon/`.

review2 (Plan 00376) M4/D8: the daemon's own `daemon_location_guard` handler
(`R-DAEMON-DIR-CD`) denies that command unconditionally, because daemon CLI
commands must run from the project root. A doc that instructs it anyway is
not a style nit -- it is a defect an agent following the doc will hit
immediately, every time. `CLAUDE/UPGRADES/upgrade-template/README.md` is
copied verbatim into every future release's own guide, so one uncaught
occurrence there is copied forward release after release; `CLAUDE/LLM-UPDATE.md`
and every already-released `CLAUDE/UPGRADES/**` guide are read directly by an
agent walking a client project through an upgrade.

This checker reuses `daemon_location_guard`'s own compiled pattern rather than
a second copy of it: if the handler's rule ever changes what it denies, this
checker's notion of a violation moves with it, in one place.

Two markers exempt a match when they appear within `_CONTEXT_WINDOW` lines
above it -- meant to sit in the prose introducing the snippet, not inline in
the shell code itself: `OWNER-ONLY` for a rare, genuine step the project
owner runs in their own terminal (never an agent), and `BLOCKED-EXAMPLE` for
a snippet that illustrates the exact shape `daemon_location_guard` denies, as
documentation OF the guard rather than an instruction to run it.

Usage:
    python scripts/qa/check_daemon_dir_cd_in_docs.py [--json] [--path DIR]

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SRC_DIR_NAME: Final[str] = "src"
_QA_OUTPUT_DIR: Final[Path] = _PROJECT_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "daemon_dir_cd_in_docs.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

#: Directories never worth scanning: gitignored runtime state, or a doc tree
#: that RECORDS the past (a plan's history, a field report, a frozen
#: per-release announcement) rather than instructing an agent what to do
#: now. `CLAUDE/Plan/` is a process/audit trail; `RELEASES/` is one frozen
#: announcement per past version, each describing how THAT release was
#: installed at the time -- not an operational run-book a future upgrade
#: reads (`CLAUDE/UPGRADES/` and `LLM-UPDATE.md` are). A sweep of the ~100
#: files under `RELEASES/` for the same boilerplate two code blocks is real
#: follow-up work, tracked separately rather than folded into this scope.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "ccy",
        "node_modules",
        "untracked",
        "venv",
        ".venv",
        "worktrees",
        "Plan",
        "RELEASES",
    }
)

#: A historical record, not an operational doc: it quotes past command text
#: (including the very shape this checker looks for) as prose describing what
#: a guard now catches, never as an instruction to run it.
_SKIP_FILES: Final[frozenset[str]] = frozenset({"CHANGELOG.md"})

#: How far above a match an exemption marker may sit and still apply -- enough
#: for a heading and a short explanatory paragraph, not the whole file.
_CONTEXT_WINDOW: Final[int] = 8
#: The step is real and correct, but only the project OWNER may run it (an
#: agent is denied some other way already, e.g. a manual git checkout of the
#: daemon clone).
_OWNER_ONLY_MARKER: Final[str] = "OWNER-ONLY"
#: The snippet illustrates the exact shape `daemon_location_guard` denies, as
#: documentation OF the guard -- not an instruction to run it.
_BLOCKED_EXAMPLE_MARKER: Final[str] = "BLOCKED-EXAMPLE"
_EXEMPTION_MARKERS: Final[tuple[str, ...]] = (_OWNER_ONLY_MARKER, _BLOCKED_EXAMPLE_MARKER)

_MAX_BYTES: Final[int] = 2_000_000


def _daemon_dir_cd_pattern() -> re.Pattern[str]:
    """The handler's own compiled pattern, loaded from ``src/`` by import.

    Function-local, like every other cross-tree import under ``scripts/qa/``
    (see ``check_handler_reference.load_ground_truth``): ``sys.path`` has to
    be primed with ``src/`` first, and doing that at module scope would put
    an import below a statement.
    """
    entry = str(_PROJECT_ROOT / _SRC_DIR_NAME)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
        _CD_INTO_DAEMON_DIR,
    )

    return _CD_INTO_DAEMON_DIR


def _walk(root: Path) -> tuple[list[Path], int]:
    """Every markdown file worth reading, and how many markdown files the walk saw.

    ``scan_scope.walk_files`` leaves out ``.git`` and nested checkouts, which
    are not this project's docs. Skip-dir membership is checked against the
    path RELATIVE to ``root`` (00466 N26): this repository is routinely
    checked out under ``untracked/worktrees/<name>/``, so filtering on
    absolute parts would match every file on that ancestor alone and scan
    nothing.
    """
    markdown = sorted(path for path in walk_files(root) if path.suffix == ".md")
    found: list[Path] = []
    for path in markdown:
        if any(part in _SKIP_DIRS for part in relative_parts(path, root)):
            continue
        if path.name in _SKIP_FILES:
            continue
        if not path.is_file() or path.is_symlink():
            continue
        found.append(path)
    return found, len(markdown)


def _candidate_files(root: Path) -> list[Path]:
    """Every markdown file worth reading."""
    return _walk(root)[0]


def _is_exempted(lines: list[str], index: int) -> bool:
    start = max(0, index - _CONTEXT_WINDOW)
    window = lines[start : index + 1]
    return any(marker in line for line in window for marker in _EXEMPTION_MARKERS)


def find_violations(root: Path, *, unreadable: list[str] | None = None) -> list[dict[str, Any]]:
    """Every un-exempted `cd .claude/hooks-daemon` instruction in a doc.

    Args:
        root: Directory to sweep.
        unreadable: Optional sink for files that could not be decoded, so a
            permissions or encoding problem is reported rather than silently
            narrowing what was checked.

    Returns:
        One record per offending line, repo-relative path and 1-indexed line.
    """
    pattern = _daemon_dir_cd_pattern()
    violations: list[dict[str, Any]] = []
    for path in _candidate_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            if unreadable is not None:
                unreadable.append(f"{relative}: {exc}")
            continue

        lines = text.splitlines()
        for index, line in enumerate(lines):
            if pattern.search(line) is None:
                continue
            if _is_exempted(lines, index):
                continue
            violations.append(
                {
                    "file": relative,
                    "line": index + 1,
                    "rule": "daemon-dir-cd-in-docs",
                    "message": (
                        "instructs `cd` into `.claude/hooks-daemon/`, which "
                        "daemon_location_guard denies for an agent; run from "
                        "the project root instead, mark the step OWNER-ONLY, "
                        "or mark a documentation-only example BLOCKED-EXAMPLE"
                    ),
                }
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_PROJECT_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    candidate_files, files_seen = _walk(root)
    files_scanned = len(candidate_files)
    # A missing or empty root is a failure, never a clean tree of 0 files.
    vacuous = vacuous_scan_failure(
        examined=files_scanned, candidates=files_seen, noun="markdown files", root=root
    )
    unreadable: list[str] = []
    violations = find_violations(root, unreadable=unreadable)

    if args.json_output:
        output_file = root / _ARTEFACT_NAME if root != _PROJECT_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(
                {
                    "summary": {
                        "passed": not violations and vacuous is None,
                        "vacuous_scan": vacuous,
                        "total_violations": len(violations),
                        "files_scanned": files_scanned,
                        "unreadable_files": len(unreadable),
                    },
                    "violations": violations,
                    "unreadable": unreadable,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        for item in violations:
            print(f"{item['file']}:{item['line']}  {item['message']}")
        print(f"\n{len(violations)} violation(s) ({files_scanned} files scanned)")
        if unreadable:
            print(f"{len(unreadable)} file(s) could not be decoded and were not checked")
    if vacuous is not None:
        print(f"FAILED: {vacuous}", file=sys.stderr)

    return 1 if violations or vacuous is not None else 0


if __name__ == "__main__":
    sys.exit(main())
