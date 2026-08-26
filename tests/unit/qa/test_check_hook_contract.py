"""Plan 00271 Task 1.3 — unit tests for the hook-contract QA checker.

The checker diffs the daemon's three sources of truth (``response_schemas.py``,
``REFUSAL_CAPABLE_EVENTS``, ``constants/events.py``) against the vendored
Claude Code hooks contract under ``contracts/claude-code-hooks/``. It is
network-free by design (Plan 00271 Decision 4).

Drift-detection logic is tested against SYNTHETIC contract/schema inputs so the
tests stay green as Phase 2 fixes close the real drifts; the RED run against
the real tree is Task 1.6's manual step, recorded in the plan's JOURNAL/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "qa"))

import check_hook_contract as chc

REPO_ROOT = Path(__file__).resolve().parents[3]


def _contract(
    event: str = "FakeEvent",
    *,
    block: str | None = None,
    ask: bool = False,
    top_extra: list[str] | None = None,
    enum: list[str] | None = None,
    hso: dict | None = None,
    discards: list[str] | None = None,
) -> dict:
    return {
        "event": event,
        "block_mechanism": block,
        "can_block": block is not None,
        "ask_capable": ask,
        "top_level_output_fields": list(chc.UNIVERSAL_FIELDS) + (top_extra or []),
        "top_level_decision_enum": enum,
        "hook_specific_output_fields": hso,
        "discarded_fields": discards or [],
        "notes": "",
        "input_example": {},
    }


class TestContractLoading:
    def test_loads_every_vendored_event(self) -> None:
        contracts = chc.load_contracts(REPO_ROOT / "contracts" / "claude-code-hooks")
        assert len(contracts) >= 31
        assert "PreToolUse" in contracts
        assert "DirectoryAdded" in contracts

    def test_meta_is_not_a_contract(self) -> None:
        contracts = chc.load_contracts(REPO_ROOT / "contracts" / "claude-code-hooks")
        assert "META" not in contracts

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            chc.load_contracts(tmp_path / "nope")


class TestSchemaFieldChecks:
    def test_undocumented_top_level_field_is_flagged(self) -> None:
        contract = _contract("E1")
        schema = {
            "type": "object",
            "properties": {"decision": {"const": "block"}},
            "additionalProperties": False,
        }
        findings = chc.check_schema_fields("E1", contract, schema)
        assert any(
            f.rule == chc.RULE_UNDOCUMENTED_FIELD and f.subject == "decision" for f in findings
        )

    def test_documented_fields_pass(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, top_extra=["decision", "reason"])
        schema = {
            "type": "object",
            "properties": {"decision": {}, "reason": {}, "systemMessage": {}},
            "additionalProperties": False,
        }
        assert chc.check_schema_fields("E1", contract, schema) == []

    def test_undocumented_hso_field_is_flagged(self) -> None:
        contract = _contract("E1", hso={"additionalContext": {}})
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {
                        "hookEventName": {},
                        "additionalContext": {},
                        "guidance": {},
                    },
                }
            },
        }
        findings = chc.check_schema_fields("E1", contract, schema)
        assert [f.subject for f in findings if f.rule == chc.RULE_UNDOCUMENTED_FIELD] == [
            "hookSpecificOutput.guidance"
        ]

    def test_undocumented_enum_value_is_flagged(self) -> None:
        contract = _contract(
            "E1",
            block=chc.MECH_PERMISSION_DECISION,
            hso={"permissionDecision": {"enum": ["allow", "deny"]}},
        )
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {
                        "hookEventName": {},
                        "permissionDecision": {"enum": ["allow", "deny", "ask"]},
                    },
                }
            },
        }
        findings = chc.check_schema_fields("E1", contract, schema)
        assert any(f.rule == chc.RULE_UNDOCUMENTED_ENUM and "ask" in f.subject for f in findings)

    def test_nested_decision_fields_compared(self) -> None:
        contract = _contract(
            "E1",
            block=chc.MECH_DECISION_BEHAVIOUR,
            hso={"decision": {"fields": {"behavior": {"enum": ["allow", "deny"]}}}},
        )
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {
                        "hookEventName": {},
                        "decision": {
                            "type": "object",
                            "properties": {
                                "behavior": {"enum": ["allow", "deny", "ask"]},
                                "updatedInput": {},
                            },
                        },
                    },
                }
            },
        }
        findings = chc.check_schema_fields("E1", contract, schema)
        rules = {(f.rule, f.subject) for f in findings}
        assert (chc.RULE_UNDOCUMENTED_ENUM, "hookSpecificOutput.decision.behavior=ask") in rules

    def test_nested_undocumented_field_flagged(self) -> None:
        contract = _contract(
            "E1",
            block=chc.MECH_DECISION_BEHAVIOUR,
            hso={"decision": {"fields": {"behavior": {"enum": ["allow", "deny"]}}}},
        )
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {
                        "hookEventName": {},
                        "decision": {
                            "type": "object",
                            "properties": {
                                "behavior": {"enum": ["allow", "deny"]},
                                "updatedInput": {},
                            },
                        },
                    },
                }
            },
        }
        findings = chc.check_schema_fields("E1", contract, schema)
        assert any(
            f.rule == chc.RULE_UNDOCUMENTED_FIELD
            and f.subject == "hookSpecificOutput.decision.updatedInput"
            for f in findings
        )

    def test_dead_letter_field_is_flagged(self) -> None:
        contract = _contract("E1", discards=["systemMessage"])
        schema = {"type": "object", "properties": {"systemMessage": {}}}
        findings = chc.check_schema_fields("E1", contract, schema)
        assert any(
            f.rule == chc.RULE_DEAD_LETTER and f.subject == "systemMessage" for f in findings
        )


class TestExpressivenessChecks:
    def test_unexpressed_hso_capability_is_flagged(self) -> None:
        contract = _contract("E1", hso={"additionalContext": {}, "sessionTitle": {}})
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {"hookEventName": {}, "additionalContext": {}},
                }
            },
        }
        findings = chc.check_expressiveness("E1", contract, schema)
        assert any(
            f.rule == chc.RULE_UNEXPRESSED and f.subject == "hookSpecificOutput.sessionTitle"
            for f in findings
        )

    def test_unexpressed_enum_value_is_flagged(self) -> None:
        contract = _contract(
            "E1",
            block=chc.MECH_PERMISSION_DECISION,
            hso={"permissionDecision": {"enum": ["allow", "deny", "ask", "defer"]}},
        )
        schema = {
            "type": "object",
            "properties": {
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {
                        "hookEventName": {},
                        "permissionDecision": {"enum": ["allow", "deny", "ask"]},
                    },
                }
            },
        }
        findings = chc.check_expressiveness("E1", contract, schema)
        assert any(f.rule == chc.RULE_UNEXPRESSED_ENUM and "defer" in f.subject for f in findings)

    def test_universal_fields_grouped_into_one_finding(self) -> None:
        contract = _contract("E1", discards=["systemMessage"])
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        findings = chc.check_expressiveness("E1", contract, schema)
        universal = [f for f in findings if f.rule == chc.RULE_UNEXPRESSED_UNIVERSAL]
        assert len(universal) == 1
        # Discarded fields are not owed expression.
        assert "systemMessage" not in universal[0].message

    def test_fully_expressive_schema_passes(self) -> None:
        contract = _contract("E1", hso={"additionalContext": {}})
        schema = {
            "type": "object",
            "properties": {
                "continue": {},
                "stopReason": {},
                "suppressOutput": {},
                "systemMessage": {},
                "terminalSequence": {},
                "hookSpecificOutput": {
                    "type": "object",
                    "properties": {"hookEventName": {}, "additionalContext": {}},
                },
            },
        }
        assert chc.check_expressiveness("E1", contract, schema) == []


class TestCapabilityChecks:
    def test_undocumented_deny_claim_is_flagged(self) -> None:
        contract = _contract("E1")  # cannot block
        findings = chc.check_capability_claims(
            "E1", contract, claimed_deny=True, claimed_ask=False, meta_can_block=False
        )
        assert any(f.rule == chc.RULE_UNDOCUMENTED_CLAIM and f.subject == "deny" for f in findings)

    def test_undocumented_ask_claim_is_flagged(self) -> None:
        contract = _contract("E1", block=chc.MECH_DECISION_BEHAVIOUR)
        findings = chc.check_capability_claims(
            "E1", contract, claimed_deny=True, claimed_ask=True, meta_can_block=True
        )
        assert any(f.rule == chc.RULE_UNDOCUMENTED_CLAIM and f.subject == "ask" for f in findings)

    def test_missing_refusal_claim_is_flagged(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, enum=["block"])
        findings = chc.check_capability_claims(
            "E1", contract, claimed_deny=False, claimed_ask=False, meta_can_block=True
        )
        assert any(f.rule == chc.RULE_MISSING_REFUSAL for f in findings)

    def test_capability_table_drift_is_flagged(self) -> None:
        contract = _contract("E1")  # can_block False
        findings = chc.check_capability_claims(
            "E1", contract, claimed_deny=False, claimed_ask=False, meta_can_block=True
        )
        assert any(f.rule == chc.RULE_CAPABILITY_DRIFT for f in findings)

    def test_consistent_claims_pass(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, enum=["block"], ask=False)
        findings = chc.check_capability_claims(
            "E1", contract, claimed_deny=True, claimed_ask=False, meta_can_block=True
        )
        assert findings == []


class TestEmittedTokenCheck:
    def test_undefined_deny_token_is_flagged(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, enum=["block"])
        finding = chc.emitted_token_finding("E1", contract, {"decision": "deny", "reason": "x"})
        assert finding is not None
        assert finding.rule == chc.RULE_EMITTED_TOKEN
        assert "deny" in finding.subject

    def test_documented_block_token_passes(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, enum=["block"])
        assert chc.emitted_token_finding("E1", contract, {"decision": "block"}) is None

    def test_payload_without_decision_passes(self) -> None:
        contract = _contract("E1", block=chc.MECH_TOP_LEVEL, enum=["block"])
        assert chc.emitted_token_finding("E1", contract, {}) is None


class TestCatalogueCheck:
    def test_vendored_event_missing_from_catalogue_is_flagged(self) -> None:
        findings = chc.check_catalogue({"TotallyNewEvent": _contract("TotallyNewEvent")})
        assert any(
            f.rule == chc.RULE_EVENT_MISSING and f.event == "TotallyNewEvent" for f in findings
        )

    def test_catalogued_event_passes(self) -> None:
        assert chc.check_catalogue({"PreToolUse": _contract("PreToolUse")}) == []


class TestAllowlist:
    def _finding(self) -> chc.Finding:
        return chc.Finding(
            rule=chc.RULE_UNDOCUMENTED_FIELD, event="E1", subject="guidance", message="m"
        )

    def test_allowlisted_finding_is_suppressed(self) -> None:
        finding = self._finding()
        entries = [
            {"id": finding.finding_id, "reason": "daemon extension", "link": "Plan 00271 Task 3.2"}
        ]
        remaining, allowlisted, stale = chc.apply_allowlist([finding], entries)
        assert remaining == []
        assert len(allowlisted) == 1
        assert stale == []

    def test_unallowlisted_finding_remains(self) -> None:
        finding = self._finding()
        remaining, allowlisted, _stale = chc.apply_allowlist([finding], [])
        assert remaining == [finding]
        assert allowlisted == []

    def test_stale_entry_is_a_violation(self) -> None:
        entries = [{"id": "no-such:E9:field", "reason": "r", "link": "Plan 00271"}]
        remaining, _, stale = chc.apply_allowlist([], entries)
        assert remaining == []
        assert len(stale) == 1
        assert stale[0].rule == chc.RULE_STALE_ALLOWLIST

    def test_entry_without_link_is_a_violation(self) -> None:
        finding = self._finding()
        entries = [{"id": finding.finding_id, "reason": "r"}]
        _, _, stale = chc.apply_allowlist([finding], entries)
        assert any(f.rule == chc.RULE_MALFORMED_ALLOWLIST for f in stale)


class TestFullScan:
    def test_scan_runs_on_real_tree(self) -> None:
        """The real tree scan must complete and produce a well-formed report.

        Whether it PASSES depends on the allowlist state (RED before Task 1.6
        seeds it, green after) — this test asserts shape, not verdict.
        """
        report = chc.scan(REPO_ROOT)
        payload = report.to_dict()
        assert "summary" in payload and "violations" in payload
        assert isinstance(payload["summary"]["passed"], bool)

    def test_status_line_is_out_of_contract_by_design(self) -> None:
        """The daemon's Status schema is never diffed — statusline is a
        separate Claude Code feature with its own contract."""
        report = chc.scan(REPO_ROOT)
        assert not any(v["event"] == "Status" for v in report.to_dict()["violations"])

    def test_json_payload_round_trips(self) -> None:
        report = chc.scan(REPO_ROOT)
        json.loads(json.dumps(report.to_dict()))
