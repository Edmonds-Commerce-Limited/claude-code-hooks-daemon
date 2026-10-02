#!/usr/bin/env python3
"""Module length report -- names every Python module under ``src/`` over a stated bound.

N314: ``subagent_full_qa_blocker.py`` reached 5,300 lines through review rounds that
never saw its size, and nothing in ``scripts/qa/`` measured module length.

The bound is ``MAX_MODULE_LINES`` (1000). The 672 modules under ``src/`` have a median
of 170 lines, a 90th percentile of 558 and a 95th of 848; 1000 is about six times the
median and leaves 26 modules (under 4%) over it, so a report is a short list rather than
a wall, and a module that crosses it is already an outlier by any reading of the
distribution.

**This check is REPORT-ONLY and always exits 0 for findings.** Today's outliers (the
longest is ``daemon/cli.py`` at over 11,000 lines) would fail a gate, and the only way
to pass one is an exception list, which is an allowlist and needs an owner decision.
Turning this into a gate awaits that decision; nothing here carries an exception list.

Usage:
    python scripts/qa/check_module_length.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - Report produced (with or without modules over the bound)
    2 - Operational failure (no ``src/`` directory to measure)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "module_length.json"
_TOOL_NAME: Final[str] = "module_length"
_SOURCE_DIR: Final[str] = "src"
_MODE: Final[str] = "report-only"

MAX_MODULE_LINES: Final[int] = 1000
RULE_MODULE_TOO_LONG: Final[str] = "module-too-long"

_REMEDIATION: Final[str] = (
    "Split the module along its existing seams. This report does not gate: making it "
    "a gate awaits an owner decision on the exception list for today's outliers."
)


@dataclass(frozen=True)
class Finding:
    """One module longer than ``MAX_MODULE_LINES``."""

    file: str
    lines: int

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": RULE_MODULE_TOO_LONG,
            "file": self.file,
            "line": 0,
            "lines": self.lines,
            "message": f"{self.lines} lines, over the bound of {MAX_MODULE_LINES}",
            "remediation": _REMEDIATION,
        }


def scan(root: Path) -> tuple[list[Finding], int]:
    """Measure every ``*.py`` under ``root/src``.

    Returns:
        The modules over the bound, longest first, and how many modules were measured.

    Raises:
        FileNotFoundError: when ``root`` has no ``src/`` directory. FAIL FAST -- a report
            over zero modules would read as clean while measuring nothing.
    """
    source = root / _SOURCE_DIR
    if not source.is_dir():
        raise FileNotFoundError(f"no {_SOURCE_DIR}/ directory under {root}")
    findings: list[Finding] = []
    scanned = 0
    for path in sorted(source.rglob("*.py")):
        scanned += 1
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_MODULE_LINES:
            findings.append(Finding(path.relative_to(root).as_posix(), lines))
    findings.sort(key=lambda finding: (-finding.lines, finding.file))
    return findings, scanned


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to check")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    try:
        findings, scanned = scan(root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "tool": _TOOL_NAME,
        "summary": {
            "mode": _MODE,
            # Report-only: findings never fail the run.
            "passed": True,
            "bound": MAX_MODULE_LINES,
            "modules_scanned": scanned,
            "modules_over_bound": len(findings),
        },
        "violations": [finding.to_dict() for finding in findings],
    }

    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif findings:
        print(
            f"{len(findings)} of {scanned} module(s) over {MAX_MODULE_LINES} lines "
            f"({_MODE}, not a gate):"
        )
        for finding in findings:
            print(f"  {finding.lines:>6}  {finding.file}")
        print(f"    {_REMEDIATION}")
    else:
        print(f"No module over {MAX_MODULE_LINES} lines ({scanned} scanned)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
