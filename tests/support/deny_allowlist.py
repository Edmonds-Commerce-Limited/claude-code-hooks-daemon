"""Handlers whose deny paths carry no declared rule, each with its reason.

One source for ``tests/unit/test_rule_parity.py`` and the
``tests/plugins/deny_carries_rule_id.py`` plugin, so the two cannot disagree
about which denials are allowed to carry no ``BLOCKED [R-...]`` identifier.
"""

from __future__ import annotations

#: Handlers whose module contains a Decision.DENY path but that legitimately
#: declare no Rule objects. Every entry MUST record why. This allowlist is
#: SEEDED from the state of the fan-out at Phase 7 authoring time (2026-08-31)
#: — the coordinator is expected to PRUNE this list as sibling Phase 3
#: migrations land, removing an entry the moment its handler gains get_rules().
_DENY_WITHOUT_RULES_ALLOWLIST: dict[str, str] = {
    "AutoApproveReadsHandler": (
        "Its Decision.DENY branch is defensive-only: matches() gates handle() to "
        "read-only tools already routed to Decision.ALLOW, so the DENY branch "
        "guards against a non-read tool reaching handle() by a path matches() "
        "does not permit today — not a live blocking rule with a table entry."
    ),
}

#: Project handlers whose module contains a deny path but that declare no rule
#: in the mode this repository runs them in. Every entry MUST record why.
_PROJECT_DENY_WITHOUT_RULES_ALLOWLIST: dict[str, str] = {
    "OrchestratorSimulateHandler": (
        "Plan 00418: it only RECORDS what orchestrator-only mode would deny while "
        "simulating, so it declares no rule (a rule row promises the rule can "
        "fire); armed, it declares R-ORCHESTRATOR-MAIN-THREAD-WRITE and denies with it."
    ),
}
