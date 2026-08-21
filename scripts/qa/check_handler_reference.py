#!/usr/bin/env python3
"""Handler-reference truth check — the options doc must agree with the code.

Built under DBF (``CLAUDE.md`` Core Standard 15). ``docs/CLAUDE.md`` names
``docs/guides/HANDLER_REFERENCE.md`` the canonical source for per-handler
options, values and defaults. It had drifted badly, and the drift was the
*symptom*: the real defect was that **nothing could see it**.

What had rotted, undetected:

- FIVE ``#### <name>`` sections documented handlers that do not exist —
  ``python_qa_suppression_blocker``, ``php_qa_suppression_blocker``,
  ``go_qa_suppression_blocker`` and ``eslint_disable`` (all collapsed long ago
  into the single ``qa_suppression`` handler), plus ``stats_cache_reader``,
  which is a helper MODULE and never was a handler. Each shipped a
  copy-pasteable YAML block that hard-fails config validation with
  ``Unknown handler '...'`` (``config/validator.py``).
- Around thirty documented priorities contradicted ``constants/priority.py``.
  ``sed_blocker`` contradicted *itself*: heading 10, own snippet 11.
- Eight PreToolUse BLOCKING handlers had no section at all. A blocking handler
  nobody documented is one a user cannot diagnose when it fires.

Ground truth is the CODE, never another document:

``handler ids``
    ``constants/handlers.py`` (via ``scripts/audit_handler_config_keys.py`` —
    reused, not reimplemented, so both surfaces agree about what a config key
    is) UNION the class names the live ``HandlerRegistry`` discovers. The union
    matters because a handler can ship with no ``HandlerID`` entry, and
    ``HandlerID`` alone would then flag it as a phantom.

``priorities``
    ``constants/priority.py``, which that module's own docstring declares the
    "Single source of truth for all handler priorities". A handler whose
    priority bypasses it (``worktree_create`` uses a module-local constant)
    yields ``priority-unresolvable`` rather than a silent skip — a guard that
    quietly checks nothing is exactly what this check exists to prevent.

The ONE rule that consults a generated document rather than code is
``undocumented-blocking-handler``, which reads ``.claude/HOOKS-DAEMON.md`` (the
``generate-docs`` artifact, the same ground truth ``check_doc_truth.py`` uses).
Its known limitation is inherited: that file is titled "Active Configuration",
so a handler DISABLED in this project is not required to be documented. The
rule is therefore a floor, not a ceiling.

``example-config-phantom-handler`` covers the SECOND copy-pasteable surface,
``.claude/hooks-daemon.yaml.example``. The guard originally saw only the
reference doc, and the template a new project starts from had meanwhile
accumulated FIFTEEN entries for handlers that no longer exist. That surface is
the more dangerous of the two, and it splits into two failure modes:

- A name in ``RETIRED_HANDLERS`` is deliberately EXEMPTED from
  ``config/validator.py``'s unknown-handler error (Plan 00233: retiring a
  handler upstream must not break a client's existing config). So copying such
  a block yields no error, no handler, and the belief that a protection is
  running — silent false assurance.
- A name that was never retired at all (five of the fifteen) hits the hard
  ``Unknown handler`` error instead, so the shipped template does not validate.

Finding ten by hand and fifteen with the guard is the whole argument for
writing the guard.

Deliberately NOT checked: prose accuracy, option tables, descriptions, and
retired names appearing in ``CHANGELOG.md``, ``RELEASES/``, ``CLAUDE/UPGRADES/``
or ``CLAUDE/Plan/`` — those SHOULD name them, because that is the record of the
removal. Judgement cases, and a gate that guesses gets switched off.

Usage:
    python scripts/qa/check_handler_reference.py [--json] [--root DIR] [--report-stdout]

Exit codes:
    0 - No violations found
    1 - Violations found
    2 - Operational failure (reference doc or generated truth missing/unreadable)
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
_SRC_DIR_NAME: Final[str] = "src"
_SCRIPTS_DIR_NAME: Final[str] = "scripts"

_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "handler_reference.json"
_TOOL_NAME: Final[str] = "handler_reference"

# The doc under audit, and the generated registry the coverage rule reads.
_REFERENCE_DOC_PARTS: Final[tuple[str, str, str]] = ("docs", "guides", "HANDLER_REFERENCE.md")
_GENERATED_DOC_PARTS: Final[tuple[str, str]] = (".claude", "HOOKS-DAEMON.md")

# The SECOND copy-pasteable surface. Optional: a project need not ship one, so
# its absence is not drift (unlike the reference doc, which is this check's
# whole subject and whose absence is an operational failure).
_EXAMPLE_CONFIG_PARTS: Final[tuple[str, str]] = (".claude", "hooks-daemon.yaml.example")

RULE_REF_UNKNOWN: Final[str] = "handler-ref-unknown"
RULE_PRIORITY_MISMATCH: Final[str] = "priority-mismatch"
RULE_PRIORITY_UNRESOLVABLE: Final[str] = "priority-unresolvable"
RULE_CONFIG_KEY_MISMATCH: Final[str] = "config-key-mismatch"
RULE_UNDOCUMENTED_BLOCKER: Final[str] = "undocumented-blocking-handler"
RULE_EXAMPLE_CONFIG_PHANTOM: Final[str] = "example-config-phantom-handler"

_ALL_RULES: Final[tuple[str, ...]] = (
    RULE_REF_UNKNOWN,
    RULE_PRIORITY_MISMATCH,
    RULE_PRIORITY_UNRESOLVABLE,
    RULE_CONFIG_KEY_MISMATCH,
    RULE_UNDOCUMENTED_BLOCKER,
    RULE_EXAMPLE_CONFIG_PHANTOM,
)

# Handlers whose ``Priority`` constant is NOT simply the uppercased config key.
# Kept explicit rather than fuzzy-matched: a near-miss guess would silently
# compare a documented priority against the wrong constant, which is worse than
# reporting that no constant could be resolved.
_PRIORITY_ATTR_ALIASES: Final[dict[str, str]] = {
    "cleanup": "SESSION_CLEANUP",
    "suggest_status_line": "SUGGEST_STATUSLINE",
    "dismissive_language_nitpick": "NITPICK_DISMISSIVE",
    "hedging_language_nitpick": "NITPICK_HEDGING",
    "hello_world_notification": "HELLO_WORLD",
    "hello_world_permission_request": "HELLO_WORLD",
    "hello_world_post_tool_use": "HELLO_WORLD",
    "hello_world_pre_compact": "HELLO_WORLD",
    "hello_world_pre_tool_use": "HELLO_WORLD",
    "hello_world_session_end": "HELLO_WORLD",
    "hello_world_session_start": "HELLO_WORLD",
    "hello_world_stop": "HELLO_WORLD",
    "hello_world_subagent_stop": "HELLO_WORLD",
    "hello_world_user_prompt_submit": "HELLO_WORLD",
}

# Event column values accepted in a Quick Reference row. Named exhaustively so
# an ``Options:`` table row (``| `max_archives` | int | `40` | ... |``) can
# never be mistaken for a handler summary row.
_EVENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "SessionEnd",
        "PreCompact",
        "PostCompact",
        "UserPromptSubmit",
        "PermissionRequest",
        "Notification",
        "Stop",
        "SubagentStop",
        "StatusLine",
        "WorktreeCreate",
        "WorktreeRemove",
    }
)

# The generated event section whose blocking handlers MUST be documented.
# Scoped to PreToolUse on purpose: those are the handlers that deny a user's
# own tool call, so they are the ones a user needs the reference to diagnose.
_COVERED_EVENT: Final[str] = "PreToolUse"

# Generated ``Behavior`` column values that genuinely stop a tool call.
_BLOCKING_BEHAVIOURS: Final[frozenset[str]] = frozenset({"BLOCKING", "TERMINAL"})

# ── Reference-doc grammar ──────────────────────────────────────────
# A per-handler section heading: `#### handler_key`.
_SECTION_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^####\s+(?P<key>[a-z][a-z0-9_]*)\s*$")
# Any markdown heading — used to close the current section.
_ANY_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s+\S")
# `| **Config key** | `handler_key` |`
_CONFIG_KEY_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\*\*Config key\*\*\s*\|\s*`(?P<key>[^`]+)`\s*\|"
)
# `| **Priority**   | 10 |`
_PRIORITY_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\*\*Priority\*\*\s*\|\s*(?P<priority>\d+)\s*\|"
)
# A `priority: N` line inside a section's YAML config example.
_YAML_PRIORITY_RE: Final[re.Pattern[str]] = re.compile(r"^\s+priority:\s*(?P<priority>\d+)\s*$")
# A Quick Reference row: `| `key` | Event | Priority | text |`
_QUICK_REF_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*`(?P<key>[a-z][a-z0-9_]*)`\s*\|\s*(?P<event>[A-Za-z]+)\s*\|\s*(?P<priority>\d+)\s*\|"
)

# ── Generated-registry grammar ─────────────────────────────────────
# ── Example-config grammar ─────────────────────────────────────────
# The block whose children are event sections, and the two indent levels below
# it. A key at the handler indent is a handler name; `options:` sits deeper and
# an event sits shallower, so neither can be mistaken for one.
_HANDLERS_BLOCK_KEY: Final[str] = "handlers:"
_TOP_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*:")
_HANDLER_ENTRY_RE: Final[re.Pattern[str]] = re.compile(r"^ {4}(?P<key>[a-z][a-z0-9_]*):(?:\s|$)")

_GENERATED_EVENT_RE: Final[re.Pattern[str]] = re.compile(r"^###\s+(?P<event>[A-Za-z]+)\b")
_GENERATED_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<handler>[a-z][a-z0-9_]*)\s*\|\s*(?P<behavior>[A-Z-]+)\s*\|"
)

_REMEDIATION_REF_UNKNOWN: Final[str] = (
    "No such handler. Delete the section (or correct the key) — a documented "
    "handler that does not exist ships a YAML snippet that hard-fails config "
    "validation with \"Unknown handler '...'\". Real keys come from "
    "constants/handlers.py and the handler registry; `hooks-daemon generate-docs` "
    "lists the ones active in a project."
)
_REMEDIATION_PRIORITY_MISMATCH: Final[str] = (
    "Correct the documented number to match constants/priority.py, which that "
    "module declares the single source of truth for handler priorities. The "
    "documented value is the SHIPPED DEFAULT; a project's own config may "
    "override it, and a project override is never a reason to edit this doc."
)
_REMEDIATION_PRIORITY_UNRESOLVABLE: Final[str] = (
    "This handler's priority is not declared in constants/priority.py, so the "
    "documented number cannot be verified. Add a Priority constant for the "
    "handler and use it in its __init__ (preferred), or drop the Priority row "
    "from the section rather than asserting an unverifiable number."
)
_REMEDIATION_CONFIG_KEY_MISMATCH: Final[str] = (
    "The section heading and its **Config key** row must name the SAME key — "
    "readers copy the row, not the heading. Make them agree."
)
_REMEDIATION_EXAMPLE_CONFIG_PHANTOM: Final[str] = (
    "Delete this key from the example config. It names a handler that no longer "
    "exists, and `config/validator.py` deliberately EXEMPTS retired names from "
    "its unknown-handler error (Plan 00233), so a user who copies this block "
    "gets no error, no handler, and the belief that a protection is running. "
    "Retirements reach existing installs through the upgrade manifests; the "
    "example config is a fresh start and must name only live handlers."
)

_REMEDIATION_UNDOCUMENTED_BLOCKER: Final[str] = (
    "Add a `#### <key>` section for this handler. A blocking handler with no "
    "entry in the canonical reference is one a user cannot diagnose when it "
    "denies their tool call."
)


@dataclass(frozen=True)
class Violation:
    """One documented claim contradicted by the handler code."""

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


@dataclass(frozen=True)
class GroundTruth:
    """Handler facts read from the code, never from another document."""

    handler_keys: frozenset[str]
    priorities: dict[str, int]


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
                "by_rule": {
                    rule: sum(1 for v in self.violations if v.rule == rule) for rule in _ALL_RULES
                },
            },
            "violations": [v.to_dict() for v in self.violations],
        }


def load_ground_truth() -> GroundTruth:
    """Handler keys and shipped priorities, read from this checkout's code.

    Imports are deliberately function-local: the daemon package and the audit
    script both live outside ``scripts/qa``, so ``sys.path`` has to be primed
    first, and doing that at module scope would put imports below statements.

    Raises:
        ImportError: when the daemon package or the audit script cannot be
            imported. FAIL FAST — a reference check that cannot read the code
            would report "clean" while verifying nothing.
    """
    for directory in (_PROJECT_ROOT / _SRC_DIR_NAME, _PROJECT_ROOT / _SCRIPTS_DIR_NAME):
        entry = str(directory)
        if entry not in sys.path:
            sys.path.insert(0, entry)

    from audit_handler_config_keys import audit_handler_keys, to_snake_case

    from claude_code_hooks_daemon.constants.priority import Priority
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

    keys: set[str] = set()

    # Source 1 — the declared HandlerID constants. Both the constant's own
    # config_key and the key the registry auto-generates from the class name
    # count as real: `audit_handler_config_keys` exists precisely because those
    # two can disagree, and a reader may legitimately have seen either.
    audit = audit_handler_keys()
    for bucket in audit.values():
        for info in bucket.values():
            keys.add(info["constant"])
            keys.add(info["auto_generated"])

    # Source 2 — every handler class the registry actually discovers. Catches
    # shipped handlers that have no HandlerID entry.
    registry = HandlerRegistry()
    registry.discover()
    for class_name in registry.list_handlers():
        keys.add(to_snake_case(class_name))

    priorities: dict[str, int] = {}
    for key in keys:
        attribute = _PRIORITY_ATTR_ALIASES.get(key, key.upper())
        value = getattr(Priority, attribute, None)
        if isinstance(value, int):
            priorities[key] = value

    return GroundTruth(handler_keys=frozenset(keys), priorities=priorities)


def parse_blocking_handlers(generated_doc: Path) -> frozenset[str]:
    """PreToolUse handlers the generated registry records as blocking.

    Raises:
        FileNotFoundError: when the generated doc is absent. FAIL FAST, for the
            same reason ``check_doc_truth.py`` does: a coverage rule with no
            inventory silently checks nothing.
    """
    if not generated_doc.is_file():
        raise FileNotFoundError(
            f"generated ground truth not found at {generated_doc}. "
            "Run `hooks-daemon generate-docs` to produce it."
        )

    blocking: set[str] = set()
    current_event: str | None = None
    for raw_line in generated_doc.read_text(encoding="utf-8").splitlines():
        event = _GENERATED_EVENT_RE.match(raw_line)
        if event is not None:
            current_event = event.group("event")
            continue
        if current_event != _COVERED_EVENT:
            continue
        row = _GENERATED_ROW_RE.match(raw_line)
        if row is not None and row.group("behavior") in _BLOCKING_BEHAVIOURS:
            blocking.add(row.group("handler"))
    return frozenset(blocking)


def _check_priority(
    rel_file: str,
    line_no: int,
    key: str,
    documented: int,
    truth: GroundTruth,
    where: str,
) -> list[Violation]:
    """Compare one documented priority against ``constants/priority.py``."""
    if key not in truth.priorities:
        return [
            Violation(
                rule=RULE_PRIORITY_UNRESOLVABLE,
                file=rel_file,
                line=line_no,
                message=(
                    f"{where} documents priority {documented} for `{key}`, but no "
                    "Priority constant declares it"
                ),
                remediation=_REMEDIATION_PRIORITY_UNRESOLVABLE,
            )
        ]
    actual = truth.priorities[key]
    if actual == documented:
        return []
    return [
        Violation(
            rule=RULE_PRIORITY_MISMATCH,
            file=rel_file,
            line=line_no,
            message=(
                f"{where} documents priority {documented} for `{key}`, "
                f"but constants/priority.py says {actual}"
            ),
            remediation=_REMEDIATION_PRIORITY_MISMATCH,
        )
    ]


def scan_reference_doc(doc_path: Path, rel_file: str, truth: GroundTruth) -> list[Violation]:
    """Check every handler claim in the reference doc against the code."""
    violations: list[Violation] = []
    current_key: str | None = None
    current_key_is_real = False

    for line_no, line in enumerate(doc_path.read_text(encoding="utf-8").splitlines(), 1):
        heading = _SECTION_HEADING_RE.match(line)
        if heading is not None:
            current_key = heading.group("key")
            current_key_is_real = current_key in truth.handler_keys
            if not current_key_is_real:
                violations.append(
                    Violation(
                        rule=RULE_REF_UNKNOWN,
                        file=rel_file,
                        line=line_no,
                        message=f"section documents handler `{current_key}`, which does not exist",
                        remediation=_REMEDIATION_REF_UNKNOWN,
                    )
                )
            continue

        if _ANY_HEADING_RE.match(line):
            # Any other heading closes the current handler section, so the rows
            # and snippets below it are never attributed to the wrong handler.
            current_key = None
            current_key_is_real = False

        quick_ref = _QUICK_REF_ROW_RE.match(line)
        if quick_ref is not None and quick_ref.group("event") in _EVENT_NAMES:
            key = quick_ref.group("key")
            if key not in truth.handler_keys:
                violations.append(
                    Violation(
                        rule=RULE_REF_UNKNOWN,
                        file=rel_file,
                        line=line_no,
                        message=(f"summary table lists handler `{key}`, which does not exist"),
                        remediation=_REMEDIATION_REF_UNKNOWN,
                    )
                )
            else:
                violations.extend(
                    _check_priority(
                        rel_file,
                        line_no,
                        key,
                        int(quick_ref.group("priority")),
                        truth,
                        "summary table",
                    )
                )
            continue

        if current_key is None:
            continue

        config_key_row = _CONFIG_KEY_ROW_RE.match(line)
        if config_key_row is not None:
            declared = config_key_row.group("key")
            if declared != current_key:
                violations.append(
                    Violation(
                        rule=RULE_CONFIG_KEY_MISMATCH,
                        file=rel_file,
                        line=line_no,
                        message=(f"section `{current_key}` declares config key `{declared}`"),
                        remediation=_REMEDIATION_CONFIG_KEY_MISMATCH,
                    )
                )
            continue

        if not current_key_is_real:
            # The heading was already reported; comparing its priority against
            # a handler that does not exist would only add noise.
            continue

        priority_row = _PRIORITY_ROW_RE.match(line)
        if priority_row is not None:
            violations.extend(
                _check_priority(
                    rel_file,
                    line_no,
                    current_key,
                    int(priority_row.group("priority")),
                    truth,
                    f"section `{current_key}`",
                )
            )
            continue

        yaml_priority = _YAML_PRIORITY_RE.match(line)
        if yaml_priority is not None:
            violations.extend(
                _check_priority(
                    rel_file,
                    line_no,
                    current_key,
                    int(yaml_priority.group("priority")),
                    truth,
                    f"config example under `{current_key}`",
                )
            )

    return violations


def documented_sections(doc_path: Path) -> frozenset[str]:
    """Every handler key that has its own `#### <key>` section."""
    keys: set[str] = set()
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        heading = _SECTION_HEADING_RE.match(line)
        if heading is not None:
            keys.add(heading.group("key"))
    return frozenset(keys)


def scan_example_config(config_path: Path, rel_file: str, truth: GroundTruth) -> list[Violation]:
    """Flag example-config handler keys that no handler answers to.

    Parsed by indentation rather than with a YAML loader on purpose: the file
    is a commented TEMPLATE, and the comments are half its value. A loader
    discards them, and round-tripping to report an accurate line number would
    mean depending on a comment-preserving parser for one check. Indentation is
    the grammar the file already commits to.

    Within the top-level ``handlers:`` block the nesting is fixed — event at
    one level, handler key at the next, ``options:`` below that — so a key at
    exactly the handler indent is unambiguous.
    """
    violations: list[Violation] = []
    in_handlers = False

    for number, raw_line in enumerate(config_path.read_text(encoding="utf-8").splitlines(), 1):
        if _TOP_LEVEL_KEY_RE.match(raw_line):
            in_handlers = raw_line.startswith(_HANDLERS_BLOCK_KEY)
            continue
        if not in_handlers:
            continue

        entry = _HANDLER_ENTRY_RE.match(raw_line)
        if entry is None or entry.group("key") in truth.handler_keys:
            continue

        violations.append(
            Violation(
                rule=RULE_EXAMPLE_CONFIG_PHANTOM,
                file=rel_file,
                line=number,
                message=(
                    f"example config offers `{entry.group('key')}`, which is not a "
                    "handler in this checkout"
                ),
                remediation=_REMEDIATION_EXAMPLE_CONFIG_PHANTOM,
            )
        )
    return violations


def scan(root: Path) -> Report:
    """Check ``root``'s handler reference against the handler code.

    Raises:
        FileNotFoundError: when the reference doc or the generated registry is
            missing.
        ImportError: when the handler code cannot be imported.
    """
    doc_path = root.joinpath(*_REFERENCE_DOC_PARTS)
    rel_file = "/".join(_REFERENCE_DOC_PARTS)
    if not doc_path.is_file():
        raise FileNotFoundError(
            f"handler reference not found at {doc_path}. There is nothing to check."
        )

    truth = load_ground_truth()
    report = Report()
    report.violations.extend(scan_reference_doc(doc_path, rel_file, truth))

    example_config = root.joinpath(*_EXAMPLE_CONFIG_PARTS)
    if example_config.is_file():
        report.violations.extend(
            scan_example_config(example_config, "/".join(_EXAMPLE_CONFIG_PARTS), truth)
        )

    blocking = parse_blocking_handlers(root.joinpath(*_GENERATED_DOC_PARTS))
    documented = documented_sections(doc_path)
    for key in sorted(blocking - documented):
        if key not in truth.handler_keys:
            continue
        report.violations.append(
            Violation(
                rule=RULE_UNDOCUMENTED_BLOCKER,
                file=rel_file,
                line=0,
                message=(
                    f"`{key}` is a {_COVERED_EVENT} blocking handler with no section "
                    "in the canonical handler reference"
                ),
                remediation=_REMEDIATION_UNDOCUMENTED_BLOCKER,
            )
        )
    return report


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
        report = scan(root)
    except (FileNotFoundError, ImportError) as exc:
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
        print(f"Found {len(report.violations)} handler-reference violation(s):")
        for violation in report.violations:
            print(f"  [{violation.rule}] {violation.file}:{violation.line}: {violation.message}")
            print(f"    Fix: {violation.remediation}")
    else:
        print("No handler-reference violations found")

    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
