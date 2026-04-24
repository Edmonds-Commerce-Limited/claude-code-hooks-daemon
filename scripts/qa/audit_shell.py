#!/usr/bin/env python3
"""Audit shell scripts for error-hiding patterns that violate FAIL FAST.

Companion to scripts/qa/audit_error_hiding.py (which only scans Python via
AST). That auditor has zero visibility into .sh / .bash files, which is
how the hooks_deploy.sh chmod-silencer (issue #29) slipped through QA:

    chmod +x "$hook_file" 2>/dev/null || true

Combining ``2>/dev/null`` (drop stderr) with ``|| true`` (drop exit code)
leaves no recovery path — the operation can fail silently and no downstream
code can ever notice. This scanner flags that combination specifically.

Legitimate exceptions (e.g. ``daemon stop`` when the daemon may not exist)
must carry an explicit marker:

    cmd 2>/dev/null || true  # shell-audit: allow -- daemon may not be running

or on the line above:

    # shell-audit: allow -- snapshot restore is best-effort
    cp src dst 2>/dev/null || true

The marker REQUIRES a ``-- <reason>`` suffix. A bare ``# shell-audit: allow``
is itself a violation (``marker-missing-reason``) — documenting the reason
is the whole point.

Usage:
    scripts/qa/audit_shell.py                          # scan scripts/
    scripts/qa/audit_shell.py --json                   # emit JSON for QA
    scripts/qa/audit_shell.py --scan-dir some/other    # custom root
    scripts/qa/audit_shell.py --output /tmp/x.json     # custom output

Exit codes:
    0 - clean
    1 - violations found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCAN_DIR = REPO_ROOT / "scripts"
DEFAULT_OUTPUT = REPO_ROOT / "untracked" / "qa" / "shell_audit.json"

# Three shapes of "drop stderr + drop exit code" in a single command.
# Each is paired with `|| true` that immediately follows (allowing a space or two).
_DOUBLE_SUPPRESS_PATTERNS = [
    re.compile(r"2>\s*/dev/null\s*\|\|\s*true\b"),
    re.compile(r">\s*/dev/null\s+2>&1\s*\|\|\s*true\b"),
    re.compile(r"&>\s*/dev/null\s*\|\|\s*true\b"),
]

_MARKER_WITH_REASON = re.compile(r"#\s*shell-audit:\s*allow\s*--\s*\S")
_MARKER_WITHOUT_REASON = re.compile(r"#\s*shell-audit:\s*allow\b")


@dataclass
class Violation:
    """A single shell-audit finding."""

    file: str
    line: int
    rule: str
    message: str


def _strip_inline_comment(line: str) -> str:
    """Return the code portion of a line (everything before the first '#')."""
    # Naive: a '#' inside single/double quotes in shell is NOT a comment, but
    # the patterns we care about never appear quoted in practice. Keep simple.
    idx = line.find("#")
    return line if idx == -1 else line[:idx]


def _line_has_double_suppression(code_portion: str) -> bool:
    return any(p.search(code_portion) for p in _DOUBLE_SUPPRESS_PATTERNS)


def _has_marker_with_reason(line: str) -> bool:
    return bool(_MARKER_WITH_REASON.search(line))


def _has_bare_marker(line: str) -> bool:
    return bool(_MARKER_WITHOUT_REASON.search(line)) and not _has_marker_with_reason(line)


def audit_text(source: str, filepath: str) -> list[Violation]:
    """Audit raw shell source text. Returns all violations."""
    violations: list[Violation] = []
    lines = source.splitlines()

    for idx, raw_line in enumerate(lines):
        lineno = idx + 1
        code = _strip_inline_comment(raw_line)

        if not _line_has_double_suppression(code):
            continue

        # Inline marker on the same line?
        if _has_marker_with_reason(raw_line):
            continue
        # Bare marker ("# shell-audit: allow" with no reason) is itself a violation.
        if _has_bare_marker(raw_line):
            violations.append(
                Violation(
                    file=filepath,
                    line=lineno,
                    rule="marker-missing-reason",
                    message=(
                        "shell-audit marker present but no reason given; "
                        "add '-- <why this suppression is correct>'"
                    ),
                )
            )
            continue

        # Above-line marker: the immediately preceding line is a marker-with-reason.
        if idx > 0 and _has_marker_with_reason(lines[idx - 1]):
            continue

        violations.append(
            Violation(
                file=filepath,
                line=lineno,
                rule="double-suppression",
                message=(
                    "combined stderr + exit-code suppression leaves no recovery path; "
                    "fix the code, or add '# shell-audit: allow -- <reason>' marker "
                    "inline or on the line above"
                ),
            )
        )

    return violations


def audit_file(path: Path) -> list[Violation]:
    """Audit a single shell file."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        # FAIL FAST: we want to see read failures, not swallow them.
        raise RuntimeError(f"could not read {path}: {exc}") from exc
    return audit_text(source, str(path))


_EXCLUDE_DIR_PARTS = {
    "untracked",
    "__pycache__",
    ".git",
    "node_modules",
}


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDE_DIR_PARTS for part in path.parts)


def audit_directory(root: Path) -> list[Violation]:
    """Audit every .sh / .bash file under root (recursively)."""
    violations: list[Violation] = []
    for pattern in ("*.sh", "*.bash"):
        for script in sorted(root.rglob(pattern)):
            if _is_excluded(script):
                continue
            violations.extend(audit_file(script))
    return violations


def _format_text_report(violations: list[Violation]) -> str:
    if not violations:
        return "shell-audit: no violations\n"
    lines = [f"shell-audit: {len(violations)} violation(s)\n"]
    for v in violations:
        lines.append(f"  {v.file}:{v.line}  [{v.rule}]  {v.message}")
    return "\n".join(lines) + "\n"


def _write_json(violations: list[Violation], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": [asdict(v) for v in violations],
    }
    output_path.write_text(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output to --output path (default: untracked/qa/shell_audit.json)",
    )
    parser.add_argument(
        "--scan-dir",
        type=Path,
        default=DEFAULT_SCAN_DIR,
        help="Directory to scan (default: scripts/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write JSON (only when --json is given)",
    )
    args = parser.parse_args(argv)

    if not args.scan_dir.is_dir():
        print(f"shell-audit: scan dir does not exist: {args.scan_dir}", file=sys.stderr)
        return 1

    violations = audit_directory(args.scan_dir)

    if args.json:
        _write_json(violations, args.output)
    else:
        sys.stdout.write(_format_text_report(violations))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
