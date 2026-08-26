#!/usr/bin/env python3
"""Hook INPUT-contract drift check — the daemon's read surface vs the vendored examples.

Plan 00273 (follow-up to Plan 00271, which covered the RESPONSE side). Handlers
and the shared ``utils/`` helpers read hook_input fields ad hoc, so a renamed
or restructured input field would surface only as handlers silently never
matching. This check derives the top-level read surface by AST scan and applies
the plan's Technical Decision 1 SUPERSET rule against each event's vendored
``input_example`` (``contracts/claude-code-hooks/*.json``), NETWORK-FREE:

``unknown-input-field``         the daemon reads a top-level hook_input field
                                that appears in NO vendored input example for
                                that event — the rename signal. Absence (the
                                example carrying fields the daemon never
                                reads) is NEVER flagged: examples are not
                                schemas and several fields are conditional.
``stale-allowlist-entry``       an INPUT-ALLOWLIST.yaml entry whose finding no
                                longer exists.
``malformed-allowlist-entry``   an allowlist entry missing its reason or link.

Scope (by construction, per the plan's Non-Goals):

- StatusLine and the ``nitpick`` pseudo-event are out-of-contract and never
  scanned.
- Nested ``tool_input`` keys are NOT validated — the examples carry one tool's
  shape only, so there is no substrate; only the top-level ``tool_input`` read
  is recorded. The known gap is on record in the plan's INVENTORY.md.
- Shared helpers (``utils/`` and ``handlers/utils``) serve many events, so
  their reads are checked against the UNION of all input examples.

The checker primitive (``collect_read_surface`` + ``check_read_surface``) is
deliberately importable and root-parameterised so ``validate-project-handlers``
can reuse it for client project handlers later (recorded follow-up gap).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
_SRC_PACKAGE_PARTS: Final[tuple[str, str]] = ("src", "claude_code_hooks_daemon")
_CONTRACTS_DIR_PARTS: Final[tuple[str, str]] = ("contracts", "claude-code-hooks")
_META_FILENAME: Final[str] = "META.json"
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "input_contract.json"

INPUT_ALLOWLIST_FILENAME: Final[str] = "INPUT-ALLOWLIST.yaml"

_HANDLERS_DIR_NAME: Final[str] = "handlers"
_UTILS_DIR_NAME: Final[str] = "utils"
_CONSTANTS_PROTOCOL_PARTS: Final[tuple[str, str]] = ("constants", "protocol.py")
_HOOK_INPUT_FIELD_CLASS: Final[str] = "HookInputField"
_HOOK_INPUT_VARIABLE: Final[str] = "hook_input"
_GET_METHOD: Final[str] = "get"
_INPUT_EXAMPLE_KEY: Final[str] = "input_example"
_EVENT_KEY: Final[str] = "event"

#: Handler packages excluded from the scan by construction: StatusLine is a
#: separate Claude Code feature with its own contract; ``nitpick`` is a daemon
#: pseudo-event; ``utils`` under handlers/ is a shared surface (scanned as
#: SHARED, not as an event package).
_EXCLUDED_HANDLER_PACKAGES: Final[frozenset[str]] = frozenset(
    {"status_line", "nitpick", "__pycache__"}
)
_SHARED_HANDLER_PACKAGES: Final[frozenset[str]] = frozenset({_UTILS_DIR_NAME})

#: Sentinel event key for reads made by shared helpers on many events' behalf.
SHARED_SURFACE: Final[str] = "(shared)"

# Rule names.
RULE_UNKNOWN_INPUT_FIELD: Final[str] = "unknown-input-field"
RULE_STALE_ALLOWLIST: Final[str] = "stale-allowlist-entry"
RULE_MALFORMED_ALLOWLIST: Final[str] = "malformed-allowlist-entry"


@dataclass
class Finding:
    """One input-contract drift, identified stably for allowlisting."""

    rule: str
    event: str
    subject: str
    message: str

    @property
    def finding_id(self) -> str:
        return f"{self.rule}:{self.event}:{self.subject}"

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.finding_id,
            "rule": self.rule,
            "event": self.event,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass
class Report:
    """Full check result: live violations plus recorded allowlisted gaps."""

    violations: list[Finding] = field(default_factory=list)
    allowlisted: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "passed": self.passed,
                "total_violations": len(self.violations),
                "allowlisted": len(self.allowlisted),
            },
            "violations": [v.to_dict() for v in self.violations],
            "allowlisted": self.allowlisted,
        }


def load_field_constants(src_dir: Path) -> dict[str, str]:
    """Map ``HookInputField`` attribute names to their string values.

    An absent or unparsable ``constants/protocol.py`` yields an empty map —
    the string-literal branch of the scan still works.
    """
    path = src_dir.joinpath(*_CONSTANTS_PROTOCOL_PARTS)
    if not path.is_file():
        return {}
    constants: dict[str, str] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == _HOOK_INPUT_FIELD_CLASS):
            continue
        for statement in node.body:
            if not (
                isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = statement.value.value
    return constants


def _resolve_key(node: ast.expr, constants: dict[str, str]) -> str | None:
    """Resolve a key expression to a field name: a string literal, or a
    ``HookInputField.X`` attribute looked up in the constants map."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr in constants:
        return constants[node.attr]
    return None


def collect_reads_from_source(source: str, constants: dict[str, str]) -> set[str]:
    """Top-level hook_input field names a module reads.

    Detected shapes: ``hook_input.get(<key>[, default])`` and
    ``hook_input[<key>]`` where ``<key>`` is a string literal or a
    ``HookInputField`` attribute. Nested reads chain off the returned value,
    so only the top-level key is ever recorded.
    """
    reads: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == _GET_METHOD
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == _HOOK_INPUT_VARIABLE
            and node.args
        ):
            key = _resolve_key(node.args[0], constants)
            if key is not None:
                reads.add(key)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == _HOOK_INPUT_VARIABLE
        ):
            key = _resolve_key(node.slice, constants)
            if key is not None:
                reads.add(key)
    return reads


def package_to_event(package_name: str) -> str:
    """``pre_tool_use`` -> ``PreToolUse`` (handler package dir to event name)."""
    return "".join(part.capitalize() for part in package_name.split("_"))


def _reads_under(directory: Path, constants: dict[str, str]) -> set[str]:
    reads: set[str] = set()
    for path in sorted(directory.rglob("*.py")):
        reads |= collect_reads_from_source(path.read_text(encoding="utf-8"), constants)
    return reads


def collect_read_surface(root: Path) -> dict[str, set[str]]:
    """Per-event read surface across handler packages plus SHARED helpers.

    Handler event packages map to their event name; ``utils/`` (top-level and
    under ``handlers/``) is aggregated under :data:`SHARED_SURFACE`. Excluded
    by construction: StatusLine and the nitpick pseudo-event.
    """
    src_dir = root.joinpath(*_SRC_PACKAGE_PARTS)
    constants = load_field_constants(src_dir)
    surface: dict[str, set[str]] = {}
    shared: set[str] = set()

    handlers_dir = src_dir / _HANDLERS_DIR_NAME
    if handlers_dir.is_dir():
        for package in sorted(handlers_dir.iterdir()):
            if not package.is_dir() or package.name in _EXCLUDED_HANDLER_PACKAGES:
                continue
            if package.name in _SHARED_HANDLER_PACKAGES:
                shared |= _reads_under(package, constants)
                continue
            reads = _reads_under(package, constants)
            if reads:
                surface[package_to_event(package.name)] = reads

    utils_dir = src_dir / _UTILS_DIR_NAME
    if utils_dir.is_dir():
        shared |= _reads_under(utils_dir, constants)
    if shared:
        surface[SHARED_SURFACE] = shared
    return surface


def load_input_examples(contracts_dir: Path) -> dict[str, set[str]]:
    """Top-level keys of every vendored per-event ``input_example``.

    Raises:
        FileNotFoundError: when the vendored contract directory is absent —
            FAIL FAST, an input check with no examples verifies nothing.
    """
    if not contracts_dir.is_dir():
        raise FileNotFoundError(f"vendored contract directory missing: {contracts_dir}")
    examples: dict[str, set[str]] = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == _META_FILENAME:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        examples[data[_EVENT_KEY]] = set(data.get(_INPUT_EXAMPLE_KEY) or {})
    return examples


def check_read_surface(
    read_surface: dict[str, set[str]], examples: dict[str, set[str]]
) -> list[Finding]:
    """Apply the SUPERSET rule (Plan 00273 Technical Decision 1).

    A field an event's handlers read that appears in NO vendored example for
    that event is flagged; absence is never flagged. SHARED reads are checked
    against the union of all examples. An event with no (or an empty) example
    has no substrate and is skipped entirely.
    """
    union: set[str] = set().union(*examples.values()) if examples else set()
    findings: list[Finding] = []
    for event, reads in sorted(read_surface.items()):
        if event == SHARED_SURFACE:
            known = union
            scope = "any vendored input example"
        else:
            known = examples.get(event, set())
            if not known:
                continue
            scope = f"the vendored {event} input example"
        for name in sorted(reads - known):
            findings.append(
                Finding(
                    rule=RULE_UNKNOWN_INPUT_FIELD,
                    event=event,
                    subject=name,
                    message=(
                        f"the daemon reads top-level hook_input field '{name}' "
                        f"({event}), which appears in {scope} nowhere — "
                        f"possible upstream rename or a stale read"
                    ),
                )
            )
    return findings


def load_allowlist(contracts_dir: Path) -> list[dict[str, Any]]:
    """Load INPUT-ALLOWLIST.yaml entries; an absent file is an empty allowlist."""
    path = contracts_dir / INPUT_ALLOWLIST_FILENAME
    if not path.is_file():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("entries", [])
    return list(entries) if isinstance(entries, list) else []


def apply_allowlist(
    findings: list[Finding], entries: list[dict[str, Any]]
) -> tuple[list[Finding], list[dict[str, Any]], list[Finding]]:
    """Split findings into (remaining, allowlisted) and validate the allowlist.

    A stale entry (no matching finding) and a malformed entry (missing reason
    or link) are themselves violations — a stale allowlist rots exactly like a
    stale schema (Plan 00271 Decision 2, carried over).
    """
    remaining = {f.finding_id: f for f in findings}
    allowlisted: list[dict[str, Any]] = []
    problems: list[Finding] = []
    for entry in entries:
        entry_id = str(entry.get("id", ""))
        reason = entry.get("reason")
        link = entry.get("link")
        if not entry_id or not reason or not link:
            problems.append(
                Finding(
                    rule=RULE_MALFORMED_ALLOWLIST,
                    event="-",
                    subject=entry_id or "(missing id)",
                    message=(
                        f"allowlist entry must carry id, reason and a linked plan/task; got: {entry}"
                    ),
                )
            )
            continue
        matched = remaining.pop(entry_id, None)
        if matched is None:
            problems.append(
                Finding(
                    rule=RULE_STALE_ALLOWLIST,
                    event="-",
                    subject=entry_id,
                    message=(
                        f"allowlist entry '{entry_id}' matches no current finding — "
                        f"the drift it recorded no longer exists; delete the entry"
                    ),
                )
            )
            continue
        allowlisted.append({**matched.to_dict(), "reason": reason, "link": link})
    return list(remaining.values()), allowlisted, problems


def scan(root: Path) -> Report:
    """Run the input-contract check against the tree at ``root``."""
    contracts_dir = root.joinpath(*_CONTRACTS_DIR_PARTS)
    examples = load_input_examples(contracts_dir)
    read_surface = collect_read_surface(root)
    findings = check_read_surface(read_surface, examples)
    remaining, allowlisted, problems = apply_allowlist(findings, load_allowlist(contracts_dir))
    return Report(violations=remaining + problems, allowlisted=allowlisted)


def _render_inventory(read_surface: dict[str, set[str]]) -> str:
    lines = ["Top-level hook_input read surface (per event; nested keys not recorded):"]
    for event, reads in sorted(read_surface.items()):
        lines.append(f"  {event}: {', '.join(sorted(reads))}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hook input-contract drift check (Plan 00273)")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="print the derived read surface (for contract-refresh re-triage)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    try:
        report = scan(root)
    except (FileNotFoundError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.inventory:
        print(_render_inventory(collect_read_surface(root)))

    payload = report.to_dict()
    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif report.violations:
        print(f"Found {len(report.violations)} input-contract violation(s):")
        for violation in report.violations:
            print(f"  [{violation.rule}] {violation.event}: {violation.message}")
    else:
        print(
            f"No input-contract violations ({len(report.allowlisted)} recorded "
            f"allowlisted gap(s))"
        )
    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
