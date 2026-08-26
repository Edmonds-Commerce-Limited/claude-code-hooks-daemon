# Plan 00273 — Decisions

## Decision: Phase 2 runtime missing-field advisory — NO-GO (Task 2.1)

**Question**: does the Task 1.2 static check leave observable residue — drift
only visible on live dispatches — that a runtime missing-field detector would
catch?

**Assessment**: the residue exists in principle but is not actionable. The
static check covers the entire drift class it can soundly detect: a field the
daemon READS that no vendored example documents. The only drift the runtime
side could add is the converse — a field the daemon reads being ABSENT from a
live payload. But Technical Decision 1 established that absence proves
nothing: several documented fields are legitimately conditional
(`Stop.stop_hook_active`/`background_tasks`/`session_crons`,
`PostToolUseFailure.error`/`is_interrupt`), and the examples carry no
required/optional marking to separate "conditionally absent" from "renamed
upstream". A runtime detector would therefore either fire on legitimate
dispatches (false signal in the direction that matters) or need a per-event
required-field table — which is Option 1 of Technical Decision 1, already
rejected as Plan 00271's substrate to change.

An upstream rename IS eventually observable statically: the refresh procedure
(HOOK-CONTRACT-REFRESH.md step 7, added by Task 1.4) re-runs the checker
against the refreshed examples, at which point the renamed field the daemon
still reads appears in no example and fails QA. That is the same signal the
runtime detector would give, minus the false positives and minus per-dispatch
cost against the ~1.8 ms budget.

**Decision**: NO-GO. Phase 2 ends at Task 2.1; Tasks 2.2–2.4 are not
executed (per the plan's explicit "If no-go, Phase 2 ends here"). No config
option is added, so no `config-changes` manifest entry is needed.

**Date**: 2026-08-26
