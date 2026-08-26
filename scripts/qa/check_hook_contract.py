#!/usr/bin/env python3
"""Hook-contract drift check — daemon sources vs the vendored Claude Code contract.

Plan 00271 (DBF, Engineering Principle 15). The daemon's idea of the Claude
Code hooks contract lives in three places — ``core/response_schemas.py``,
``core/hook_result.py`` (``REFUSAL_CAPABLE_EVENTS`` + the serialisers) and
``constants/events.py`` (``can_block``) — and it rotted invisibly for many
Claude Code versions (21 drifts found by the Plan 00271 audit). This check
diffs all three against the tracked vendored contract under
``contracts/claude-code-hooks/`` on every QA run, NETWORK-FREE (Decision 4:
freshness of the vendored copy is the ``contract_staleness`` SessionStart
advisory's job, refreshed per ``docs/guides/HOOK-CONTRACT-REFRESH.md``).

Rules (each finding's id is ``rule:event:subject``):

``undocumented-schema-field``   a bespoke response schema accepts a field the
                                docs never define for that event.
``undocumented-enum-value``     a schema enum carries a value the docs never
                                define (e.g. PermissionRequest ``behavior: ask``).
``undocumented-claim``          ``REFUSAL_CAPABLE_EVENTS`` claims a decision the
                                docs do not document for the event.
``missing-refusal-claim``       the docs document blocking for the event, but
                                ``REFUSAL_CAPABLE_EVENTS`` omits it — a client
                                DENY there is silently dropped.
``capability-table-drift``      ``constants/events.py can_block`` disagrees with
                                the vendored contract.
``undocumented-emitted-token``  serialising a DENY on the event emits a
                                top-level ``decision`` token the docs never
                                define (the ``{"decision": "deny"}`` class).
``event-missing-from-catalogue``a documented event has no entry (wired or
                                tracked-unwired) in ``constants/events.py``.
``unexpressed-capability``      a documented output field a bespoke schema
                                cannot express (e.g. PreToolUse ``updatedInput``).
``unexpressed-enum-value``      a documented enum value a schema cannot express
                                (e.g. ``permissionDecision: defer``).
``unexpressed-universal-fields``the documented universal fields (grouped into a
                                single finding per event) a bespoke schema
                                rejects.
``dead-letter-field``           a schema accepts a field the docs say Claude
                                Code DISCARDS for the event.
``stale-allowlist-entry``       an ``ALLOWLIST.yaml`` entry whose drift no
                                longer exists (stale allowlists rot too).
``malformed-allowlist-entry``   an allowlist entry missing its reason or its
                                linked plan/task.

The ``Status``/``StatusLine`` surface is out-of-contract BY DESIGN: the status
line is a separate Claude Code feature with its own contract, not a hooks
event, so its schema is never diffed here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
_SRC_DIR_NAME: Final[str] = "src"
_CONTRACTS_DIR_PARTS: Final[tuple[str, str]] = ("contracts", "claude-code-hooks")
_ALLOWLIST_FILENAME: Final[str] = "ALLOWLIST.yaml"
_META_FILENAME: Final[str] = "META.json"
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "hook_contract.json"

# The five universal output fields every event accepts (docs "JSON output").
UNIVERSAL_FIELDS: Final[tuple[str, ...]] = (
    "continue",
    "stopReason",
    "suppressOutput",
    "systemMessage",
    "terminalSequence",
)

# Vendored block_mechanism tokens (see docs/guides/HOOK-CONTRACT-REFRESH.md).
MECH_TOP_LEVEL: Final[str] = "top-level-decision"
MECH_EXIT_OR_CONTINUE: Final[str] = "exit-2-or-continue-false"
MECH_EXIT_OR_TOP_LEVEL: Final[str] = "exit-2-or-top-level-decision"
MECH_PERMISSION_DECISION: Final[str] = "permission-decision"
MECH_DECISION_BEHAVIOUR: Final[str] = "decision-behavior"
MECH_ACTION: Final[str] = "hook-specific-action"
MECH_PATH_RETURN: Final[str] = "path-return"

#: Mechanisms a ``HookResult`` DENY can express on the wire. An event whose
#: only documented block route is a returned path or an elicitation action is
#: not owed a ``REFUSAL_CAPABLE_EVENTS`` entry.
_REFUSAL_EXPRESSIBLE_MECHANISMS: Final[frozenset[str]] = frozenset(
    {
        MECH_TOP_LEVEL,
        MECH_EXIT_OR_CONTINUE,
        MECH_EXIT_OR_TOP_LEVEL,
        MECH_PERMISSION_DECISION,
        MECH_DECISION_BEHAVIOUR,
    }
)

# Rule names.
RULE_UNDOCUMENTED_FIELD: Final[str] = "undocumented-schema-field"
RULE_UNDOCUMENTED_ENUM: Final[str] = "undocumented-enum-value"
RULE_UNDOCUMENTED_CLAIM: Final[str] = "undocumented-claim"
RULE_MISSING_REFUSAL: Final[str] = "missing-refusal-claim"
RULE_CAPABILITY_DRIFT: Final[str] = "capability-table-drift"
RULE_EMITTED_TOKEN: Final[str] = "undocumented-emitted-token"
RULE_EVENT_MISSING: Final[str] = "event-missing-from-catalogue"
RULE_UNEXPRESSED: Final[str] = "unexpressed-capability"
RULE_UNEXPRESSED_ENUM: Final[str] = "unexpressed-enum-value"
RULE_UNEXPRESSED_UNIVERSAL: Final[str] = "unexpressed-universal-fields"
RULE_DEAD_LETTER: Final[str] = "dead-letter-field"
RULE_STALE_ALLOWLIST: Final[str] = "stale-allowlist-entry"
RULE_MALFORMED_ALLOWLIST: Final[str] = "malformed-allowlist-entry"

#: Schema registry keys that are daemon-internal, not hooks events (statusline
#: is a separate Claude Code feature with its own contract — audit, cosmetic).
_DAEMON_ONLY_SCHEMA_KEYS: Final[frozenset[str]] = frozenset({"Status"})

#: The nested-object field key that carries its own field table (PermissionRequest).
_NESTED_DECISION_KEY: Final[str] = "decision"
_HSO_KEY: Final[str] = "hookSpecificOutput"
_HOOK_EVENT_NAME_KEY: Final[str] = "hookEventName"
_ENUM_KEY: Final[str] = "enum"
_FIELDS_KEY: Final[str] = "fields"
_PROPERTIES_KEY: Final[str] = "properties"


@dataclass
class Finding:
    """One contract drift, identified stably for allowlisting."""

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
    """Full check result: live violations, allowlisted gaps, stale entries."""

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


def load_contracts(contracts_dir: Path) -> dict[str, dict[str, Any]]:
    """Load every per-event contract JSON, keyed by event name.

    Raises:
        FileNotFoundError: when the vendored contract directory is absent —
            FAIL FAST, a contract check with no contract verifies nothing.
    """
    if not contracts_dir.is_dir():
        raise FileNotFoundError(f"vendored contract directory missing: {contracts_dir}")
    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == _META_FILENAME:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        contracts[data["event"]] = data
    return contracts


def load_allowlist(contracts_dir: Path) -> list[dict[str, Any]]:
    """Load ALLOWLIST.yaml entries; an absent file is an empty allowlist."""
    path = contracts_dir / _ALLOWLIST_FILENAME
    if not path.is_file():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("entries", [])
    return list(entries) if isinstance(entries, list) else []


def _is_permissive(schema: dict[str, Any]) -> bool:
    """True for the fail-open schema wired events without a bespoke one get."""
    return schema.get("additionalProperties") is True and _PROPERTIES_KEY not in schema


def _schema_top_fields(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.get(_PROPERTIES_KEY, {}).items() if k not in (_HSO_KEY,)}


def _schema_hso_fields(schema: dict[str, Any]) -> dict[str, Any]:
    hso = schema.get(_PROPERTIES_KEY, {}).get(_HSO_KEY, {})
    return {k: v for k, v in hso.get(_PROPERTIES_KEY, {}).items() if k != _HOOK_EVENT_NAME_KEY}


def _contract_hso_fields(contract: dict[str, Any]) -> dict[str, Any]:
    return contract.get("hook_specific_output_fields") or {}


def check_schema_fields(
    event: str, contract: dict[str, Any], schema: dict[str, Any]
) -> list[Finding]:
    """Emit-side checks: schema fields/enums the docs never define, dead letters."""
    findings: list[Finding] = []
    if _is_permissive(schema):
        return findings

    documented_top = set(contract.get("top_level_output_fields", []))
    discarded = set(contract.get("discarded_fields", []))
    contract_hso = _contract_hso_fields(contract)

    for name in _schema_top_fields(event_schema := schema):
        if name == "worktreePath" and "worktreePath" in contract_hso:
            # WorktreeCreate: the daemon carries the path at the top level for
            # the forwarder to print raw — the documented command-hook form.
            continue
        if name not in documented_top:
            findings.append(
                Finding(
                    rule=RULE_UNDOCUMENTED_FIELD,
                    event=event,
                    subject=name,
                    message=(
                        f"schema accepts top-level '{name}', which the docs do not "
                        f"define for {event}"
                    ),
                )
            )
        elif name in discarded:
            findings.append(
                Finding(
                    rule=RULE_DEAD_LETTER,
                    event=event,
                    subject=name,
                    message=(
                        f"schema accepts '{name}' but the docs say Claude Code "
                        f"DISCARDS it for {event}"
                    ),
                )
            )
    del event_schema

    for name, spec in _schema_hso_fields(schema).items():
        contract_spec = contract_hso.get(name)
        if contract_spec is None:
            findings.append(
                Finding(
                    rule=RULE_UNDOCUMENTED_FIELD,
                    event=event,
                    subject=f"{_HSO_KEY}.{name}",
                    message=(
                        f"schema accepts hookSpecificOutput.{name}, which the docs "
                        f"do not define for {event}"
                    ),
                )
            )
            continue
        findings.extend(_check_enum(event, f"{_HSO_KEY}.{name}", spec, contract_spec))
        if name == _NESTED_DECISION_KEY and _FIELDS_KEY in contract_spec:
            findings.extend(_check_nested_decision(event, spec, contract_spec[_FIELDS_KEY]))
    return findings


def _check_enum(
    event: str, path: str, schema_spec: dict[str, Any], contract_spec: dict[str, Any]
) -> list[Finding]:
    schema_enum = schema_spec.get(_ENUM_KEY)
    contract_enum = contract_spec.get(_ENUM_KEY)
    if not schema_enum or not contract_enum:
        return []
    return [
        Finding(
            rule=RULE_UNDOCUMENTED_ENUM,
            event=event,
            subject=f"{path}={value}",
            message=(
                f"schema enum for {path} allows '{value}', which the docs do not "
                f"define for {event} (documented: {contract_enum})"
            ),
        )
        for value in schema_enum
        if value not in contract_enum
    ]


def _check_nested_decision(
    event: str, schema_spec: dict[str, Any], contract_fields: dict[str, Any]
) -> list[Finding]:
    findings: list[Finding] = []
    for name, spec in schema_spec.get(_PROPERTIES_KEY, {}).items():
        path = f"{_HSO_KEY}.{_NESTED_DECISION_KEY}.{name}"
        contract_spec = contract_fields.get(name)
        if contract_spec is None:
            findings.append(
                Finding(
                    rule=RULE_UNDOCUMENTED_FIELD,
                    event=event,
                    subject=path,
                    message=(f"schema accepts {path}, which the docs do not define for {event}"),
                )
            )
            continue
        findings.extend(_check_enum(event, path, spec, contract_spec))
    return findings


def check_expressiveness(
    event: str, contract: dict[str, Any], schema: dict[str, Any]
) -> list[Finding]:
    """Gap-side checks: documented capabilities a bespoke schema cannot express."""
    findings: list[Finding] = []
    if _is_permissive(schema):
        return findings

    schema_top = _schema_top_fields(schema)
    schema_hso = _schema_hso_fields(schema)
    discarded = set(contract.get("discarded_fields", []))

    unexpressed_universal = [
        name
        for name in UNIVERSAL_FIELDS
        if name in contract.get("top_level_output_fields", [])
        and name not in discarded
        and name not in schema_top
    ]
    if unexpressed_universal:
        findings.append(
            Finding(
                rule=RULE_UNEXPRESSED_UNIVERSAL,
                event=event,
                subject="universal",
                message=(
                    f"schema cannot express the documented universal fields "
                    f"{unexpressed_universal} on {event}"
                ),
            )
        )

    for name in contract.get("top_level_output_fields", []):
        if name in UNIVERSAL_FIELDS or name in discarded:
            continue
        if name not in schema_top:
            findings.append(
                Finding(
                    rule=RULE_UNEXPRESSED,
                    event=event,
                    subject=name,
                    message=f"documented top-level field '{name}' is inexpressible on {event}",
                )
            )

    for name, contract_spec in _contract_hso_fields(contract).items():
        schema_spec = schema_hso.get(name)
        if schema_spec is None:
            findings.append(
                Finding(
                    rule=RULE_UNEXPRESSED,
                    event=event,
                    subject=f"{_HSO_KEY}.{name}",
                    message=(f"documented hookSpecificOutput.{name} is inexpressible on {event}"),
                )
            )
            continue
        contract_enum = contract_spec.get(_ENUM_KEY)
        schema_enum = schema_spec.get(_ENUM_KEY)
        if contract_enum and schema_enum:
            for value in contract_enum:
                if value not in schema_enum:
                    findings.append(
                        Finding(
                            rule=RULE_UNEXPRESSED_ENUM,
                            event=event,
                            subject=f"{_HSO_KEY}.{name}={value}",
                            message=(
                                f"documented value '{value}' of "
                                f"hookSpecificOutput.{name} is inexpressible on {event}"
                            ),
                        )
                    )
        nested = contract_spec.get(_FIELDS_KEY)
        if nested:
            schema_nested = schema_spec.get(_PROPERTIES_KEY, {})
            for nested_name in nested:
                if nested_name not in schema_nested:
                    findings.append(
                        Finding(
                            rule=RULE_UNEXPRESSED,
                            event=event,
                            subject=f"{_HSO_KEY}.{name}.{nested_name}",
                            message=(
                                f"documented hookSpecificOutput.{name}.{nested_name} "
                                f"is inexpressible on {event}"
                            ),
                        )
                    )
    return findings


def check_capability_claims(
    event: str,
    contract: dict[str, Any],
    *,
    claimed_deny: bool,
    claimed_ask: bool,
    meta_can_block: bool | None,
) -> list[Finding]:
    """Claim-table checks: REFUSAL_CAPABLE_EVENTS and events.py can_block."""
    findings: list[Finding] = []
    contract_can_block = bool(contract.get("can_block"))
    mechanism = contract.get("block_mechanism")

    if claimed_deny and not contract_can_block:
        findings.append(
            Finding(
                rule=RULE_UNDOCUMENTED_CLAIM,
                event=event,
                subject="deny",
                message=(
                    f"REFUSAL_CAPABLE_EVENTS claims DENY on {event}, but the docs "
                    f"document no blocking mechanism for it"
                ),
            )
        )
    if claimed_ask and not contract.get("ask_capable"):
        findings.append(
            Finding(
                rule=RULE_UNDOCUMENTED_CLAIM,
                event=event,
                subject="ask",
                message=(
                    f"REFUSAL_CAPABLE_EVENTS claims ASK on {event}, but the docs "
                    f"define no ask outcome for it"
                ),
            )
        )
    if not claimed_deny and contract_can_block and mechanism in _REFUSAL_EXPRESSIBLE_MECHANISMS:
        findings.append(
            Finding(
                rule=RULE_MISSING_REFUSAL,
                event=event,
                subject="deny",
                message=(
                    f"the docs document blocking for {event} "
                    f"({mechanism}), but REFUSAL_CAPABLE_EVENTS omits it — a DENY "
                    f"there is silently dropped"
                ),
            )
        )
    if meta_can_block is not None and meta_can_block != contract_can_block:
        findings.append(
            Finding(
                rule=RULE_CAPABILITY_DRIFT,
                event=event,
                subject="can_block",
                message=(
                    f"constants/events.py says can_block={meta_can_block} for "
                    f"{event}; the vendored contract says {contract_can_block}"
                ),
            )
        )
    return findings


def emitted_token_finding(
    event: str, contract: dict[str, Any], payload: dict[str, Any]
) -> Finding | None:
    """Flag a serialised top-level ``decision`` token the docs never define."""
    token = payload.get("decision")
    if token is None:
        return None
    enum = contract.get("top_level_decision_enum") or []
    if token in enum:
        return None
    return Finding(
        rule=RULE_EMITTED_TOKEN,
        event=event,
        subject=f"decision={token}",
        message=(
            f"serialising a DENY on {event} emits top-level decision '{token}', "
            f"which the docs never define (documented values: {enum})"
        ),
    )


def check_catalogue(contracts: dict[str, dict[str, Any]]) -> list[Finding]:
    """Every documented event must exist in constants/events.py (wired or not)."""
    _prime_sys_path()
    from claude_code_hooks_daemon.constants.events import all_event_metas

    known = {meta.json_key for meta in all_event_metas()}
    return [
        Finding(
            rule=RULE_EVENT_MISSING,
            event=name,
            subject="catalogue",
            message=(
                f"documented event {name} has no entry in constants/events.py — "
                f"add it (wired, or wired=False + EXPECTED_UNWIRED per the "
                f"file's tracked-gap rule)"
            ),
        )
        for name in sorted(contracts)
        if name not in known
    ]


def apply_allowlist(
    findings: list[Finding], entries: list[dict[str, Any]]
) -> tuple[list[Finding], list[dict[str, Any]], list[Finding]]:
    """Split findings into (remaining, allowlisted) and validate the allowlist.

    A stale entry (no matching finding) and a malformed entry (missing reason
    or link) are themselves violations: a stale allowlist rots exactly like a
    stale schema (Plan 00271 Decision 2).
    """
    by_id = {f.finding_id: f for f in findings}
    remaining = dict(by_id)
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
                        "allowlist entry must carry id, reason and a linked "
                        f"plan/task; got: {entry}"
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


def _prime_sys_path() -> None:
    entry = str(_PROJECT_ROOT / _SRC_DIR_NAME)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def scan(root: Path) -> Report:
    """Run every rule against the tree at ``root`` and apply its allowlist."""
    _prime_sys_path()
    from claude_code_hooks_daemon.constants.events import all_event_metas
    from claude_code_hooks_daemon.core.hook_result import (
        REFUSAL_CAPABLE_EVENTS,
        Decision,
        HookResult,
    )
    from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS

    contracts_dir = root.joinpath(*_CONTRACTS_DIR_PARTS)
    contracts = load_contracts(contracts_dir)
    entries = load_allowlist(contracts_dir)
    metas = {meta.json_key: meta for meta in all_event_metas()}

    findings: list[Finding] = []
    findings.extend(check_catalogue(contracts))

    deny_events = REFUSAL_CAPABLE_EVENTS.get(Decision.DENY, frozenset())
    ask_events = REFUSAL_CAPABLE_EVENTS.get(Decision.ASK, frozenset())

    for name, contract in sorted(contracts.items()):
        meta = metas.get(name)
        schema = RESPONSE_SCHEMAS.get(name)
        findings.extend(
            check_capability_claims(
                name,
                contract,
                claimed_deny=name in deny_events,
                claimed_ask=name in ask_events,
                meta_can_block=None if meta is None else meta.can_block,
            )
        )
        if schema is None:
            continue
        findings.extend(check_schema_fields(name, contract, schema))
        findings.extend(check_expressiveness(name, contract, schema))

        # Emitted-token probe: what does a DENY actually put on the wire for a
        # documented top-level-decision event whose schema is fail-open?
        if contract.get("block_mechanism") in (
            MECH_TOP_LEVEL,
            MECH_EXIT_OR_TOP_LEVEL,
        ) and _is_permissive(schema):
            # The probe legitimately triggers the serialiser's DROPPED REFUSAL
            # error log; silence that logger for the probe only — the drop IS
            # the finding being checked for, not an incident to report twice.
            import logging

            serialiser_logger = logging.getLogger(HookResult.__module__)
            previous_level = serialiser_logger.level
            serialiser_logger.setLevel(logging.CRITICAL)
            try:
                payload = HookResult(decision=Decision.DENY, reason="contract probe").to_json(name)
            finally:
                serialiser_logger.setLevel(previous_level)
            probe = emitted_token_finding(name, contract, payload)
            if probe is not None:
                findings.append(probe)

    # Claims about events the vendored contract does not know (minus the
    # daemon-only surfaces) would themselves be drift, but every documented
    # event is vendored, so the only residue is Status — skipped by design.
    findings = [f for f in findings if f.event not in _DAEMON_ONLY_SCHEMA_KEYS]

    remaining, allowlisted, problems = apply_allowlist(findings, entries)
    return Report(violations=remaining + problems, allowlisted=allowlisted)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hook-contract drift check (Plan 00271)")
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
    except (FileNotFoundError, json.JSONDecodeError) as exc:
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
        print(f"Found {len(report.violations)} hook-contract violation(s):")
        for violation in report.violations:
            print(f"  [{violation.rule}] {violation.event}: {violation.message}")
    else:
        print(
            f"No hook-contract violations ({len(report.allowlisted)} recorded "
            f"allowlisted gap(s))"
        )

    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
