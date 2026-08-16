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

``handler-count-unverifiable``
    A prose "N production handlers" claim. No artifact substantiates it:
    ``.claude/HOOKS-DAEMON.md`` is titled **Active Configuration** and counts
    what is enabled IN THIS PROJECT — including project-local and plugin
    handlers a client never receives, and counting a handler registered on two
    events twice. Validating the claim against that total would assert
    agreement between two artifacts sharing one overcount: circular
    consistency, not truth, and precisely what this check exists to prevent.
    The number is genuinely ambiguous — 87, 89, 90 and 92 are each defensible
    depending on whether you count registrations or classes, and whether
    repo-local handlers are included. So the fix is to stop asserting one.

``qa-check-count-hardcoded``
    Same treatment for the size of the QA suite, for the same reason.

If ``generate-docs`` ever emits a SHIPPED-inventory figure distinct from the
active one, ``handler-count-unverifiable`` can become an equality assertion
against that — real ground truth rather than a restatement of the claim.

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
import subprocess  # nosec B404 - runs the daemon's own CLI to read its registry
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
RULE_COUNT_UNVERIFIABLE: Final[str] = "handler-count-unverifiable"
RULE_QA_COUNT: Final[str] = "qa-check-count-hardcoded"
RULE_CLI_SUBCOMMAND_UNKNOWN: Final[str] = "cli-subcommand-unknown"

# Fence info strings that assert "this block is runnable shell". A command
# inside one is a command; the same words in prose are a mention. The tag is
# the discriminator, NOT the fence: `CLAUDE/AgentTeam.md` keeps agent-prompt
# templates — English prose — inside UNTAGGED ``` fences, and one of them reads
# "Run the daemon CLI as ./bin/hooks-daemon from inside that worktree", which a
# fence-only rule reads as a subcommand named `from` at seven sites.
_SHELL_FENCE_TAGS: Final[frozenset[str]] = frozenset({"bash", "sh", "shell", "console", "zsh"})

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*```(?P<tag>[A-Za-z0-9_+-]*)")

# A path-form wrapper invocation: `bin/hooks-daemon <subcommand>`. Requiring the
# `bin/` segment is what separates the WRAPPER from the SKILL: `/hooks-daemon
# upgrade` is a valid slash-command that 38 release notes use correctly, and
# must never be flagged. Only the wrapper reaches argparse.
_CLI_INVOCATION_RE: Final[re.Pattern[str]] = re.compile(
    r"bin/hooks-daemon\s+(?P<sub>[a-z][a-z0-9-]*)"
)

# Directories whose markdown is not this project's documentation.
_UNSCANNED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {".git", "node_modules", "untracked", "__pycache__", ".venv", "vendor"}
)

_MARKDOWN_GLOB: Final[str] = "*.md"

# Asking the live parser rather than restating it. `--help` renders the
# subcommand registry as argparse's usage brace group.
_HELP_ARGS: Final[tuple[str, ...]] = ("-m", "claude_code_hooks_daemon.daemon.cli", "--help")
_HELP_TIMEOUT_SECONDS: Final[int] = 60
_USAGE_CHOICES_RE: Final[re.Pattern[str]] = re.compile(r"\{(?P<choices>[a-z][a-z0-9,-]+)\}")
_CHOICE_SEPARATOR: Final[str] = ","

# A generated table row: | priority | handler | BEHAVIOR | description |
_GENERATED_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*\|\s*(?P<behavior>[A-Z-]+)\s*\|"
)
# A doc bullet that opts in by naming its handler key in backticks.
_BULLET_RE: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\*\*(?P<name>[^*]+)\*\*\s*\(`(?P<key>[a-z][a-z0-9_]*)`\)\s*[—-]\s*(?P<desc>.+)$"
)

# "92 production handlers", with or without a trailing "across N event types".
_COUNT_CLAIM_RE: Final[re.Pattern[str]] = re.compile(r"(?P<handlers>\d+)\s+production handlers?")

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
_REMEDIATION_COUNT_UNVERIFIABLE: Final[str] = (
    "Drop the number. No artifact substantiates a 'ships with N handlers' claim: "
    ".claude/HOOKS-DAEMON.md is titled 'Active Configuration' and counts what is "
    "ENABLED IN THIS PROJECT — including project-local and plugin handlers a client "
    "never receives, and counting a handler registered on two events twice. Say "
    "'a large library of production handlers' and point at the generated doc. If "
    "generate-docs later emits a SHIPPED-inventory figure distinct from the active "
    "one, this rule can become an equality assertion against that."
)
_REMEDIATION_QA_COUNT: Final[str] = (
    "Do not hardcode the size of the QA suite — there is no generated ground "
    "truth for it, so the number drifts silently. Say 'all checks in the QA "
    "suite' instead."
)

_REMEDIATION_CLI_UNKNOWN: Final[str] = (
    "Use a subcommand the CLI actually has, or the skill form. Upgrading is "
    "'/hooks-daemon upgrade' (the skill) — NOT a wrapper subcommand; the "
    "wrapper exits 2 on it."
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
    """Per-handler behaviours parsed from the generated doc.

    Deliberately carries NO totals. The generated doc is titled "Active
    Configuration": its counts describe what is ENABLED IN THIS PROJECT, which
    is a different claim from what the daemon ships. Its totals also include
    project-local and plugin handlers a client never receives, and count a
    handler registered on two events twice. Parsing a total here and comparing
    it to a "ships with N" claim would assert agreement between two artifacts
    sharing one overcount — circular consistency, not truth.

    Per-handler BEHAVIOUR is unaffected by any of that, so it stays.
    """

    behaviours: dict[str, str] = field(default_factory=dict)


def parse_generated_truth(path: Path) -> GeneratedTruth:
    """Parse ``.claude/HOOKS-DAEMON.md`` into per-handler behaviours.

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


def _check_counts(rel_file: str, line_no: int, line: str) -> list[Violation]:
    violations: list[Violation] = []

    count_claim = _COUNT_CLAIM_RE.search(line)
    if count_claim is not None:
        violations.append(
            Violation(
                rule=RULE_COUNT_UNVERIFIABLE,
                file=rel_file,
                line=line_no,
                message=(
                    f"prose asserts {count_claim.group('handlers')} production handlers; "
                    "no artifact substantiates a shipped-handler count"
                ),
                remediation=_REMEDIATION_COUNT_UNVERIFIABLE,
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


def live_cli_subcommands() -> frozenset[str]:
    """Return the daemon CLI's subcommand registry, read from the live parser.

    The parser is built inline inside ``cli.main()`` with nothing importable to
    introspect, so the registry is obtained by asking the CLI to render itself
    and reading argparse's usage brace group. That is the live parser speaking
    — a restated tuple here would be exactly the drift this module exists to
    catch.

    Raises:
        FileNotFoundError: when the registry cannot be read. FAIL FAST: a guard
            that silently fell back to "no known subcommands" would pass every
            document while checking nothing, which is the failure mode this
            whole check was written against.
    """
    result = subprocess.run(  # nosec B603 - fixed argv, no shell, no user input
        [sys.executable, *_HELP_ARGS],
        capture_output=True,
        text=True,
        timeout=_HELP_TIMEOUT_SECONDS,
        check=False,
    )
    match = _USAGE_CHOICES_RE.search(result.stdout)
    if match is None:
        raise FileNotFoundError(
            "could not read the daemon CLI subcommand registry from "
            f"`{sys.executable} {' '.join(_HELP_ARGS)}` (rc={result.returncode}). "
            f"stderr: {result.stderr[:300]}"
        )
    return frozenset(match.group("choices").split(_CHOICE_SEPARATOR))


def _iter_markdown(root: Path) -> list[Path]:
    """Every documentation markdown file under ``root``, noise directories aside."""
    return sorted(
        path
        for path in root.rglob(_MARKDOWN_GLOB)
        if not _UNSCANNED_DIR_NAMES.intersection(path.parts)
    )


def _check_cli_invocations(root: Path, subcommands: frozenset[str]) -> list[Violation]:
    """Flag wrapper invocations naming a subcommand the CLI does not have.

    Only shell-tagged fences are scanned — see ``_SHELL_FENCE_TAGS`` for why the
    tag, and not the fence, is the discriminator.
    """
    violations: list[Violation] = []
    for path in _iter_markdown(root):
        rel_file = path.relative_to(root).as_posix()
        fence_tag: str | None = None
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            fence = _FENCE_RE.match(line)
            if fence is not None:
                fence_tag = None if fence_tag is not None else fence.group("tag").lower()
                continue
            if fence_tag not in _SHELL_FENCE_TAGS:
                continue
            for found in _CLI_INVOCATION_RE.finditer(line):
                subcommand = found.group("sub")
                if subcommand in subcommands:
                    continue
                violations.append(
                    Violation(
                        rule=RULE_CLI_SUBCOMMAND_UNKNOWN,
                        file=rel_file,
                        line=line_no,
                        message=(
                            f"`hooks-daemon {subcommand}` is not a CLI subcommand; "
                            "the wrapper rejects it with exit 2"
                        ),
                        remediation=_REMEDIATION_CLI_UNKNOWN,
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
            violations.extend(_check_counts(rel_file, line_no, line))

    # Applied to EVERY tracked document, not just `_CHECKED_DOCS`. A handler
    # behaviour claim was true when it was written and archived notes should not
    # be re-litigated; a command either runs or it does not, whenever it was
    # written, and a reader will paste it either way.
    violations.extend(_check_cli_invocations(root, live_cli_subcommands()))
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
                    RULE_COUNT_UNVERIFIABLE,
                    RULE_QA_COUNT,
                    RULE_CLI_SUBCOMMAND_UNKNOWN,
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
