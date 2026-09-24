#!/usr/bin/env python3
"""Generated-doc drift check — the committed handler doc must match its generator.

Plan 00402, built under DBF (``CLAUDE.md`` Core Standard 15).
``.claude/HOOKS-DAEMON.md`` is written by exactly one command, ``generate-docs``
(``regenerate-docs`` calls it). A daemon restart regenerates the ``CLAUDE.md``
``<hooksdaemon>`` block but never this file, so a handler added in-repo updated
one artefact and silently rotted the other: the file sat announcing
"UserPromptSubmit (5 handlers)" while six were registered, and omitted
``daemon_upgrade_detector`` entirely.

Nothing could see it. The docs-QA ``generated-doc-hand-edit`` sweep compares
only the embedded version marker with ``__version__``, so drift WITHIN one
version — every in-repo handler addition — is invisible by construction.
``check_doc_truth.py`` and ``check_handler_reference.py`` both READ this file as
ground truth, so a stale copy also quietly weakens them.

This check regenerates the doc through the real CLI into a throwaway directory
and compares it with the committed file line by line:

``generated-doc-drift``
    A body line differs. Reported per line, naming what the committed file has
    that the generator no longer emits and what the generator emits that the
    committed file lacks.

``generated-doc-marker-missing``
    The committed file has no ``> Generated on YYYY-MM-DD (vX.Y.Z)`` marker.

**The marker line is excluded from the comparison, deliberately.** It is the
project's only durable record of the version its tracked assets were deployed
FROM: ``utils/deployed_version.py`` parses it and ``scripts/upgrade.sh`` reads
it as the upgrade's FROM side. A check that demanded today's date and the
running version would push every reader to restamp it, which is exactly the
damage Plan 00402 ruled out. Its ABSENCE is still flagged, because excluding
it would otherwise make a missing marker pass silently.

The committed file is only ever READ. Repair is the author's call:
``bin/hooks-daemon generate-docs`` (or ``regenerate-docs``), then commit.

Usage:
    python scripts/qa/check_generated_doc_drift.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - The committed body matches fresh generator output
    1 - Drift or a missing marker
    2 - Operational failure (committed doc missing, or the generator failed)
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess  # nosec B404 - runs the daemon's own CLI to regenerate the doc
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SRC_DIR: Final[Path] = _PROJECT_ROOT / "src"

_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "generated_doc_drift.json"
_TOOL_NAME: Final[str] = "generated_doc_drift"

_GENERATED_DOC_PARTS: Final[tuple[str, str]] = (".claude", "HOOKS-DAEMON.md")
_GENERATED_DOC_REL: Final[str] = "/".join(_GENERATED_DOC_PARTS)

# The daemon CLI, run from THIS checkout's source, so the comparison is always
# against the generator the change under review ships.
_GENERATE_ARGS: Final[tuple[str, ...]] = (
    "-m",
    "claude_code_hooks_daemon.daemon.cli",
    "generate-docs",
)
_GENERATE_TIMEOUT_SECONDS: Final[int] = 120
_STDERR_EXCERPT_CHARS: Final[int] = 500

RULE_DRIFT: Final[str] = "generated-doc-drift"
RULE_MARKER_MISSING: Final[str] = "generated-doc-marker-missing"
_ALL_RULES: Final[tuple[str, ...]] = (RULE_DRIFT, RULE_MARKER_MISSING)

_REMEDIATION_DRIFT: Final[str] = (
    "Run `bin/hooks-daemon generate-docs` (or `regenerate-docs`) and commit "
    f"`{_GENERATED_DOC_REL}` in the same change that altered the handler set. "
    "A daemon restart does NOT refresh this file."
)
_REMEDIATION_MARKER_MISSING: Final[str] = (
    "Run `bin/hooks-daemon generate-docs` to restore the `> Generated on ...` "
    "marker. It is the only durable record of the version the tracked assets "
    "were deployed from, and `scripts/upgrade.sh` reads it."
)


@dataclass(frozen=True)
class Violation:
    """One way the committed doc disagrees with fresh generator output."""

    rule: str
    file: str
    line: int
    message: str
    remediation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "remediation": self.remediation,
        }


class GenerationError(RuntimeError):
    """``generate-docs`` could not produce a fresh copy to compare against."""


def _marker_re() -> re.Pattern[str]:
    """The one marker parser, shared with ``upgrade.sh``'s reader.

    Imported rather than restated: a second copy of this pattern is how the
    two drift apart, and the one that quietly stops matching would make this
    check compare the marker line after all.
    """
    if str(_SRC_DIR) not in sys.path:
        sys.path.insert(0, str(_SRC_DIR))
    from claude_code_hooks_daemon.utils.deployed_version import VERSION_MARKER_RE

    return VERSION_MARKER_RE


def generate_fresh(root: Path) -> str:
    """Regenerate ``root``'s handler doc into a throwaway directory and return it.

    Raises:
        GenerationError: when the generator exits non-zero or writes nothing.
            FAIL FAST — a drift check with nothing to compare against would
            report clean while checking nothing.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(_SRC_DIR), env.get("PYTHONPATH"))))
    with tempfile.TemporaryDirectory(prefix="generated-doc-drift-") as scratch:
        output = Path(scratch) / _GENERATED_DOC_PARTS[-1]
        result = subprocess.run(  # nosec B603 - fixed argv, no shell, no user input
            [
                sys.executable,
                *_GENERATE_ARGS,
                "--project-root",
                str(root),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=_GENERATE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
        if result.returncode != 0 or not output.is_file():
            raise GenerationError(
                f"`generate-docs --project-root {root}` failed (rc={result.returncode}); "
                "there is no fresh copy to compare against. stderr: "
                f"{result.stderr.strip()[:_STDERR_EXCERPT_CHARS]}"
            )
        return output.read_text(encoding="utf-8")


def _body(text: str, marker: re.Pattern[str]) -> list[tuple[int, str]]:
    """Every line except the deployed-from marker, with its 1-based number."""
    return [
        (number, line)
        for number, line in enumerate(text.splitlines(), 1)
        if marker.match(line) is None
    ]


def compare(committed: str, generated: str) -> list[Violation]:
    """Every way ``committed`` disagrees with ``generated``, marker excluded."""
    marker = _marker_re()
    violations: list[Violation] = []

    if not any(marker.match(line) for line in committed.splitlines()):
        violations.append(
            Violation(
                rule=RULE_MARKER_MISSING,
                file=_GENERATED_DOC_REL,
                line=0,
                message="the committed doc carries no `> Generated on ... (vX.Y.Z)` marker",
                remediation=_REMEDIATION_MARKER_MISSING,
            )
        )

    committed_body = _body(committed, marker)
    generated_body = [line for _number, line in _body(generated, marker)]
    committed_lines = [line for _number, line in committed_body]
    # Past the committed file's end, an addition anchors to the line after its last.
    end_of_file = (committed_body[-1][0] + 1) if committed_body else 1

    matcher = difflib.SequenceMatcher(a=committed_lines, b=generated_body, autojunk=False)
    for tag, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        for index in range(a_start, a_end):
            number, line = committed_body[index]
            violations.append(
                Violation(
                    rule=RULE_DRIFT,
                    file=_GENERATED_DOC_REL,
                    line=number,
                    message=f"generate-docs no longer emits this line: `{line}`",
                    remediation=_REMEDIATION_DRIFT,
                )
            )
        anchor = committed_body[a_start][0] if a_start < len(committed_body) else end_of_file
        violations.extend(
            Violation(
                rule=RULE_DRIFT,
                file=_GENERATED_DOC_REL,
                line=anchor,
                message=f"generate-docs emits a line the committed doc lacks: `{line}`",
                remediation=_REMEDIATION_DRIFT,
            )
            for line in generated_body[b_start:b_end]
        )
    return violations


def scan(root: Path) -> tuple[list[Violation], int]:
    """Compare ``root``'s committed handler doc with fresh generator output.

    Returns:
        The violations, and how many committed body lines were compared.

    Raises:
        FileNotFoundError: when the committed doc is absent.
        GenerationError: when ``generate-docs`` fails.
    """
    doc_path = root.joinpath(*_GENERATED_DOC_PARTS)
    if not doc_path.is_file():
        raise FileNotFoundError(
            f"committed handler doc not found at {doc_path}. "
            "Run `bin/hooks-daemon generate-docs` to produce it."
        )
    committed = doc_path.read_text(encoding="utf-8")
    violations = compare(committed, generate_fresh(root))
    return violations, len(_body(committed, _marker_re()))


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
        violations, lines_checked = scan(root)
    except (FileNotFoundError, GenerationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "tool": _TOOL_NAME,
        "summary": {
            "passed": not violations,
            "total_violations": len(violations),
            # The denominator: a comparison over zero lines would pass anything.
            "lines_checked": lines_checked,
            "by_rule": {rule: sum(1 for v in violations if v.rule == rule) for rule in _ALL_RULES},
        },
        "violations": [v.to_dict() for v in violations],
    }

    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif violations:
        print(f"Found {len(violations)} generated-doc drift violation(s):")
        for violation in violations:
            print(f"  [{violation.rule}] {violation.file}:{violation.line}: {violation.message}")
        # One line per drifted row would repeat the same fix dozens of times.
        for remediation in dict.fromkeys(v.remediation for v in violations):
            print(f"    Fix: {remediation}")
    else:
        print(f"No generated-doc drift ({lines_checked} lines checked)")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
