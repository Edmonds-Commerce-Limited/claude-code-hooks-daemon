#!/usr/bin/env python3
"""Shared allowlist protocol for the vendored-contract QA checkers.

Plan 00273 (DRY): ``check_hook_contract.py`` (response side, Plan 00271) and
``check_input_contract.py`` (input side, Plan 00273) share one allowlist
convention — YAML ``entries`` each carrying ``id``/``reason``/``link``, stable
finding ids ``rule:event:subject``, and the rule that a stale or malformed
entry is itself a violation (a stale allowlist rots exactly like a stale
schema — Plan 00271 Decision 2). This module is that single source of truth;
each checker supplies its own allowlist file path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

# Allowlist YAML keys.
ENTRIES_KEY: Final[str] = "entries"
ENTRY_ID_KEY: Final[str] = "id"
ENTRY_REASON_KEY: Final[str] = "reason"
ENTRY_LINK_KEY: Final[str] = "link"

# Allowlist-integrity rule names (shared by both checkers).
RULE_STALE_ALLOWLIST: Final[str] = "stale-allowlist-entry"
RULE_MALFORMED_ALLOWLIST: Final[str] = "malformed-allowlist-entry"

#: Event placeholder for findings about the allowlist itself.
NO_EVENT: Final[str] = "-"
_MISSING_ID_SUBJECT: Final[str] = "(missing id)"


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


def load_allowlist_file(path: Path) -> list[dict[str, Any]]:
    """Load allowlist entries from a YAML file; absent file = empty allowlist."""
    if not path.is_file():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get(ENTRIES_KEY, [])
    return list(entries) if isinstance(entries, list) else []


def apply_allowlist(
    findings: list[Finding], entries: list[dict[str, Any]]
) -> tuple[list[Finding], list[dict[str, Any]], list[Finding]]:
    """Split findings into (remaining, allowlisted) and validate the allowlist.

    A stale entry (no matching finding) and a malformed entry (missing reason
    or link) are themselves violations.
    """
    remaining = {f.finding_id: f for f in findings}
    allowlisted: list[dict[str, Any]] = []
    problems: list[Finding] = []
    for entry in entries:
        entry_id = str(entry.get(ENTRY_ID_KEY, ""))
        reason = entry.get(ENTRY_REASON_KEY)
        link = entry.get(ENTRY_LINK_KEY)
        if not entry_id or not reason or not link:
            problems.append(
                Finding(
                    rule=RULE_MALFORMED_ALLOWLIST,
                    event=NO_EVENT,
                    subject=entry_id or _MISSING_ID_SUBJECT,
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
                    event=NO_EVENT,
                    subject=entry_id,
                    message=(
                        f"allowlist entry '{entry_id}' matches no current finding — "
                        f"the drift it recorded no longer exists; delete the entry"
                    ),
                )
            )
            continue
        allowlisted.append({**matched.to_dict(), ENTRY_REASON_KEY: reason, ENTRY_LINK_KEY: link})
    return list(remaining.values()), allowlisted, problems
