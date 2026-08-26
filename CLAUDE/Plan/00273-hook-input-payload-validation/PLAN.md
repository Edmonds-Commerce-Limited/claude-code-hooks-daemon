# Plan 00273: Hook Input Payload Validation

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Follow-up filed by Plan 00271 (its audit's "Input-payload drift surface").
The daemon validates hook RESPONSES against the vendored contract, but has no
input-schema layer at all: handlers read fields ad hoc (`stop_hook_active`,
`tool_input`, `prompt`, …), so a renamed or restructured input field would
surface only as handlers silently never matching — structurally invisible
drift.

The substrate already exists: every per-event file in
`contracts/claude-code-hooks/` carries a VERBATIM `input_example` lifted from
the raw hooks documentation, refreshed by the procedure in
`docs/guides/HOOK-CONTRACT-REFRESH.md`. This plan builds the input half on
that substrate: derive per-event input expectations (the fields the daemon
actually reads), check them against the vendored examples in QA, and surface
drift as an advisory rather than a block (inputs must stay fail-open).

## Context & Background

- Plan 00271 (Complete, `CLAUDE/Plan/Completed/00271-hook-contract-alignment/`)
  aligned the RESPONSE side against the vendored contract. Its
  `AUDIT-schema-drift.md` names the input-payload drift surface this plan
  addresses; `DECISIONS.md` records the response-side triage precedent.
- The contract files carry one flat `input_example` per event — an example,
  NOT a schema: no required/optional marking, no types, no conditionality
  (e.g. `PostToolUseFailure.json`'s `error`/`is_interrupt` are present only
  on some dispatches). Technical Decision 1 confronts this gap.
- Phase 3 closes out a 00271 leftover (dual-channel emission retirement); it
  shares no substrate with Phases 1–2 and blocks nothing here, but lives in
  this plan because 00271 is archived.

## Goals

- A per-event statement of the input fields the daemon READS (handlers AND
  the `utils/` helpers that read `hook_input` on their behalf), derived or
  declared, checked against the vendored `input_example`s by a network-free
  QA check (mirroring `check_hook_contract.py`), under the superset rule of
  Technical Decision 1.
- A runtime missing-field advisory IF the static check leaves observable
  residue (per Task 2.1's assessment), with the decision recorded either way
  in this plan's `DECISIONS.md`.
- Newly documented input fields the daemon may want triaged: consumed or
  recorded as deliberate gaps (field list in Task 1.4).

## Non-Goals

- Blocking dispatch on input mismatch — inputs are fail-open by principle.
- Re-vendoring or restructuring the contract files (Plan 00271 owns that).
- Validating NESTED `tool_input` keys (`command`, `file_path`,
  `new_string`, …). The contract examples carry one tool's shape only, so no
  substrate exists to check the ~13 `hook_input.get("tool_input")` read
  sites' nested keys against. This is where much rename risk lives; it is
  deliberately out of scope until a per-tool input substrate exists, and is
  recorded as a known gap in the inventory (Task 1.1).
- StatusLine and the `nitpick` pseudo-event: out-of-contract by 00271 Task
  3.2 / by construction. Their reads (`workspace`, `context_window`, `cost`,
  `effort`, `terminal_columns`, `level`, `count`, `custom_message`, …) are
  excluded from the inventory and can never be findings.
- Project handlers (client repos): the QA sweep cannot reach them. Extending
  `bin/hooks-daemon validate-project-handlers` with the same read-surface
  check (precedent: `core/decision_capability.py` sharing) is recorded as a
  follow-up gap, not done here — the checker primitive built in Task 1.2
  should be written so that extension stays possible.

## Tasks

### Phase 1: Read-surface inventory and static guard

- [x] ✅ **Task 1.1**: Inventory the top-level input fields the daemon reads
  per event (AST scan or declaration table) across
  `src/claude_code_hooks_daemon/handlers/` AND `src/claude_code_hooks_daemon/utils/`
  (`session_helpers.py`, `stop_hook_helpers.py`, `permission_mode.py` read
  `hook_input` on handlers' behalf). Exclude StatusLine and pseudo-event
  (`nitpick`) reads by construction. Record nested `tool_input` reads as a
  known-gap appendix, not as checkable entries.
- [x] ✅ **Task 1.2**: TDD a QA check applying Technical Decision 1's
  superset rule: flag only a field the daemon reads that appears in NO
  vendored `input_example` for that event; never flag absence. Wire into
  `run_all.sh` + `llm_qa.py`; keep the checker primitive reusable by
  `validate-project-handlers` later (see Non-Goals).
- [x] ✅ **Task 1.3**: Triage the newly documented input fields into consumed
  vs recorded-gap: `prompt_id`, `agent_id`/`agent_type`,
  `last_assistant_message`, `permission_suggestions`; `effort` is already
  consumed by StatusLine, so its triage is "already consumed, different
  surface".
- [x] ✅ **Task 1.4**: Add an input-field re-triage step to
  `docs/guides/HOOK-CONTRACT-REFRESH.md` so refreshed examples are diffed
  against the Task 1.1 inventory — without it the input half rots exactly as
  the output half did.

### Phase 2: Runtime advisory (conditional)

- [x] ✅ **Task 2.1**: Assess whether Task 1.2's static check leaves
  observable residue (drift only visible on live dispatches). Record the
  go/no-go decision with reasoning in this plan's `DECISIONS.md`. If no-go,
  Phase 2 ends here. — **Decision: NO-GO** (see `DECISIONS.md`); Tasks
  2.2–2.4 are not executed.
- [ ] ❌ **Task 2.2**: If go: TDD the runtime missing-field detector —
  fail-open, rate-limited, and inside a performance budget: per-dispatch
  overhead measured and kept under 5% of the ~1.8 ms daemon-side dispatch
  time (~0.09 ms), or sampled (first dispatch per event type per session) if
  full checking exceeds it. Include the measurement step in the task's QA.
- [ ] ❌ **Task 2.3**: If go: delivery surface — most events cannot carry
  `additionalContext`, and drift is typically detected on one that cannot
  advise. Record detections to the verdict log (`docs/guides/VERDICT_LOG.md`
  schema) at detection time and surface a per-session summary via a
  SessionStart advisory.
- [ ] ❌ **Task 2.4**: If go: ship the config option with a
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/` manifest entry, a
  `get_claude_md()` verdict, and `get_acceptance_tests()` consideration;
  verify daemon restart (`bin/hooks-daemon restart` → RUNNING) per
  CLAUDE/CodeLifecycle/General.md.

### Phase 3: Plan 00271 dual-channel retirement (independent close-out)

Requires the dogfood daemon on main — a worktree agent cannot run this.

- [ ] ⬜ **Task 3.1**: Sentinel experiment: in a real dogfood session, emit a
  DISTINCT sentinel string on each channel of the two dual emissions —
  SessionStart advisory context on both `systemMessage` and
  `hookSpecificOutput.additionalContext`, and a PermissionRequest deny
  explanation on both `decision.message` and
  `hookSpecificOutput.additionalContext` — then check which sentinel appears
  in the session transcript jsonl and which on the user-visible surface.
  (`scripts/debug_hooks.sh` captures INBOUND events only and cannot answer
  this outbound rendering question.)
- [ ] ⬜ **Task 3.2**: Retirement rule, stated in advance: retire a channel
  ONLY on positive evidence that the surviving channel delivers — never on
  the other channel's failure to appear (absence has innocent explanations).
- [ ] ⬜ **Task 3.3**: On positive evidence, drop the redundant emission and
  update the ONE allowlist entry involved:
  `undocumented-schema-field:PermissionRequest:hookSpecificOutput.additionalContext`
  (`contracts/claude-code-hooks/ALLOWLIST.yaml:25-27`). SessionStart's dual
  emission generates NO allowlist finding — `systemMessage` is documented on
  that event — so there is no SessionStart entry to update; its redundant
  channel is simply removed in code. Verify daemon restart after the change.

## Dependencies

- Depends on: Plan 00271 (Complete) — substrate:
  `contracts/claude-code-hooks/*.json` (`input_example`s),
  `contracts/claude-code-hooks/ALLOWLIST.yaml`,
  `CLAUDE/Plan/Completed/00271-hook-contract-alignment/AUDIT-schema-drift.md`,
  `docs/guides/HOOK-CONTRACT-REFRESH.md`.
- Blocks: nothing.

## Technical Decisions

### Decision 1: Example-vs-schema — superset check only

**Context**: Each contract carries one flat `input_example` — no
required/optional sets, no types, no conditionality (`Stop.json`'s
`stop_hook_active`/`background_tasks`/`session_crons`,
`PostToolUseFailure.json`'s `error`/`is_interrupt` are dispatch-dependent).
Diffing "fields read" against "keys in the example" symmetrically would flag
legitimately conditional fields as drift — false findings in the direction
that matters.
**Options Considered**:

1. Promote examples to a declared per-event input schema with explicit
   `required`/`optional` sets (new contract key, maintained by the refresh
   procedure) — precise, but a large substrate change Plan 00271 owns, and
   ongoing curation cost.
2. Treat the example strictly as a SUPERSET check: flag only a field the
   daemon reads that appears in NO example for that event; never flag
   absence — cheap, zero false positives from conditionality, matches the
   fail-open principle.

**Decision**: Option 2. A read of a field no example has ever shown is the
rename signal we want; absence proves nothing and is never flagged.
**Date**: 2026-08-26

### Decision 2: Phase 3 method — sentinel experiment with positive-evidence rule

**Context**: The dual-channel retirement needs an OUTBOUND rendering
observation; the existing inbound capture tooling cannot provide it, and
absence of rendering has innocent explanations.
**Decision**: Distinct per-channel sentinels in a live dogfood session,
transcript + surface inspection, and retirement only on positive evidence the
surviving channel delivers (Tasks 3.1–3.2).
**Date**: 2026-08-26

## Success Criteria

- [ ] A unit test mutates a vendored `input_example` (renames a field the
  daemon reads) and asserts the Task 1.2 checker reports it.
- [ ] The checker runs in `llm_qa.py all` / `run_all.sh` and is green on the
  current tree.
- [ ] `docs/guides/HOOK-CONTRACT-REFRESH.md` contains the input re-triage
  step.
- [ ] Phase 2 go/no-go decision recorded in `DECISIONS.md`; if go, the
  advisory's overhead measurement is on record and within budget, and no
  blocking behaviour exists on the dispatch path.
- [ ] Phase 3: sentinel evidence recorded in JOURNAL/; redundant channels
  removed only per the positive-evidence rule; ALLOWLIST entry updated.
- [ ] Full QA green; daemon restart verified RUNNING after each src/ change.

## Risks & Mitigations

| Risk                                                                          | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| Superset rule misses a rename where old and new names both appear in examples | Medium | Low         | Refresh-procedure re-triage step (Task 1.4) diffs inventory on every contract refresh          |
| Runtime advisory adds measurable dispatch latency                             | Medium | Medium      | Explicit budget + sampling fallback (Task 2.2); Phase 2 is conditional and can be declined     |
| Phase 3 sentinel never observed (rendering ambiguous)                         | Low    | Medium      | Positive-evidence rule: keep both channels; no retirement on absence                           |
| Nested `tool_input` renames remain invisible                                  | High   | Low         | Explicit Non-Goal + known-gap appendix in the inventory so the gap is on record, not forgotten |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00273-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
