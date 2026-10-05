"""Check a hook's JSON output against Claude Code's per-event output contract.

The contract is the vendored one under ``contracts/claude-code-hooks/`` (one
JSON per event, derived from the Claude Code docs); this module only READS it,
so there is no second copy of what an event accepts. Claude Code validates hook
output strictly: a key or ``hookSpecificOutput`` the event does not define
invalidates the whole document.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import yaml

_CONTRACTS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "contracts" / "claude-code-hooks"
)

_HSO_KEY: Final[str] = "hookSpecificOutput"
_CONTEXT_FIELD: Final[str] = "additionalContext"


def load_event_contracts() -> dict[str, dict[str, Any]]:
    """Every per-event contract, keyed by event name."""
    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(_CONTRACTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "event" in data:
            contracts[str(data["event"])] = data
    return contracts


def _allowlisted_extensions() -> frozenset[str]:
    """``<Event>.<field>`` pairs the daemon deliberately emits beyond the docs.

    From the contract ALLOWLIST (``undocumented-schema-field`` entries), the
    reasoned record of the daemon-internal ``hookSpecificOutput`` extensions.
    """
    data = yaml.safe_load((_CONTRACTS_DIR / "ALLOWLIST.yaml").read_text(encoding="utf-8"))
    prefix = "undocumented-schema-field:"
    pairs: set[str] = set()
    for entry in data["entries"]:
        entry_id = str(entry["id"])
        if entry_id.startswith(prefix):
            event, _, path = entry_id[len(prefix) :].partition(":")
            pairs.add(f"{event}.{path.removeprefix(_HSO_KEY + '.')}")
    return frozenset(pairs)


def events_accepting_context() -> frozenset[str]:
    """Events whose contract defines ``hookSpecificOutput.additionalContext``."""
    return frozenset(
        event
        for event, contract in load_event_contracts().items()
        if _CONTEXT_FIELD in (contract.get("hook_specific_output_fields") or {})
    )


def contract_violations(event: str, response: dict[str, Any]) -> list[str]:
    """What in ``response`` the event's contract does not define (empty = valid)."""
    contract = load_event_contracts()[event]
    problems: list[str] = []

    allowed_top = set(contract["top_level_output_fields"]) | {_HSO_KEY}
    for key in response:
        if key not in allowed_top:
            problems.append(f"top-level key {key!r} is not defined for {event}")

    enum = contract.get("top_level_decision_enum")
    if "decision" in response and enum is not None and response["decision"] not in enum:
        problems.append(f"decision {response['decision']!r} is not one of {enum}")

    if _HSO_KEY in response:
        hso_fields = contract.get("hook_specific_output_fields")
        hso = response[_HSO_KEY]
        if hso_fields is None:
            problems.append(f"{event} defines no hookSpecificOutput at all")
        else:
            if hso.get("hookEventName") != event:
                problems.append(f"hookEventName {hso.get('hookEventName')!r} is not {event!r}")
            extensions = _allowlisted_extensions()
            for key in hso:
                if key == "hookEventName" or key in hso_fields:
                    continue
                if f"{event}.{key}" not in extensions:
                    problems.append(f"hookSpecificOutput.{key} is not defined for {event}")
    return problems
