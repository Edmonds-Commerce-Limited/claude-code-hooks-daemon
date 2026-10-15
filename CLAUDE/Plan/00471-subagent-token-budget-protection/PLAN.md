# Plan 00471: subagent token budget protection

**Status**: In Progress
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

- [ ] ⬜ **Task 2.0**: Transcript readers: the tail reader, the offset cache
  and the agent-transcript resolver.
- [ ] ⬜ **Task 2.1**: Spend ledger (L6) in `subagent_cache_aggregator`, and
  the `hooks-daemon spend` CLI.
- [ ] ⬜ **Task 2.2**: Subagent context budget (L2): soft advisory on; hard
  mode built, tested and shipped off; SubagentStop handoff gate; the
  `budget: <N>k` dispatch override.
- [ ] ⬜ **Task 2.3**: Resume guard (L3): deny in this repo at 150k, advise
  by default for clients.
- [ ] ⬜ **Task 2.4**: Live count and five-hour percentage (L4, L5),
  advisory only.
- [ ] ⬜ **Task 2.5**: Status segment (L7).
- [ ] ⬜ **Task 2.6**: Review-round advisory (L9).
- [ ] ⬜ **Task 2.7**: Docs, config manifest, holding-area entry, baseline
  copy and the dogfood run.

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

## Success Criteria

- [ ] `hooks-daemon spend` prints, for the live session, per-agent
  `requests`, `max_ctx`, `mean_ctx`, ite, `compactions`, `inbound_messages`
  and the plan key, plus the `compact_boundary` distribution and the
  unmeasured count; a golden-output test covers it from fixture transcripts.
- [ ] The tail reader's read count is the same for a 1 MB and an 8 MB
  fixture, and the offset cache gives the same totals after append, truncate
  and inode replacement.
- [ ] In a SUB-scoped PreToolUse at or above `soft_tokens`, the budget
  handler injects `additionalContext` exactly once per band; the acceptance
  test shows it through a real subagent in this repo.
- [ ] With `hard_tokens` set in a test config, every tool outside the
  allowlist is denied with a reason naming the handoff path, the
  allowlisted writes, commit and SendMessage pass, the reason escalates
  after 3 consecutive denials, and SubagentStop is blocked until the handoff
  file exists; the shipped config has `hard_tokens: null` everywhere.
- [ ] An unreadable or missing agent transcript allows the call and writes
  one `unmeasured` verdict per `(agent_id, reason)`; the spend report shows
  the count.
- [ ] A `budget: <N>k` line in a named dispatch's prompt raises that agent's
  budget, clamped to `max_override_tokens`, and is a ledger row; an unnamed
  dispatch's line is ignored.
- [ ] The resume guard denies a SendMessage to a stopped, cold,
  at-or-above-threshold agent under this repo's config, allows warm,
  running, overridden and unresolvable targets, and the deny reason names
  the last report file when one exists.
- [ ] The live count excludes `end_turn` agents and reconciles against a
  Stop payload's `background_tasks[]`; the concurrency and five-hour
  advisories fire at their thresholds and never deny; a stale sidecar draws
  nothing.
- [ ] The status segment renders spend, live count, largest live context
  and unmeasured count from fixture sidecars.
- [ ] The review-round counter advises at round 4 on the same key and is
  silent below it.
- [ ] `docs/guides/HANDLER_REFERENCE.md` and the config-changes manifest
  describe every new handler and option; the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/`) records this plan's release-bound
  consequences (new handlers, new config keys, the new CLI command).
- [ ] `untracked/scratch/p471_spend.json` is copied into
  `subagent-reports/` as the baseline, and the dogfood journal entry cites a
  `hooks-daemon spend` run and a soft-advisory verdict from a real session.
- [ ] Targeted QA is green on the work branch; the coordinator's full gate is
  green before merge.

## Delivery & Milestones

- Plan filed; brainstorm dispatched.
