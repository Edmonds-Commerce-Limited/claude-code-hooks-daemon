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

## Open question for Phase 2 — ANSWERED

Which tools count as "coordination". The awkward middle was `Bash` for
read-only inspection, which is most of what a coordinator actually does, and
the simulated run answered it from data rather than taste: **`Bash` cannot be
a denial surface at all**, because on the real record 93% of calls run several
commands at once and 22% straddle the boundary inside one invocation. The
denial surface is `Write`/`Edit`/`NotebookEdit`; `Bash` stays record-only with
its command-head label. See Task 2.1.

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

- [x] ✅ **Task 2.1**: Review what it would have denied, and settle the
  coordination-tool boundary from that evidence. **Settled: the boundary is
  `Write`/`Edit`/`NotebookEdit` on the main thread; `Bash` is never denied;
  the plan tree is the one path exemption.** Ruling and full derivation in
  `fable-orchestrator-boundary-decision.md`; implemented in
  `.claude/project-handlers/pre_tool_use/orchestrator_simulate.py`.

  437 would-be denials in the first session: Bash 277, Write 122, Edit 33,
  Artifact 4, CronList 1, ToolSearch 1, and `Read` zero. Reads are already
  exempt, so the boundary is not too tight in the way first suspected. But Bash
  was 63% of the total and spans both sides of the line — `git status` and a QA
  run are both Bash — while `verdicts.jsonl` carried `tool` without the
  command, so the two were the same record.

  That half was a BUILD, not a decision, and it is done: the handler now sets
  `HookResult.rule` to the command HEADS (`git status`, `git commit`,
  `pytest`), reusing the field that already exists for a handler-set
  sub-classification. No new log, no new file, and nothing recorded that was
  not already recorded. Heads only is both the privacy floor — a label is
  written to a log, so it must never carry arguments, paths or tokens — and
  the right granularity, since the rest of the command line cannot inform the
  decision. RED first, 11 tests.

  What is still owed is the judgement the evidence now serves: where the line
  falls for Bash, or whether to draw it on `Write`/`Edit` alone, where 155
  calls need no interpretation at all. Building the classifier did not
  foreclose that — the second option is exactly as available as it was.

  **The second sample was not a second session, and half of it was not
  traffic.** Re-derived from the raw log: the "437" and "1,385" figures above
  are the SAME real session read at two moments, and both are ALL-SESSIONS
  totals that blend in acceptance-playbook probes (`playbook-probe-*`), the
  forwarder's socket test, and records with no session id. At the 1,385
  moment only 879 were real. 2,717 of 5,396 records (50%) were synthetic. The
  recorded lesson: **a record that mixes synthetic probes with real traffic
  is a record of neither, and it passes every check because nothing said the
  two should be told apart.**

  **The conclusion survives on clean data and strengthens.** Real session
  only, post-classifier Bash (432 calls):

  | Measure                                       | Blended (as first read) | Real traffic only |
  | --------------------------------------------- | ----------------------- | ----------------- |
  | Distinct labels                               | 171                     | 197               |
  | Compound (multi-command) calls                | 325 (79%)               | 399 (93%)         |
  | Most common single label                      | 9.5%                    | 9.0%              |
  | Labels needed to cover 50%                    | 21                      | 23                |
  | Labels seen exactly once                      | 62%                     | 72%               |
  | Labels mixing a read-only and a mutating head | not measured            | 95 (22%)          |

  The synthetic fires are single-head fixtures (`echo`, `git commit`, `git status`), which is exactly what dragged the blended compound share DOWN.

  **This settles a sub-question, and it is not the owner's to decide because
  it is arithmetic: the line cannot be drawn on Bash by command head.** Nine
  calls in ten run several commands, the labels are a long tail with no
  dominant member, 72% occur once, and one call in five straddles the
  boundary WITHIN a single invocation — `set+git add+git commit+…` is
  coordination and mutation at once, so no per-call verdict can be right
  about both halves.

  `Write`/`Edit` need no interpretation at all, and the transcript says what
  they were: ~73% of the real session's main-thread edits were implementation
  (`src/`, `tests/`, `scripts/`), which is precisely the work this plan
  exists to push to sub-agents. **The boundary therefore falls on tool
  identity.** The plan tree is exempt because `DirectoryRoles.md` gives
  `PLAN.md`, supporting documents and `JOURNAL/` to the coordinator, and
  denying them would buy no context hygiene while pushing the lead into
  `cat >> JOURNAL` heredocs — the one route this project's CLAUDE.md says
  bypasses every content guard. `untracked/scratch` is deliberately NOT
  exempt; the blocking record will show whether that hurts.

  **The recording gap that produced the blend is now closed** (Task 2.2
  precondition 1), so no future figure here can repeat it:
  `daemon/synthetic_traffic.py` is the one predicate for "was this a
  harness?", the playbook harness MARKS its own events, `verdicts.jsonl`
  carries a `synthetic` field on every line, and `hooks-daemon verdicts`
  excludes harness traffic by default (`--include-synthetic` restores the
  blended view for debugging the harness). Session-shape recognition
  classifies the window written before the marker existed, so the existing
  log became readable rather than being thrown away. RED first, 32 tests.

- [x] ✅ **Task 2.2**: Owner decision on promoting to blocking, and separately
  on promoting to the shipped library. **Two separate answers: yes to
  blocking as a project-handler opt-in; no to the library, and that one is
  not even open yet.**

  **2.2a — promote to blocking: YES, as an opt-in in the PROJECT handler,
  shipped OFF.** The switch is `BLOCKING_ENABLED` in
  `orchestrator_simulate.py`: a one-line edit to a tracked, reviewed file,
  and deliberately NOT a config key, because a config key is a library
  surface (docs, manifest, config-optimiser, a commitment to maintain it) and
  Ruling 3 says nothing ships yet. Non-Goal "blocking by default, ever"
  holds: the default is simulate and a wrong answer reverses in one line.

  Both technical preconditions are met. Precondition 1 (a filterable record)
  is the synthetic-traffic work above. Precondition 2 (blocking must not fire
  on synthetic probes) is real rather than hypothetical — the playbook builds
  events with no `agent_id`, so a naive blocking mode would deny every
  `Write`/`Edit` probe AND, under most-restrictive-wins, turn other handlers'
  expected ALLOWs into failures; the acceptance suite would have gone red on
  the day blocking was enabled. Both discriminators are tested.

  **2.2b — promote to the shipped library: NO, and the gate is not open.**
  See "The one human-gated item" below.

## The one human-gated item — NOT OPEN

Every other decision on this plan was answerable from the repository, and was
answered there. This one is not, and it is recorded rather than asked, because
**asking it today would be asking for a judgement with the evidence missing**:

> Do you commit every installing project to an opt-in orchestrator-only gate
> that THIS repository's record supports, knowing that (a) the record comes
> from one repository, one user and one workflow, (b) upstream delegate mode
> may make the handler redundant, and (c) shipping it means maintaining it for
> users indefinitely?

That is a commitment to users and a risk appetite; nothing in the repository
can answer it.

**What would open it**: a BLOCKING record from this repository — filtered to
real sessions, which is now possible — spanning several real sessions. Not the
simulation record: a simulated denial says what a policy would have caught, a
real one says what it cost. Until that exists the question has no evidence
behind it, and the "not yet" is technical rather than a deferral.

Deliberately NOT built under this plan, so that the gate cannot be quietly
walked through: no library handler, no library config key, no docs entry, no
config manifest row. The project switch is a module constant precisely because
a config key would be the first of those.

## Success Criteria

- [x] ✅ A subagent's tool call is provably unaffected, by test. This is the
  exact failure that killed the original attempt, so it is the test the slice
  was built around rather than one added afterwards.

- [x] ✅ A simulated run over real sessions in this repository produces a record
  of would-be denials, and that record is what the boundary decision cites.
  One real session (`9679b063…`), read at two moments — not two sessions, and
  the correction matters more than the count did. On clean data the record
  ruled one option out on arithmetic and pointed the other way on a 73%
  implementation share.

- [x] ✅ The record can tell a real session from a test probe, and does so by
  default. Half of it could not, which is why the figures above needed
  re-deriving; `daemon/synthetic_traffic.py` is now the single predicate, the
  harness marks its own events, and `hooks-daemon verdicts` partitions rather
  than blends.

- [x] ✅ Nothing is blocked by this plan BY DEFAULT, and blocking was a
  separate, evidenced decision rather than a flag flip. Phase 1's structural
  proof (zero `DENY` tokens in the module) is deliberately spent — Task 2.2a
  built a deny path — so the claim now rests on what can still be checked:

  1. **By default** — a default-constructed handler returns `ALLOW` for every
     tool shape, asserted across the whole surface rather than three
     convenient ones.
  2. **By declaration** — with blocking off, the handler declares no `Rule`
     and carries no `blocking` tag, so it makes no promise CLAUDE.md or
     `explain-rule` would have to keep.
  3. **Empirically** — every live `orchestrator-simulate` record in
     `verdicts.jsonl` is `allow`, against a control of thousands of `deny`
     records from other handlers in the same log. Without that control the
     evidence would be indistinguishable from a broken logger.

- [ ] ⬜ Full QA passes, the daemon restarts, CI green.

- [ ] ⬜ Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/08-verdicts-excludes-harness-traffic.md`
  (the `verdicts` default change is operator-visible). The orchestrator gate
  itself is a project handler and ships nothing, so it needs no entry.

## Delivery & Milestones

- From issue #14, open since 2026-01-27 and correctly parked until now: the
  capability it named as its unblocking condition arrived, and nothing was
  watching for it. That is the argument issue #24 makes for an upstream
  monitoring process.
