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

A second, unrelated rule (Plan 00285 DBF guard) also lives here:
``bootstrap-reexec-dollar0-source`` flags ``$0``-relative path resolution
(``dirname "$0"``, ``${0%/*}``) appearing AFTER a self-bootstrap re-exec
stanza (``# === SELF-BOOTSTRAP BEGIN`` ... ``END``). That stanza's
``exec bash "$tmpfile" --already-bootstrapped "$@"`` relocates the running
script's own ``$0`` to a mktemp path, so a later sibling ``source`` resolved
relative to it silently breaks on every install whose local script differs
from the latest release — the exact bug daemon-cli.sh/health-check.sh/
init-handlers.sh shipped with. It shares this file (and its scan/JSON/marker
plumbing) rather than living standalone because both rules are "shell
scripts doing something structurally unsound", and the QA pipeline already
wires one ``shell_audit`` check.

Usage:
    scripts/qa/audit_shell.py                          # scan scripts/ + skill scripts/
    scripts/qa/audit_shell.py --json                   # emit JSON for QA
    scripts/qa/audit_shell.py --scan-dir some/other    # custom root (single dir)
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
# Plan 00285: the self-bootstrap stanza (and therefore the
# bootstrap-reexec-dollar0-source rule) only ever appears in the deployed
# skill scripts, which live outside scripts/ — scan both by default so the
# new rule actually covers the files it exists to protect.
DEFAULT_SKILL_SCAN_DIR = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts"
)
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

# Plan 00285 DBF guard: a script that self-bootstraps by `exec`-ing a
# freshly-downloaded copy of itself relocates its own $0 to a mktemp path.
# Any LATER path resolution relative to $0 (a sibling `source`, most often)
# then silently breaks on every install whose local script differs from the
# latest release — the exact bug daemon-cli.sh/health-check.sh/
# init-handlers.sh shipped with. Only checked AFTER the bootstrap stanza:
# referencing $0 before the re-exec point is unaffected by it.
_BOOTSTRAP_BEGIN_MARKER = "SELF-BOOTSTRAP BEGIN"
_BOOTSTRAP_END_MARKER = "SELF-BOOTSTRAP END"
_DOLLAR0_RELATIVE_PATTERN = re.compile(r'dirname\s+"?\$0"?|\$\{0%/\*\}')


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

    violations.extend(_audit_bootstrap_reexec_dollar0(lines, filepath))
    return violations


def _find_bootstrap_end_index(lines: list[str]) -> int | None:
    """Line index (0-based) of the SELF-BOOTSTRAP END marker, or None."""
    for idx, line in enumerate(lines):
        if _BOOTSTRAP_END_MARKER in line:
            return idx
    return None


def _audit_bootstrap_reexec_dollar0(lines: list[str], filepath: str) -> list[Violation]:
    """Flag $0-relative path resolution appearing AFTER a self-bootstrap stanza.

    A script with no bootstrap stanza never relocates its own $0, so this
    rule only applies once ``SELF-BOOTSTRAP BEGIN`` is present at all, and
    only to lines after the matching ``SELF-BOOTSTRAP END`` marker — a
    reference to $0 before the re-exec point is unaffected by it.
    """
    if not any(_BOOTSTRAP_BEGIN_MARKER in line for line in lines):
        return []

    end_idx = _find_bootstrap_end_index(lines)
    start_idx = end_idx + 1 if end_idx is not None else 0

    violations: list[Violation] = []
    for idx in range(start_idx, len(lines)):
        raw_line = lines[idx]
        code = _strip_inline_comment(raw_line)

        if not _DOLLAR0_RELATIVE_PATTERN.search(code):
            continue
        if _has_marker_with_reason(raw_line):
            continue
        if idx > start_idx and _has_marker_with_reason(lines[idx - 1]):
            continue

        violations.append(
            Violation(
                file=filepath,
                line=idx + 1,
                rule="bootstrap-reexec-dollar0-source",
                message=(
                    "$0-relative path resolution after a self-bootstrap re-exec "
                    'stanza is unsound: `exec bash "$tmpfile" --already-bootstrapped '
                    '"$@"` relocates $0 to a mktemp path, so a sibling lookup based '
                    "on it silently breaks on every install whose local script "
                    "differs from the latest release (Plan 00285). Anchor to a value "
                    "derived from PROJECT_ROOT/DAEMON_DIR instead, or add "
                    "'# shell-audit: allow -- <reason>' if this reference genuinely "
                    "predates the re-exec."
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
        default=None,
        help="Directory to scan (default: scripts/ AND the skill scripts dir, both)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where to write JSON (only when --json is given)",
    )
    args = parser.parse_args(argv)

    scan_dirs = (
        [args.scan_dir]
        if args.scan_dir is not None
        else [
            DEFAULT_SCAN_DIR,
            DEFAULT_SKILL_SCAN_DIR,
        ]
    )

    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            print(f"shell-audit: scan dir does not exist: {scan_dir}", file=sys.stderr)
            return 1

    violations = [v for scan_dir in scan_dirs for v in audit_directory(scan_dir)]

    if args.json:
        _write_json(violations, args.output)
    else:
        sys.stdout.write(_format_text_report(violations))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
