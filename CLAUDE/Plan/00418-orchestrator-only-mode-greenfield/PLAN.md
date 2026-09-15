# Plan 00418: orchestrator only mode greenfield

**Status**: In Progress
**Created**: 2026-09-15
**GitHub Issue**: #14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Restrict the MAIN THREAD to coordination-only tools, so heavy work is delegated
to sub-agents and the lead agent's context stays clean.

**This was built once and deliberately deleted, and the reason it died has since
expired.** Implemented under Plan 00019 at `0da21754`; removed at `b91f0012`
with the message "dead code, superseded by upstream delegate mode". It was never
enabled in any config. The defect was fundamental rather than incidental: hooks
gave no way to tell WHICH agent fired a `PreToolUse`, so enabling it blocked
every agent equally and made agent teams unusable.

That distinction now exists. `agent_id` is delivered to `PreToolUse` **inside a
subagent call**, documented upstream as being there "to distinguish subagent
hook calls from main-thread calls". Enforcement gates on its ABSENCE: absent
means main thread, present means subagent. The field looked absent for months
because it is CONDITIONAL — every `input_example` depicts a main-thread call,
where it is correctly missing — and a sweep of the contract files therefore said
"no" while meaning "not in this example". Ledger 00413 N12 found this and added
the `conditional_input_fields` slot so the next reader is not misled the same
way.

**Greenfield, by owner ruling.** The archived code at
`CLAUDE/Plan/Cancelled/00032-subagent-orchestration-context-preservation/archived-code/`
is not the starting point. It was written against a world where the distinction
did not exist, and was cancelled alongside three sibling plans as won't-do. Read
it for prior art if useful; do not revive it.

## The shape, per the owner's ruling

> we can dog food as a project level handler initially maybe and with a
> WARN/Simulated mode instead of block to start with

Two deliberate constraints, and both are about earning the right to block:

- **Project-level handler first**, in this repository's own
  `.claude/project-handlers/`, not the shipped library. A handler that has never
  run anywhere has no business shipping to every client project, and this repo
  is the only place we can watch it for real.
- **Warn/simulate before block.** The handler reports what it WOULD have denied
  and allows the call. The interesting question is not "does the gate work" but
  "what does it catch that it should not" — and a simulated mode answers that at
  zero cost, where a blocking one answers it by ruining someone's session.

## Goals

- The main thread can be restricted to coordination tools without touching
  sub-agents, proven by a test that a subagent-shaped `PreToolUse` is never
  affected.

- A simulated mode produces a truthful record of what would have been denied,
  and denies nothing.

- The decision to promote to blocking, or to the shipped library, is made from
  that record rather than from confidence.

## Non-Goals

- **Reviving the archived handler.** Owner ruling; see above.

- **Shipping as a library handler in this plan.** Promotion is a later decision
  and needs evidence this plan is designed to produce.

- **Blocking by default, ever.** Even after promotion this stays opt-in. The
  failure mode of a wrong answer here is an agent that cannot work at all.

- **Competing with upstream delegate mode.** If Anthropic fixes the cascade bug
  (`anthropics/claude-code#23447` and siblings), delegate mode may be the better
  answer and this becomes redundant. That is a reason to keep the footprint
  small, not a reason to wait.

## Open question for Phase 2

Which tools count as "coordination". `Task`/`Agent`, `TodoWrite`, `Read` and the
search tools obviously; `Edit`/`Write`/`Bash` obviously not. The awkward middle
is `Bash` for read-only inspection, which is most of what a coordinator actually
does. The simulated run exists to answer this from data rather than taste.

## Tasks

### Phase 1: Simulate

- [x] ✅ **Task 1.1**: Confirm the premise against the live contract before
  writing anything: `agent_id` is present on a subagent `PreToolUse` and absent
  on a main-thread one. If that does not hold, STOP — the plan has no basis.
  Capture with `scripts/debug_hooks.sh` rather than trusting the documentation,
  since trusting a document about this exact field is what cost the first
  attempt.

- [x] ✅ **Task 1.2**: RED first — a main-thread `PreToolUse` (no `agent_id`)
  for a non-coordination tool is flagged; the same call carrying an `agent_id`
  is NOT. The second test is the one that matters: it is the exact failure that
  killed the original handler.

- [x] ✅ **Task 1.3**: The project handler, simulate-only. It records what it
  would have denied and allows every call. No blocking code path exists yet, so
  none can be reached by mistake.

- [x] ✅ **Task 1.4**: Enable it in this repository and gather a real record.
  Live since the merge-day daemon restart; no config entry was needed, since
  project handlers auto-load. 153 would-be denials recorded in the first
  session alone (`bin/hooks-daemon verdicts`, handler `orchestrator-simulate`).

### Phase 2: Decide from the record

- [ ] 🔄 **Task 2.1**: Review what it would have denied, and settle the
  coordination-tool boundary from that evidence. **Review done, boundary not
  settled — and the record is why.** 437 would-be denials in one session:
  Bash 277, Write 122, Edit 33, Artifact 4, CronList 1, ToolSearch 1, and
  `Read` zero. Reads are already exempt, so the boundary is not too tight in
  the way first suspected. But Bash is 63% of the total and spans both sides of
  the line — `git status` and a QA run are coordination, and both are Bash —
  while the verdict record carries `tool` without the command. The evidence
  cannot separate them. Owner input needed: record enough to classify Bash, or
  draw the boundary on `Write`/`Edit` alone, where 155 calls need no
  interpretation at all.

- [ ] ⬜ **Task 2.2**: Owner decision on promoting to blocking, and separately
  on promoting to the shipped library. Either may be "no".

## Success Criteria

- [x] ✅ A subagent's tool call is provably unaffected, by test. This is the
  exact failure that killed the original attempt, so it is the test the slice
  was built around rather than one added afterwards.

- [ ] ⬜ A simulated run over real sessions in this repository produces a record
  of would-be denials, and that record is what the boundary decision cites.

- [ ] ⬜ Nothing is blocked by this plan. Blocking is a later, separate decision.

- [ ] ⬜ Full QA passes, the daemon restarts, CI green.

## Delivery & Milestones

- From issue #14, open since 2026-01-27 and correctly parked until now: the
  capability it named as its unblocking condition arrived, and nothing was
  watching for it. That is the argument issue #24 makes for an upstream
  monitoring process.
