# Plan 00471: subagent token budget protection

**Status**: Complete
**Created**: 2026-09-25
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**Owner request:** find out how the hooks daemon itself can protect a
session against a subagent "token inferno", and track the work here. It
follows from ledger 00466 N62.

**What happened (measured, not assumed).** A coordinated run hit the 5-hour
usage limit.

- The session held 584 subagent transcripts, about 1 GB.
- The largest agents auto-compacted only at about 567k to 581k tokens of
  context. Plan 464's implementer compacted 9 times.
- A message to a finished agent resumes its whole history. One resume carried
  2,374 prior messages.
- About nine Opus agents ran at once for hours, and review rounds on one
  branch reached nine.

Every tool call re-reads the agent's context, so the cost is roughly
(average context) x (tool calls) x (concurrent agents). Nothing in the
daemon observes or bounds any of those three factors today.

**Why the daemon is the right place.** Hook inputs carry `transcript_path`,
`agent_id`/`agent_type` and the tool being called. The transcript records
per-turn `usage`, including cache-read tokens, and `compact_boundary` events.
The daemon already sees every Agent, SendMessage and tool call. So it can
measure spend and gate it deterministically, which prompt-level advice alone
cannot guarantee.

**Sibling plan.** [Plan 00472](../00472-subagent-model-tier-selection/PLAN.md)
governs WHICH model a subagent runs on, including the fan-out of a
`Workflow` script (60 parallel top-tier agents was the owner's case). This
plan bounds how MUCH context each agent spends. The two stay cross-linked
rather than merged, so each keeps its own owner decisions.

## Goals

- A brainstorm, grounded in what hook inputs and transcripts actually expose,
  of every daemon-side lever: measure, advise, deny, report.
- A ranked design for the chosen levers, with thresholds, config keys, the
  default for client projects, and failure modes such as lockout or losing
  an agent's work.
- Implementation of the chosen levers, TDD, with a dogfood proof in this
  repository.

## Non-Goals

- Changing Claude Code itself, or the owner's user settings.json. The
  autocompact threshold is the owner's setting; this plan may recommend a
  value, backed by evidence.
- Billing or API-account integration.

## Tasks

### Phase 1: Brainstorm and design

- [x] ✅ **Task 1.1**: Brainstorm the levers, from the evidence
  (subagent-reports/).
- [x] ✅ **Task 1.2**: Owner picks the levers and thresholds from the ranked
  design. Decided by Fable ruling (owner-delegated), recorded in
  [RULINGS-fable.md](RULINGS-fable.md); the rulings are not the owner's.
  - Decided: lever L1 (lower `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which is 600000
    in the container env) is dropped. About 230k is too tight for the
    orchestrator, and Claude Code has no subagent-only compaction setting:
    `sub-agents.md` says subagents compact "using the same logic as the main
    conversation". L2, the daemon's subagent context budget, is the
    subagent-only substitute. It forces a handoff and never touches the
    orchestrator.

### Phase 2: Build

The build scope of [RULINGS-fable.md](RULINGS-fable.md) section 2, in order.
Every gate that cannot measure fails open with a recorded `unmeasured`
verdict.

- [x] ✅ **Task 2.0** (35f174bec): Transcript readers: the tail reader, the
  offset cache and the agent-transcript resolver.
- [x] ✅ **Task 2.1** (ea7fab202): Spend ledger (L6) in
  `subagent_cache_aggregator`, and the `hooks-daemon spend` CLI.
- [x] ✅ **Task 2.2** (2ca8a05c4): Subagent context budget (L2): soft
  advisory on; hard mode built, tested and shipped off; SubagentStop handoff
  gate; the `budget: <N>k` dispatch override.
- [x] ✅ **Task 2.3** (e0c1d55b0): Resume guard (L3): deny in this repo at
  150k, advise by default for clients.
- [x] ✅ **Task 2.4** (d50f10655): Live count and five-hour percentage (L4,
  L5), advisory only.
- [x] ✅ **Task 2.5** (d4425ac43): Status segment (L7).
- [x] ✅ **Task 2.6** (05b87417c): Review-round advisory (L9).
- [x] ✅ **Task 2.7**: Docs, config manifest, holding-area entry (release
  note 078), baseline copy
  (`subagent-reports/260925-p471-spend-baseline.json`, identical to
  `untracked/scratch/p471_spend.json`) and the dogfood run (JOURNAL
  26-10-16). The Q5 payload capture is moved to Deferred.

## Deferred

- **L2 hard mode in this repo** (`hard_tokens: 250k`): left to the owner.
  The ruling recommends it once the dogfood run shows the soft band firing
  with zero unmeasured events.
- **L4 and L5 deny modes**: a follow-up plan, opened only if the ledger shows
  the live count matching `background_tasks[]` and the five-hour percentage
  being hit.
- **L8 CLAUDE.md diet**: a follow-up plan, whose first deliverable is the
  blocked-call rate from `verdicts.jsonl`.
- **L1 autocompact window**: dropped (Task 1.2). The spend report carries the
  `compact_boundary` distribution so the owner can revisit.
- **A savings figure as a closing criterion**: dropped. Re-measure later
  with `hooks-daemon spend` against the baseline.
- **Q5 subagent PreToolUse payload capture**: not done (`payload_capture`
  stays off and `untracked/payload-capture/` is empty). The live soft
  advisory (JOURNAL 26-10-16) shows the resolver finding a real subagent's
  transcript from a real payload, so the capture is now confirmation only.

## Success Criteria

Test evidence: every test named below passed on main at b1d6397f4 (pytest
by path, run during closure).

- [x] `hooks-daemon spend` prints, for the live session, per-agent
  `requests`, `max_ctx`, `mean_ctx`, ite, `compactions`, `inbound_messages`
  and the plan key, plus the `compact_boundary` distribution and the
  unmeasured count; a golden-output test covers it from fixture transcripts.
  Tests: `tests/unit/daemon/test_spend_report.py::TestReport::test_golden_by_agent`,
  `::test_golden_by_plan`, `::test_no_agents_and_unmeasured_count`. Live: a
  run over the coordinator's 450-agent session (JOURNAL 26-10-16).
- [x] The tail reader's read count is the same for a 1 MB and an 8 MB
  fixture, and the offset cache gives the same totals after append, truncate
  and inode replacement. Tests:
  `tests/unit/utils/test_transcript_tail.py::TestReadTail::test_read_count_does_not_scale_with_file_size`;
  `tests/unit/utils/test_transcript_spend.py` `test_append_parses_only_new_bytes`,
  `test_truncate_resets`, `test_inode_replacement_resets`,
  `test_same_totals_as_a_fresh_full_scan`.
- [x] In a SUB-scoped PreToolUse at or above `soft_tokens`, the budget
  handler injects `additionalContext` exactly once per band; the acceptance
  test shows it through a real subagent in this repo. Tests:
  `tests/unit/handlers/pre_tool_use/test_subagent_context_budget.py::TestSoftBand::test_advises_once_per_band`,
  `::test_once_per_band_survives_a_new_instance`, `TestShape::test_scope_is_sub`.
  Live: one injection into `p472-tier-advisor` at 153,883 tokens (JOURNAL
  26-10-16).
- [x] With `hard_tokens` set in a test config, every tool outside the
  allowlist is denied with a reason naming the handoff path, the
  allowlisted writes, commit and SendMessage pass, the reason escalates
  after 3 consecutive denials, and SubagentStop is blocked until the handoff
  file exists; the shipped config has `hard_tokens: null` everywhere. Tests:
  `test_subagent_context_budget.py::TestHardBand` (5 tests),
  `tests/unit/handlers/subagent_stop/test_subagent_handoff_gate.py::test_over_hard_without_handoff_is_blocked_until_written`,
  `TestShape::test_shipped_defaults`; `hard_tokens: null` in
  `.claude/hooks-daemon.yaml` and the v3.70.0 config-changes manifest.
- [x] An unreadable or missing agent transcript allows the call and writes
  one `unmeasured` verdict per `(agent_id, reason)`; the spend report shows
  the count. Tests: `test_subagent_context_budget.py::TestUnmeasured` (2
  tests), `test_spend_report.py::TestReport::test_no_agents_and_unmeasured_count`.
  Live: three `unmeasured` records, and the spend report prints 3.
- [x] A `budget: <N>k` line in a named dispatch's prompt raises that agent's
  budget, clamped to `max_override_tokens`, and is a ledger row; an unnamed
  dispatch's line is ignored. Tests:
  `tests/unit/handlers/pre_tool_use/test_agent_dispatch_recorder.py::TestBudgetOverride::test_budget_line_is_recorded_and_ledgered`;
  `test_subagent_context_budget.py::TestOverride` (4 tests, including
  `test_override_is_clamped` and `test_unnamed_agent_has_no_override`).
- [x] The resume guard denies a SendMessage to a stopped, cold,
  at-or-above-threshold agent under this repo's config, allows warm,
  running, overridden and unresolvable targets, and the deny reason names
  the last report file when one exists. Tests:
  `tests/unit/handlers/pre_tool_use/test_resume_guard.py::TestDecision`
  (`test_stopped_cold_large_is_denied_naming_the_route`, `test_warm_is_allowed`,
  `test_running_is_never_gated`, `test_override_prefix_allows_and_is_recorded`,
  `test_unresolvable_target_fails_open`); this repo runs `mode: deny` at
  150,000.
- [x] The live count excludes `end_turn` agents and reconciles against a
  Stop payload's `background_tasks[]`; the concurrency and five-hour
  advisories fire at their thresholds and never deny; a stale sidecar draws
  nothing. Tests:
  `tests/unit/handlers/pre_tool_use/test_spawn_rate_advisor.py` (`TestConcurrency`,
  `TestFiveHour`, including `test_reconciled_by_a_stop_payload`,
  `test_never_denies`, `test_stale_reading_draws_nothing`),
  `test_transcript_tail.py::TestReadTail::test_end_turn_as_last_conversational_record_is_stopped`.
- [x] The status segment renders spend, live count, largest live context
  and unmeasured count from fixture sidecars. Tests:
  `tests/unit/handlers/status_line/test_spend_meter.py` (8 tests).
- [x] The review-round counter advises at round 4 on the same key and is
  silent below it. Test:
  `tests/unit/handlers/pre_tool_use/test_review_round_advisor.py::test_advises_at_round_four_on_the_same_key`.
- [x] `docs/guides/HANDLER_REFERENCE.md` and the config-changes manifest
  describe every new handler and option; the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/`) records this plan's release-bound
  consequences (new handlers, new config keys, the new CLI command): release
  note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/078-subagent-spend-ledger-budget-and-resume-guard.md`
  and `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.70.0.yaml`.
- [x] `untracked/scratch/p471_spend.json` is copied into
  `subagent-reports/` as the baseline, and the dogfood journal entry cites a
  `hooks-daemon spend` run and a soft-advisory verdict from a real session.
  Baseline: `subagent-reports/260925-p471-spend-baseline.json`. Journal:
  26-10-16, "dogfood run".
- [ ] Targeted QA is green on the work branch; the coordinator's full gate is
  green before merge. The coordinator's full gate runs in the release
  (RELEASING.md Step 1b); left for the coordinator to tick.

## Delivery & Milestones

- Plan filed; brainstorm dispatched.
- Built per the Fable rulings and merged to main in 2c12a3778; dogfood run
  and closure in ab46984cf.
