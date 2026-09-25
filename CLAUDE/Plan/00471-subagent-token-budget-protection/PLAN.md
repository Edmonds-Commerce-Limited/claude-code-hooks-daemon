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
- [ ] 🔄 **Task 1.2**: Owner picks the levers and thresholds from the ranked
  design.
  - Decided: lever L1 (lower `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which is 600000
    in the container env) is dropped. About 230k is too tight for the
    orchestrator, and Claude Code has no subagent-only compaction setting:
    `sub-agents.md` says subagents compact "using the same logic as the main
    conversation". L2, the daemon's subagent context budget, is the
    subagent-only substitute. It forces a handoff and never touches the
    orchestrator.

### Phase 2: Build

- [ ] ⬜ **Task 2.1**: Implement the chosen levers, TDD, with a dogfood run.

## Success Criteria

- [ ] A session in this repository cannot run a subagent past the
  configured context budget without the daemon intervening in a way that
  is measured and recorded.
- [ ] The intervention never loses an agent's work: it forces a handoff
  report, not a kill.

## Delivery & Milestones

- Plan filed; brainstorm dispatched.
