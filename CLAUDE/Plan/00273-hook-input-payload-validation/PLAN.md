# Plan 00273: Hook Input Payload Validation

**Status**: Not Started
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
that substrate: derive per-event input expectations (at minimum, the fields
handlers actually read), check dispatched payloads against them, and surface
drift as an advisory rather than a block (inputs must stay fail-open).

## Goals

- A per-event statement of the input fields the daemon's handlers READ,
  derived or declared, diffed against the vendored `input_example`s by a QA
  check (network-free, mirroring `check_hook_contract.py`).
- A runtime advisory (rate-limited) when a dispatched payload lacks a field a
  matching handler reads — the observable symptom of an input rename.
- Newly documented input fields the daemon may want (`prompt_id`, `effort`,
  `agent_id`/`agent_type`, `last_assistant_message`, `permission_suggestions`)
  triaged: consumed or recorded as deliberate gaps.

## Non-Goals

- Blocking dispatch on input mismatch — inputs are fail-open by principle.
- Re-vendoring or restructuring the contract files (Plan 00271 owns that).

## Tasks

### Phase 1: Design and guard

- [ ] ⬜ **Task 1.1**: Inventory the input fields each handler reads (AST scan
  or declaration table) and record them per event.
- [ ] ⬜ **Task 1.2**: TDD a QA check diffing that inventory against the
  vendored `input_example`s; wire into `run_all.sh` + `llm_qa.py`.
- [ ] ⬜ **Task 1.3**: Runtime missing-field advisory (rate-limited,
  fail-open), if Task 1.2's static check leaves observable residue.
- [ ] ⬜ **Task 1.4**: Triage the newly documented input fields listed in the
  Goals into consumed vs recorded-gap.
- [ ] ⬜ **Task 1.5**: Retire the Plan 00271 dual-channel emissions once live
  rendering is observed on the installed Claude Code: SessionStart advisory
  context currently goes out on BOTH systemMessage and
  hookSpecificOutput.additionalContext (the full advisory blob duplicated),
  and a PermissionRequest deny explanation on BOTH decision.message and
  hookSpecificOutput.additionalContext. Observe which channel actually
  renders/delivers, keep that one, drop the other, and update the
  corresponding ALLOWLIST.yaml entries.

## Success Criteria

- [ ] An input-field rename in a future Claude Code release is surfaced by
  the QA check or the runtime advisory, not by handlers silently going dark.
- [ ] Full QA green; no blocking behaviour added to the dispatch path.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00273-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
