#!/usr/bin/env python3
"""British-English check over the TRACKED tree.

DBF (``CLAUDE.md`` Core Standard 15). The daemon ships ``british_english``, a
handler that flags ``behavior``/``organize``/``analyze``/``color`` when an agent
WRITES a content file. The project's own tracked docs carried 85 such spellings
across 28 files — ``CLAUDE/CodeLifecycle/General.md`` said "Update tests when
changing behavior" while ``README.md`` said "behaviour" two directories away.

The handler was never going to catch them: it fires on a write, and these were
already on disk. That is the corollary in Core Standard 15 — every write-time
rule needs a batch equivalent, or everything predating it is permanently
unexamined. This is that equivalent.

**The rule has one definition.** ``spelling_checks()`` returns the handler's own
``SPELLING_CHECKS`` object and the scan delegates to the handler's
``find_american_spellings``, so the two surfaces cannot disagree about either
the word list or how code blocks are skipped.

Scope differs from the handler in one deliberate way: this check also ignores
**inline code spans**. The handler only skips fenced blocks, which is right for
a write-time warning, but a batch scan reads reference documentation that
legitimately NAMES the mappings it enforces. Flagging those would make the rule
impossible to document, and a gate that cannot be documented gets a blanket
exemption and then dies.

Exemptions are by LOCATION and each earns its place:

- ``CLAUDE/Plan/``, ``RELEASES/``, ``CHANGELOG.md``, ``CLAUDE/UPGRADES/`` are
  historical records. Editing them to change a spelling falsifies an account of
  what was written at the time.
- fixture directories hold DELIBERATE specimens.
  ``CLAUDE/AcceptanceTests/fixtures/test-files/sample.md`` exists to make the
  handler fire; "fixing" it would destroy the evidence that it works.

Usage:
    python scripts/qa/check_british_english.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - No violations found
    1 - Violations found
    2 - Operational failure (not a git repository, git unavailable)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SRC_DIR_NAME: Final[str] = "src"

_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "british_english.json"

_GIT_BINARY: Final[str] = "git"
_GIT_TIMEOUT_SECONDS: Final[int] = 60
_NUL: Final[str] = "\0"

_TOOL_NAME: Final[str] = "british_english"
RULE_AMERICAN_SPELLING: Final[str] = "american-spelling"

# Historical records: dated accounts of what was written at the time.
_ARCHIVE_PREFIXES: Final[tuple[str, ...]] = (
    "CLAUDE/Plan/",
    "RELEASES/",
    "CLAUDE/UPGRADES/",
    "untracked/",
)
_ARCHIVE_BASENAMES: Final[frozenset[str]] = frozenset({"CHANGELOG.md"})

# Directory names holding deliberate specimens of the thing being checked.
_FIXTURE_DIRNAMES: Final[frozenset[str]] = frozenset({"fixtures", "test-files", "__fixtures__"})

# Inline code spans: an opening backtick run, NON-EMPTY content, matching close.
# The content must be non-empty or the pattern would match the first two
# backticks of a ``` fence marker as an empty span, mangling the line and
# breaking the handler's fence tracking downstream.
_INLINE_CODE: Final[re.Pattern[str]] = re.compile(r"(`+)(?:(?!\1).)+?\1")

# A line that opens or closes a fenced block. Left byte-for-byte alone so the
# handler still sees the fence and skips the block.
_FENCE_MARKER: Final[str] = "```"

_REMEDIATION: Final[str] = (
    "Use the British spelling. This project ships a handler that enforces it on "
    "every write, so an American spelling in its own docs is the rule failing "
    "its author. If the word is a quotation or an identifier, wrap it in "
    "backticks — inline code is not checked."
)


@dataclass(frozen=True)
class Violation:
    """One American spelling in one tracked file."""

    rule: str
    file: str
    line: int
    american: str
    british: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "american": self.american,
            "british": self.british,
            "text": self.text,
            "remediation": _REMEDIATION,
        }


@dataclass
class Report:
    """Accumulated findings for one repository."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "tool": _TOOL_NAME,
            "summary": {
                "passed": self.passed,
                "total_violations": len(self.violations),
            },
            "violations": [v.to_dict() for v in self.violations],
        }


def _handler_class() -> Any:
    """Import the handler, priming ``sys.path`` first.

    The import is function-local for the same reason as in
    ``check_handler_reference.py``: the daemon package lives outside
    ``scripts/qa``, so the path has to be primed before the import, and doing
    that at module scope would put an import below a statement.

    Raises:
        ImportError: when the daemon package cannot be imported. FAIL FAST — a
            spelling check that could not read the word list would report
            "clean" while verifying nothing.
    """
    entry = str(_PROJECT_ROOT / _SRC_DIR_NAME)
    if entry not in sys.path:
        sys.path.insert(0, entry)

    from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import (
        BritishEnglishHandler,
    )

    return BritishEnglishHandler


def spelling_checks() -> dict[str, str]:
    """The one and only word list — the handler's own.

    Returned by identity rather than copied so a test can assert the two
    surfaces share an object, not merely equal contents.
    """
    checks: dict[str, str] = _handler_class().SPELLING_CHECKS
    return checks


def tracked_files(root: Path) -> tuple[str, ...]:
    """Every path in ``root``'s git index, repo-relative.

    Raises:
        RuntimeError: when ``root`` is not a git repository or git is
            unavailable. FAIL FAST — a check that silently reported "clean"
            because it could not read the index would be the blind guard this
            file exists to replace.
    """
    # SECURITY: list-form argv, no shell (B603); git is a trusted tool (B607).
    result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
        [_GIT_BINARY, "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not read the git index at {root}: {result.stderr.strip() or 'git failed'}"
        )
    return tuple(path for path in result.stdout.split(_NUL) if path)


def _is_exempt(rel_path: str) -> bool:
    """True when ``rel_path`` is a historical record or a deliberate fixture."""
    if rel_path.startswith(_ARCHIVE_PREFIXES):
        return True
    if rel_path in _ARCHIVE_BASENAMES:
        return True
    return bool(_FIXTURE_DIRNAMES.intersection(rel_path.split("/")[:-1]))


def _strip_inline_code(line: str) -> str:
    """Blank out inline code spans, leaving nothing that could match.

    Fence delimiters are returned untouched: the handler tracks fenced blocks
    by looking for a line starting with ``` and rewriting one would silently
    turn code into prose.
    """
    if line.strip().startswith(_FENCE_MARKER):
        return line
    return _INLINE_CODE.sub(" ", line)


def scan_content(rel_path: str, content: str) -> list[Violation]:
    """Find American spellings in ``content``, skipping code."""
    handler = _handler_class()()
    checks = spelling_checks()
    stripped = "\n".join(_strip_inline_code(line) for line in content.split("\n"))
    return [
        Violation(
            rule=RULE_AMERICAN_SPELLING,
            file=rel_path,
            line=int(issue["line"]),
            american=str(issue["american"]),
            british=checks[rf"\b{str(issue['american']).lower()}\b"],
            text=str(issue["text"]),
        )
        for issue in handler.find_american_spellings(stripped)
    ]


def scan(root: Path) -> Report:
    """Check every eligible tracked file in ``root``."""
    report = Report()
    extensions = tuple(_handler_class().CHECK_EXTENSIONS)
    for rel_path in tracked_files(root):
        if not rel_path.endswith(extensions) or _is_exempt(rel_path):
            continue
        target = root / rel_path
        # A tracked path with no regular file behind it (sparse checkout,
        # submodule gitlink) carries no prose to judge. Tested explicitly
        # rather than by catching the read error: FAIL FAST means a genuinely
        # unreadable or non-UTF-8 document in the index raises here instead of
        # being silently counted as clean.
        if not target.is_file():
            continue
        report.violations.extend(scan_content(rel_path, target.read_text(encoding="utf-8")))
    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check tracked docs for American spellings.")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    try:
        report = scan(root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = report.to_dict()

    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif report.violations:
        print(f"Found {len(report.violations)} American spelling(s):")
        for violation in report.violations:
            print(
                f"  {violation.file}:{violation.line}  "
                f"'{violation.american}' -> '{violation.british}'"
            )
        print(f"\nFix: {_REMEDIATION}")
    else:
        print("No American spellings found")

    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
