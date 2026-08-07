#!/usr/bin/env python3
"""Doc-vs-generated-truth check — prose must agree with the live registry.

Plan 00200 Task 6.2, built under DBF (``CLAUDE.md`` Core Standard 15). Two
``README.md`` bullets described handlers as doing the **opposite** of what they
do (an advisory handler as "Blocks commits"; a handler that *requires* absolute
paths as one that "Prevents" them), and ``CLAUDE.md`` claimed "ALL 10 checks"
against a suite that runs more than that.

The guard did not exist — but the ground truth did. ``.claude/HOOKS-DAEMON.md``
is generated from live config by ``generate-docs`` and had no consumer. This
check gives it one.

**Scope is deliberately narrow.** A general prose-claim checker would need to
guess, and a gate that guesses gets switched off. Only mechanically decidable
claims are checked:

``handler-ref-unknown``
    A doc bullet naming a handler key that is not in the generated registry.

``handler-claim-mismatch``
    A bullet whose verb asserts blocking for an ADVISORY/CONTEXT handler, or
    advisory-only behaviour for a BLOCKING/TERMINAL one.

``handler-count-drift``
    "N production handlers across M event types" must match the registry.
    Counts have generated ground truth, so they are asserted rather than banned.

``qa-check-count-hardcoded``
    The inverse: no generated truth exists for the size of the QA suite, so a
    hardcoded count is guaranteed to drift. The fix is to stop asserting one.

Bullets opt in by naming their handler key — ``- **Display name**
(`handler_key`) — description``. That keeps matching exact (no fuzzy
name-to-handler guessing) and makes the docs more useful to a reader who wants
to find the handler. A bullet with no key is not checked.

Usage:
    python scripts/qa/check_doc_truth.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - No violations found
    1 - Violations found
    2 - Operational failure (generated truth missing)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "doc_truth.json"
_TOOL_NAME: Final[str] = "doc_truth"

# Generated ground truth, produced by `hooks-daemon generate-docs`.
_GENERATED_DOC_PARTS: Final[tuple[str, str]] = (".claude", "HOOKS-DAEMON.md")

# Prose files whose factual claims are checked, relative to the root.
_CHECKED_DOCS: Final[tuple[str, ...]] = (
    "README.md",
    "CLAUDE.md",
    "CLAUDE/development/RELEASING.md",
)

RULE_REF_UNKNOWN: Final[str] = "handler-ref-unknown"
RULE_CLAIM_MISMATCH: Final[str] = "handler-claim-mismatch"
RULE_COUNT_DRIFT: Final[str] = "handler-count-drift"
RULE_QA_COUNT: Final[str] = "qa-check-count-hardcoded"

# A generated table row: | priority | handler | BEHAVIOR | description |
_GENERATED_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*\|\s*(?P<behavior>[A-Z-]+)\s*\|"
)
# A generated event-type section heading: ### PreToolUse (37 handlers)
_GENERATED_SECTION_RE: Final[re.Pattern[str]] = re.compile(
    r"^###\s+\S+\s+\((?P<count>\d+)\s+handlers?\)\s*$"
)

# A doc bullet that opts in by naming its handler key in backticks.
_BULLET_RE: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\*\*(?P<name>[^*]+)\*\*\s*\(`(?P<key>[a-z][a-z0-9_]*)`\)\s*[—-]\s*(?P<desc>.+)$"
)

# "92 production handlers across 15 event types"
_COUNT_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<handlers>\d+)\s+production handlers?\s+across\s+(?P<events>\d+)\s+event types?"
)

# A hardcoded QA-suite size, e.g. "ALL 10 checks" / "all 13 checks must pass".
_QA_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"\bALL\s+(?P<count>\d+)\s+checks?\b", re.I)

# Behaviours in the generated table that genuinely stop a tool call.
_BLOCKING_BEHAVIOURS: Final[frozenset[str]] = frozenset({"BLOCKING", "TERMINAL"})

# Verbs asserting that the handler stops something.
_BLOCKING_VERBS: Final[tuple[str, ...]] = (
    "blocks",
    "prevents",
    "denies",
    "refuses",
    "rejects",
    "forbids",
)
# Verbs asserting that the handler only informs.
_ADVISORY_VERBS: Final[tuple[str, ...]] = (
    "advises",
    "warns",
    "suggests",
    "reminds",
    "alerts",
    "recommends",
)

_REMEDIATION_REF_UNKNOWN: Final[str] = (
    "The named handler is not in .claude/HOOKS-DAEMON.md. Correct the key, or "
    "regenerate the doc (`hooks-daemon generate-docs`) if the handler is new."
)
_REMEDIATION_COUNT_DRIFT: Final[str] = (
    "Update the sentence to the generated figures, or drop the numbers. "
    "Regenerate .claude/HOOKS-DAEMON.md first so it reflects live config."
)
_REMEDIATION_QA_COUNT: Final[str] = (
    "Do not hardcode the size of the QA suite — there is no generated ground "
    "truth for it, so the number drifts silently. Say 'all checks in the QA "
    "suite' instead."
)


@dataclass(frozen=True)
class Violation:
    """One prose claim contradicted by generated truth."""

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


@dataclass
class GeneratedTruth:
    """Handler behaviours and counts parsed from the generated doc."""

    behaviours: dict[str, str] = field(default_factory=dict)
    event_type_count: int = 0
    # Sum of the per-section ``(N handlers)`` headings — i.e. REGISTRATIONS,
    # not distinct classes. The two differ: `remind_prompt_library` and
    # `subagent_completion_logger` are each registered on both Stop and
    # SubagentStop, so the tree holds 92 registrations across 90 classes.
    # Counting distinct keys here produced a false positive against a README
    # that was correct — and a check that cries wolf gets switched off, so the
    # generated doc's own arithmetic is the ground truth.
    handler_count: int = 0


def parse_generated_truth(path: Path) -> GeneratedTruth:
    """Parse ``.claude/HOOKS-DAEMON.md`` into behaviours plus counts.

    Raises:
        FileNotFoundError: when the generated doc is absent. FAIL FAST — a
            doc-truth check with no ground truth would report "clean" while
            checking nothing, which is the failure this repo is auditing.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"generated ground truth not found at {path}. "
            "Run `hooks-daemon generate-docs` to produce it."
        )
    truth = GeneratedTruth()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        section = _GENERATED_SECTION_RE.match(raw_line)
        if section is not None:
            truth.event_type_count += 1
            truth.handler_count += int(section.group("count"))
            continue
        row = _GENERATED_ROW_RE.match(raw_line)
        if row is not None:
            truth.behaviours[row.group("handler")] = row.group("behavior")
    return truth


def _first_verb_class(description: str) -> str | None:
    """Classify a bullet's leading claim as 'blocking', 'advisory' or unknown."""
    lowered = description.lower()
    for verb in _BLOCKING_VERBS:
        if verb in lowered:
            return "blocking"
    for verb in _ADVISORY_VERBS:
        if verb in lowered:
            return "advisory"
    return None


def _check_bullet(rel_file: str, line_no: int, line: str, truth: GeneratedTruth) -> list[Violation]:
    match = _BULLET_RE.match(line)
    if match is None:
        return []
    key = match.group("key")
    description = match.group("desc")

    if key not in truth.behaviours:
        return [
            Violation(
                rule=RULE_REF_UNKNOWN,
                file=rel_file,
                line=line_no,
                message=f"doc references handler `{key}`, which is not in the generated registry",
                remediation=_REMEDIATION_REF_UNKNOWN,
            )
        ]

    behaviour = truth.behaviours[key]
    claim = _first_verb_class(description)
    if claim is None:
        return []

    is_blocking = behaviour in _BLOCKING_BEHAVIOURS
    if claim == "blocking" and not is_blocking:
        return [
            Violation(
                rule=RULE_CLAIM_MISMATCH,
                file=rel_file,
                line=line_no,
                message=(
                    f"prose claims `{key}` blocks, but the generated registry "
                    f"records it as {behaviour}"
                ),
                remediation=(
                    f"Reword to match {behaviour} behaviour, or change the handler. "
                    "Describing an advisory handler as blocking is the failure this "
                    "check exists to prevent."
                ),
            )
        ]
    if claim == "advisory" and is_blocking:
        return [
            Violation(
                rule=RULE_CLAIM_MISMATCH,
                file=rel_file,
                line=line_no,
                message=(
                    f"prose describes `{key}` as advisory, but the generated "
                    f"registry records it as {behaviour}"
                ),
                remediation=f"Reword to match {behaviour} behaviour.",
            )
        ]
    return []


def _check_counts(rel_file: str, line_no: int, line: str, truth: GeneratedTruth) -> list[Violation]:
    violations: list[Violation] = []

    count_claim = _COUNT_CLAIM_RE.search(line)
    if count_claim is not None:
        claimed_handlers = int(count_claim.group("handlers"))
        claimed_events = int(count_claim.group("events"))
        if (claimed_handlers, claimed_events) != (truth.handler_count, truth.event_type_count):
            violations.append(
                Violation(
                    rule=RULE_COUNT_DRIFT,
                    file=rel_file,
                    line=line_no,
                    message=(
                        f"doc claims {claimed_handlers} handlers across "
                        f"{claimed_events} event types; the generated registry has "
                        f"{truth.handler_count} across {truth.event_type_count}"
                    ),
                    remediation=_REMEDIATION_COUNT_DRIFT,
                )
            )

    qa_claim = _QA_COUNT_RE.search(line)
    if qa_claim is not None:
        violations.append(
            Violation(
                rule=RULE_QA_COUNT,
                file=rel_file,
                line=line_no,
                message=(f"prose hardcodes the QA suite size as {qa_claim.group('count')} checks"),
                remediation=_REMEDIATION_QA_COUNT,
            )
        )
    return violations


def scan(root: Path) -> list[Violation]:
    """Check every configured doc against the generated registry."""
    truth = parse_generated_truth(root.joinpath(*_GENERATED_DOC_PARTS))
    violations: list[Violation] = []

    for rel_file in _CHECKED_DOCS:
        doc_path = root / rel_file
        if not doc_path.is_file():
            continue
        for line_no, line in enumerate(doc_path.read_text(encoding="utf-8").splitlines(), 1):
            violations.extend(_check_bullet(rel_file, line_no, line, truth))
            violations.extend(_check_counts(rel_file, line_no, line, truth))
    return violations


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        violations = scan(root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "tool": _TOOL_NAME,
        "summary": {
            "passed": not violations,
            "total_violations": len(violations),
            "by_rule": {
                rule: sum(1 for v in violations if v.rule == rule)
                for rule in (
                    RULE_REF_UNKNOWN,
                    RULE_CLAIM_MISMATCH,
                    RULE_COUNT_DRIFT,
                    RULE_QA_COUNT,
                )
            },
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
        print(f"Found {len(violations)} doc-truth violation(s):")
        for violation in violations:
            print(f"  [{violation.rule}] {violation.file}:{violation.line}: {violation.message}")
            print(f"    Fix: {violation.remediation}")
    else:
        print("No doc-truth violations found")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
