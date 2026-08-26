# Plan 00271 — Technical Decisions

Supporting document for [PLAN.md](PLAN.md). Each decision is summarised
there; the reasoning lives here.

## Decision 1: Vendored-contract format — per-event JSON + META.json

**Context**: The guard needs a machine-diffable, reviewable statement of
the documented contract.

**Options considered**:

1. One JSON file per event + `META.json` — small diffs on refresh, each
   file reviewable against its docs section, the checker iterates the
   directory so a missing event file is itself a finding.
2. One monolithic YAML — fewer files but refresh diffs conflate events and
   a forgotten event is invisible.
3. Reuse `response_schemas.py` as the contract — circular: the drifted
   artefact cannot be its own reference.

**Decision**: Option 1. JSON (not YAML) because the checker and tests load
it with the stdlib, and because the vendored data is a record, not config a
human tunes. `META.json` carries provenance (URL, fetch date, docs sha256,
last-audited Claude Code version) so staleness is checkable and refreshes
are attributable.
**Date**: 2026-08-26

## Decision 2: Reasoned allowlist, self-cleaning

**Context**: The daemon deliberately does not express every documented
field; the guard must distinguish "known, recorded gap" from drift.

**Options considered**:

1. Allowlist entries = `{event, field/token, reason, linked plan/task}`,
   with the checker failing on entries whose drift no longer exists.
2. Inline `# contract-gap:` comments in `response_schemas.py` — scattered,
   unqueryable, and invisible to the capability-table checks.
3. No allowlist; guard only checks the emit-side inventions — abandons
   half the defect class (documented capabilities silently missing).

**Decision**: Option 1. A stale allowlist is the same disease as a stale
schema, so unused entries are failures, not noise. Seeding the allowlist
with ALL Task 1.6 findings (each linked to its fix task) keeps QA green
between guard and fixes while making every gap a tracked TODO — the same
"recorded rather than silent" principle as `EXPECTED_UNWIRED`.
**Date**: 2026-08-26

## Decision 3: Staleness advisory over any auto-refresh

**Context**: The vendored copy rots exactly like the schemas did unless
something triggers a refresh.

**Options considered**:

1. SessionStart advisory when installed Claude Code version >
   `last_audited_claude_code_version` — cheap, uses existing machinery
   (sibling of `version_check`), puts a human/agent in the loop.
2. Scheduled auto-fetch + auto-update of the contract JSON — trusts an
   automated extraction of prose docs; the audit's fabricated-summary
   incident shows exactly this failing silently.
3. Nothing; rely on release-time discipline — that is the regime that
   produced 21 drifts.

**Decision**: Option 1, with Option 2 explicitly rejected: extraction from
prose must be verified, never trusted (the fetched summary layer invented
`permissionDecision: "escalate"`). The advisory is the trigger; REFRESH.md
is the procedure it points at.
**Date**: 2026-08-26

## Decision 4: The QA check is network-free

**Context**: QA runs on every commit and in CI; the docs live on the
network.

**Options considered**:

1. Diff daemon sources against the tracked vendored contract only — fast,
   deterministic, works offline; staleness is handled separately
   (Decision 3).
2. Fetch docs live in QA — flaky, slow, non-deterministic (docs can change
   mid-release), and couples every commit to claude.com availability.

**Decision**: Option 1. The guard checks internal consistency with the
vendored contract; freshness of the vendored contract is a separate,
advisory-triggered human procedure. Same split as `version_check` vs the
QA suite.
**Date**: 2026-08-26

## Decision 5: Guard lands red-then-allowlisted, not red-and-blocking

**Context**: DBF ordering means the guard exists before the fixes, but the
QA suite must stay green for unrelated work in the meantime.

**Decision**: Task 1.6 proves the checker sees every audit drift (RED run,
recorded in JOURNAL/), then seeds the allowlist so the suite passes with
every gap recorded and linked. Each Phase 2/3 fix deletes its entry,
re-arming enforcement fix by fix. This preserves both mandates: the guard
precedes the fixes, and an unfixed drift is never silent — it is an
allowlist line with a linked task.
**Date**: 2026-08-26
