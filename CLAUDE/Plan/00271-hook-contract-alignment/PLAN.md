# Plan 00271: Hook Contract Alignment

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's idea of the Claude Code hooks contract lives implicitly in
`src/claude_code_hooks_daemon/core/response_schemas.py`,
`core/hook_result.py` (`REFUSAL_CAPABLE_EVENTS` and the per-event
formatters) and `constants/events.py` — and it has rotted. An audit against
the raw hooks documentation (Claude Code 2.1.246) found **21 drifts: 9
load-bearing, 8 moderate, 4 cosmetic** — full matrix with file:line
citations in [AUDIT-schema-drift.md](AUDIT-schema-drift.md). Load-bearing:
documented capabilities the daemon cannot express (`updatedInput`, `defer`,
UserPromptSubmit and PreCompact blocking), tokens it emits that the
contract never defines (top-level `decision: "deny"`, PermissionRequest
`behavior: "ask"`), a deny reason routed into an undocumented field, and a
documented event (`DirectoryAdded`) missing from the catalogue.

The mandate is DBF-first (Defence Before Fix, Engineering Principle 15):
the defect worth fixing is the **missing guard** that let the schemas drift
invisibly for many Claude Code versions. Phase 1 therefore builds the guard
— a vendored, tracked copy of the documented contract plus a network-free
QA check that diffs the daemon's three sources of truth against it — and
the guard must go RED on the current tree, enumerating the audit's drifts.
Phase 2 then fixes the drifts the guard reports, so every fix flips a red
check green and can never silently regress. Phase 3 burns down the
remaining allowlisted gaps and coordinates with Plan 00170's dormant
Phase 4 (drift detection), which this guard is designed to underpin.

A lesson from the audit is itself a deliverable: a summarised fetch of the
docs **fabricated contract details** (an invented `permissionDecision: "escalate"` value), so the refresh procedure must mandate raw-markdown
fetch with verification of every extracted claim — never a trusted
automated summary.

## Goals

- A tracked, vendored per-event contract (`contracts/claude-code-hooks/`)
  capturing documented output fields, decision tokens and input examples,
  with provenance metadata (docs URL, fetch date, last-audited Claude Code
  version).
- A network-free QA check, wired into `scripts/qa/run_all.sh` and
  `llm_qa.py`, that diffs `response_schemas.py`, `REFUSAL_CAPABLE_EVENTS`,
  `can_block` and the event catalogue against the vendored contract, with a
  reasoned allowlist for deliberate capability gaps.
- A SessionStart advisory that fires when the installed Claude Code version
  exceeds the last-audited version, so the vendored copy cannot rot
  silently.
- A documented refresh procedure encoding the raw-fetch-only lesson.
- All 9 load-bearing drifts fixed, each closing a red guard finding, with
  TDD and daemon-restart verification per fix.
- Truth-changes/config-changes manifests staged for any fix that changes
  what client projects observe.

## Non-Goals

- Expressing every documented field. Capability gaps nothing needs
  (`classifierContext`, `updatedMCPToolOutput`, Elicitation events, …)
  stay allowlisted with reasons; the allowlist IS the record.
- An input-payload validation layer. The vendored contract stores input
  examples per event so the guard's data model is ready for one, but
  building input validation is future work (candidate follow-up plan).
- Automated extraction of the contract from the docs. The fabrication
  incident is the argument: extraction is a verified manual/agent step.
- Live behavioural verification of every documented field against a
  running Claude Code. Only fixes whose observable behaviour is uncertain
  (SessionStart `systemMessage` routing) get a live-verification task.
- Plan 00170 Phase 4 itself (whole-event-coverage drift detection); this
  plan provides the vendored substrate it needs and records the interface.

## Context & Background

- Audit: [AUDIT-schema-drift.md](AUDIT-schema-drift.md) (this folder) —
  full drift matrix, DBF options analysis, suggested fix order.
- Docs source of truth: https://code.claude.com/docs/en/hooks.md (raw
  markdown; the summarising fetch layer fabricates).
- Plan 00170 (universal hook coverage) Phase 4 is dormant, scoped to
  detecting NEW events appearing in Claude Code; this plan's vendored
  contract + staleness advisory covers the "docs changed" half and Phase 4
  should consume `META.json` rather than invent a second provenance record.
- Plan 00265 covered compile-time handler-base typing; this plan is the
  runtime/wire-format complement. Plan 00270 (bash safe-mode forcer) is
  blocked on the PreToolUse `updatedInput` drift (Task 2.5).
- Dedupe scout verdict: proceed as filed; overlap with 00170 is
  coverage-vs-correctness, with 00265 compile-time-vs-runtime.

## Tasks

### Phase 1: The Guard (DBF — before any fix)

- [x] ✅ **Task 1.1**: Vendor the documented contract as tracked JSON under
  `contracts/claude-code-hooks/` — one file per documented event (30
  events incl. `DirectoryAdded`), each capturing: documented top-level
  output fields, `hookSpecificOutput` fields with enums (e.g.
  `permissionDecision`: allow/deny/ask/defer), blocking mechanism
  (top-level `decision: "block"` / nested behaviour / none), fields the
  docs say are discarded (e.g. PreCompact `systemMessage`), and a
  representative input example. Source every claim from a fresh raw fetch
  of hooks.md, cross-checked against the audit's contract table.
- [x] ✅ **Task 1.2**: Write `contracts/claude-code-hooks/META.json`: docs
  URL, fetch date, docs byte size/sha256, `last_audited_claude_code_version`
  (2.1.246 or the version current at execution), and a pointer to the
  refresh procedure doc.
- [x] ✅ **Task 1.3**: TDD the contract-diff checker
  (`scripts/qa/check_hook_contract.py` + a supporting module with unit
  tests). Network-free. Per event it asserts:
  - every field/enum value in the daemon's bespoke schema exists in the
    vendored contract (catches inventions like `guidance` being presented
    as contractual);
  - every decision capability the daemon claims (`REFUSAL_CAPABLE_EVENTS`
    entries, `can_block=True`, serialiser output tokens) is documented for
    that event;
  - every documented capability/field the daemon does NOT express is
    either allowlisted or reported as a finding;
  - every vendored event name exists in `constants/events.py` (wired or
    tracked in `EXPECTED_UNWIRED`) — this alone catches `DirectoryAdded`.
- [x] ✅ **Task 1.4**: Design and implement the reasoned allowlist
  (tracked file beside the contracts, e.g.
  `contracts/claude-code-hooks/ALLOWLIST.yaml`): each entry names the
  event, the field/token, the reason, and a linked plan/task; the checker
  FAILS on an allowlist entry whose drift no longer exists (stale
  entries rot too).
- [x] ✅ **Task 1.5**: Wire the checker into `scripts/qa/run_all.sh` and
  `scripts/qa/llm_qa.py` as a first-class QA check.
- [x] ✅ **Task 1.6**: RED verification — run the checker against the
  current tree and confirm it reports every load-bearing drift from the
  audit (items 1–9) plus the moderate/cosmetic ones not yet allowlisted.
  Record the red output in this plan's JOURNAL/. Seed the allowlist with
  ALL current findings, each entry linked to its Phase 2/3 task — so the
  QA suite passes between now and each fix while every gap stays recorded.
- [x] ✅ **Task 1.7**: TDD the contract-staleness SessionStart advisory
  (sibling of `version_check`): when the installed Claude Code version
  exceeds `META.json`'s `last_audited_claude_code_version`, advise running
  the refresh procedure. Enable it in `.claude/hooks-daemon.yaml` and
  `.example`, register constants, daemon restart verification.
- [x] ✅ **Task 1.8**: Write the refresh procedure doc
  (`contracts/claude-code-hooks/REFRESH.md`): raw fetch of hooks.md to a
  scratch file (never a summarising fetch layer — record the fabrication
  incident as the rationale), manual/agent extraction with verbatim
  verification of every changed claim, update contract JSON + META.json,
  re-run the checker, triage new findings into allowlist entries or fix
  tasks.

### Phase 2: Fix the Load-Bearing Drifts (each flips a red finding green)

Fix order follows the audit's recommendation: wrong claims first (they
gate what project handlers are told is possible), then missing
capabilities. Every task: TDD (failing test first, keyed to the vendored
contract), full QA, daemon restart verification, remove the corresponding
allowlist entry so the guard enforces the fix.

- [x] ✅ **Task 2.1**: Three-way reconciliation of claim tables (audit
  items 3, 5, 7, 9). Make `REFUSAL_CAPABLE_EVENTS`
  (`core/hook_result.py:66-82`), `can_block` in `constants/events.py`, and
  the schemas agree with the vendored contract for every event. Includes
  removing the undefined PermissionRequest ASK claim
  (`hook_result.py:76-81`, `response_schemas.py:117`).
- [x] ✅ **Task 2.2**: UserPromptSubmit blocking (audit item 5): top-level
  `decision: "block"` + `reason` in schema
  (`response_schemas.py:183-198`) and serialiser; add UserPromptSubmit to
  `REFUSAL_CAPABLE_EVENTS[DENY]`; coherence with `can_block=True`
  (`constants/events.py:129-136`).
- [x] ✅ **Task 2.3**: Correct block serialisation for the six wired-extra
  blockable events (audit item 9: PostToolBatch, PostToolUseFailure,
  TaskCreated, ConfigChange, UserPromptExpansion, TeammateIdle): a DENY
  must emit the documented mechanism (top-level `decision: "block"` +
  `reason`, or `continue: false` where that is the documented form), not
  the undefined `{"decision": "deny"}` from
  `_format_system_message_response` (`hook_result.py:518-521, 704-710`).
  Extend `REFUSAL_CAPABLE_EVENTS` so drops on these events are no longer
  silent; tighten their fail-open schemas enough to reject the old token.
- [x] ✅ **Task 2.4**: PreCompact blocking (audit item 7): schema
  (`response_schemas.py:171-177`) and serialiser support top-level
  `decision: "block"`; reconcile with `can_block=True`
  (`constants/events.py:138-145`); document that PreCompact
  `systemMessage` is discarded (dead-letter) per contract.
- [x] ✅ **Task 2.5**: PreToolUse `updatedInput` + `defer` (audit items 1,
  2): extend `PRE_TOOL_USE_SCHEMA` (`response_schemas.py:26-40`), add a
  `HookResult` field and formatter support
  (`hook_result.py:523-545`), add `Decision.DEFER`
  (`hook_result.py:18-24`) with correct capability-table and
  handler-base treatment. Unblocks Plan 00270 — notify that plan's task
  list on completion.
- [x] ✅ **Task 2.6**: PermissionRequest deny surface (audit items 3, 4):
  route the deny reason into the documented `decision.message`
  (replacing the undocumented `additionalContext` routing at
  `hook_result.py:639-652`); add `updatedPermissions` and `interrupt` to
  the schema (`response_schemas.py:105-135`) and result model, or
  allowlist them with linked follow-up if deliberately unsupported.
- [x] ✅ **Task 2.7**: SessionStart live verification then migration
  (audit item 6): use `scripts/debug_hooks.sh` against the installed
  Claude Code to establish what `systemMessage` vs
  `hookSpecificOutput.additionalContext` actually do on SessionStart;
  then migrate schema (`response_schemas.py:143-149`) and serialiser so
  advisory context reaches Claude via the documented
  `hookSpecificOutput.additionalContext`, keeping `systemMessage` only
  for genuinely user-facing warnings. `initialUserMessage`,
  `sessionTitle`, `watchPaths`, `reloadSkills` become expressible or
  allowlisted with reasons.
- [x] ✅ **Task 2.8**: Add `DirectoryAdded` to `constants/events.py`
  (audit item 8) per the file's own tracked-gap rule (`wired=False` +
  `EXPECTED_UNWIRED` if not wired now).
- [x] ✅ **Task 2.9**: Client-observable-change manifests: for each Phase 2
  fix that changes what a client project observes (new decision
  capabilities on events, PermissionRequest deny reason moving fields,
  SessionStart context channel change), stage
  `CLAUDE/UPGRADES/UNRELEASED/truth-changes/` and/or
  `UNRELEASED/config-changes/` entries per their READMEs.

### Phase 3: Burn-Down, Coordination and Docs

- [x] ✅ **Task 3.1**: Moderate-drift triage: for each remaining
  allowlisted gap (PostToolUse `updatedToolOutput`/
  `updatedMCPToolOutput`/`classifierContext`, universal fields incl.
  `terminalSequence`, UserPromptSubmit `sessionTitle`/
  `suppressOriginalPrompt`, dead-letter `systemMessage` events,
  SubagentStart/Setup context shape) decide fix-now vs keep-allowlisted;
  implement the fix-now set with TDD; every kept entry ends with a
  reason and a linked plan/task.
- [x] ✅ **Task 3.2**: Cosmetic clean-up: comment `guidance` as a
  daemon-internal extension (not contractual) where declared in schemas;
  require `reason` alongside Stop `decision: "block"`
  (`hook_result.py:604-607`); comment StatusLine as out-of-contract by
  design.
- [x] ✅ **Task 3.3**: Plan 00170 Phase 4 coordination note: append to
  Plan 00170's PLAN.md (Dependencies/notes) that its dormant drift
  detection should build on `contracts/claude-code-hooks/META.json` and
  the checker from this plan, not a parallel mechanism; record the
  interface (files, checker entry point) there.
- [x] ✅ **Task 3.4**: Documentation: CLAUDE/HANDLER_DEVELOPMENT.md and
  docs/guides/HANDLER_REFERENCE.md updated for any newly expressible
  decisions/fields; CLAUDE/ARCHITECTURE.md gains a short section naming
  the vendored contract as the source of truth for wire shapes.
- [x] ✅ **Task 3.5**: Candidate follow-up plan filed (or explicitly
  declined in this plan's JOURNAL/) for input-payload validation, using
  the vendored input examples (audit "Input-payload drift surface").

## Dependencies

- Related: Plan 00170 (dormant Phase 4 builds on this guard), Plan 00265
  (compile-time complement, Complete), Plan 00270 (blocked on Task 2.5).
- Blocks: Plan 00270's inject/command-rewrite mode.

## Technical Decisions

Full reasoning with options considered: [DECISIONS.md](DECISIONS.md).
Summary:

1. **Vendored contract = per-event JSON + META.json** — small refresh
   diffs, missing-event-file is itself a finding, stdlib-loadable; the
   drifted `response_schemas.py` cannot be its own reference.
2. **Reasoned, self-cleaning allowlist** — every entry carries a reason
   and a linked plan/task; an entry whose drift no longer exists FAILS the
   check (stale allowlists rot like stale schemas).
3. **Staleness advisory, never auto-refresh** — extraction from prose docs
   must be verified, not trusted (the summarising fetch layer fabricated
   `permissionDecision: "escalate"`); a SessionStart advisory triggers the
   human/agent REFRESH.md procedure.
4. **The QA check is network-free** — it diffs daemon sources against the
   tracked vendored contract only; freshness is the advisory's job.
5. **Guard lands red-then-allowlisted** — Task 1.6's RED run proves
   coverage, then seeded allowlist entries (each linked to a fix task)
   keep QA green while recording every gap; each fix deletes its entry.

## Success Criteria

- [ ] Task 1.6's RED run reports every load-bearing drift the audit
  enumerates (items 1–9), before any fix lands.
- [ ] `scripts/qa/llm_qa.py all` includes and passes the contract check;
  the checker fails on: an undocumented schema field/token, an
  unallowlisted documented gap, a stale allowlist entry, a documented
  event absent from the catalogue.
- [ ] All 9 load-bearing drifts fixed with TDD; their allowlist entries
  removed; daemon restart verified after each handler/core change.
- [ ] Staleness advisory fires when installed Claude Code version exceeds
  the last-audited version (unit-tested; observed once live).
- [ ] REFRESH.md exists and encodes the raw-fetch-only rule with the
  fabrication incident as rationale.
- [ ] Plan 00170 carries the coordination note; Plan 00270 notified that
  `updatedInput` is expressible.
- [ ] Truth-changes/config-changes manifests staged for every
  client-observable change.
- [ ] Full QA green; acceptance impact assessed for changed handlers.

## Risks & Mitigations

| Risk                                            | Impact | Probability | Mitigation                                                                   |
| ----------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------- |
| Docs wrong/ahead of the installed binary        | High   | Medium      | Live verification (2.7) where uncertain; META.json records the docs version  |
| Tightened schemas break client project handlers | Medium | Medium      | 2.3 rejects only the undefined token; truth-changes manifest (2.9) notifies  |
| Contract extraction fabricates                  | High   | Low         | Raw fetch only; each claim cross-checked vs audit + raw markdown; per-event  |
| Allowlist becomes a dumping ground              | Medium | Medium      | Entries need a linked plan/task; stale entries FAIL; Phase 3 burn-down pass  |
| SessionStart migration regresses advisories     | High   | Low         | Verify-live-first in 2.7; acceptance-test SessionStart advisories pre-commit |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00271-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Guard red-run verified at <commit-hash>
- Load-bearing drifts closed at <commit-hash>
