# Plan 00276: goal stack concurrent tracking

**Status**: Not Started
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Claude Code's `/goal` system holds exactly ONE session-scoped Stop-hook
condition. Setting a new goal silently clobbers the previous one. The daemon's
`goal_injection` handler (Plan 00269,
`src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py`) fires
whenever a `PLAN.md` flips to `**Status**: In Progress`, so under this
project's established concurrent-work pattern — multiple plans executing in
parallel via sub-agents — each new plan's injected goal REPLACES the previous
plan's goal while that plan is still unfinished. Observed live today
(2026-08-26, dogfooding): the Plan 00275 goal displaced the Plan 00274 goal
mid-pipeline. Nothing records the displaced goal; the Stop hook thereafter
defends only the newest plan.

Because `/goal` and the single condition slot belong to Claude Code, not to
this daemon, the fix cannot be "hold multiple conditions in Claude Code". The
tracking must live daemon-side: this plan designs a goal ledger that records
every goal the daemon emits, detects displacement, and lets the daemon's own
`auto_continue_stop` Stop handler defend EVERY still-live ledgered goal — not
just the last writer.

## Goals

- Record every goal `goal_injection` emits in a durable daemon-side ledger,
  including detection of when a new goal displaces a still-live one.
- Extend Stop-time defence so a stop is challenged while ANY ledgered goal's
  plan remains `In Progress`, not only the newest.
- Retire ledger entries automatically when their plan reaches a terminal
  status (Complete/Cancelled/Superseded) or is archived.
- Ship an advisory-first increment: on displacement, inject context naming the
  displaced plan so the agent knows it is still owed work.

## Non-Goals

- Changing Claude Code's `/goal` mechanism or making it hold multiple
  conditions — the slot is upstream's and stays last-writer-wins.
- Changing the supervisor's injection rails or typing behaviour beyond what
  the ledger requires.
- Any general multi-goal UX (listing/editing goals from chat); this is
  Stop-defence plumbing, not a feature surface.

## Context & Background

- **Parent**: Plan 00269 built the sensor/actuator pair: `goal_injection`
  (PostToolUse) writes a `<session>.goal-intent` signal when a PLAN.md flips
  to In Progress; the ccy PTY supervisor types `/goal 🤖 [ccy-supervisor] ...`
  into the foreground chat. The handler latches once per `(session, plan)` in
  memory and re-fires in a new session, re-establishing the goal after a
  restart.
- **Evidence**: today's displacement (Plan 00275's goal overwrote Plan
  00274's while 00274 was still executing) was observed directly in this
  session's own dogfooding. The user's prompt: "maybe we need to track this
  somehow? dog fooding".
- **Honest constraint**: the supervisor typing `/goal` per new plan is
  inherently last-writer-wins at the Claude Code layer. Daemon-side tracking
  compensates at Stop time; it cannot restore the displaced condition inside
  Claude Code itself.
- The daemon already watches PLAN.md edits (`plan_qa_edit`,
  `recovery_cron_advisor`, `goal_injection` all key on the same surface), so
  terminal-status flips are an observable retirement trigger with no new
  event plumbing.

## Dependencies

- Depends on: Plan 00269 (Complete — goal injection feature this extends)
- Related: `auto_continue_stop` Stop handler (Stop-time enforcement point);
  ccy PTY supervisor (actuator, unchanged)

## Tasks

### Phase 1: Research and ground truth

- [ ] ⬜ **Task 1.1**: Read `goal_injection.py`, `auto_continue_stop`, and the
  supervisor's goal-signal consumption path; document the exact write points,
  the once-per-`(session, plan)` latch, and where a ledger write would slot in
  without changing trigger semantics.
- [ ] ⬜ **Task 1.2**: Reproduce the displacement shape from today's session
  (two plans flipped to In Progress in one session) against the live daemon
  and record the resulting signal-file history as the failing-behaviour
  baseline.
- [ ] ⬜ **Task 1.3**: Survey existing daemon state-file conventions under
  `ProjectContext.daemon_untracked_dir()` (context-sidecar signals,
  `background-processes.jsonl`, verdict log) and pick the ledger's format,
  location, and locking approach consistent with them.

### Phase 2: Design decisions

- [ ] ⬜ **Task 2.1**: Finalise the ledger schema: per-entry plan number,
  session id, rendered goal line, emitted timestamp, displacement record
  (which entry displaced it, when), retirement record (terminal status or
  archive move, when).
- [ ] ⬜ **Task 2.2**: Specify retirement triggers: PLAN.md edit setting a
  terminal status; `git mv` into `Completed/`/`Cancelled/` (visible only at
  the next PLAN.md-surface event or session sweep — decide which surface
  reconciles it).
- [ ] ⬜ **Task 2.3**: Specify Stop-time behaviour: how `auto_continue_stop`
  consults the ledger, what the challenge message names (every still-live
  ledgered plan), and how it degrades when the ledger is missing/unreadable
  (fail open, advisory).
- [ ] ⬜ **Task 2.4**: Specify session-restart semantics: the ledger survives
  under `untracked/`; the `/goal` condition does not. Decide whether a
  SessionStart advisory lists still-live ledgered goals and suggests
  re-arming (and whether `goal_injection`'s new-session re-fire already
  covers the newest plan, leaving only the displaced ones to surface).
- [ ] ⬜ **Task 2.5**: Reconcile with `goal_injection`'s existing cap and
  once-per-plan latch: the ledger must record every EMISSION (including
  re-fires after restart) without double-counting a live goal per plan.

### Phase 3: Increment 1 — displacement advisory (option c)

- [ ] ⬜ **Task 3.1**: TDD: on emitting a goal while another ledgered goal's
  plan is still In Progress, mark the older entry displaced and inject
  advisory context ("goal displaced: Plan NNNNN still In Progress").
- [ ] ⬜ **Task 3.2**: Ledger write/read module with tests (atomic writes,
  corrupt-file tolerance, bounded growth/pruning of retired entries).
- [ ] ⬜ **Task 3.3**: QA, daemon restart verification, dogfood with two
  concurrent plans.

### Phase 4: Increment 2 — Stop-time defence (option a)

- [ ] ⬜ **Task 4.1**: TDD: `auto_continue_stop` consults the ledger and
  challenges a stop while any ledgered goal's plan is still In Progress.
- [ ] ⬜ **Task 4.2**: Retirement on terminal-status flip and archive move,
  with tests.
- [ ] ⬜ **Task 4.3**: QA, daemon restart verification, acceptance tests via
  `get_acceptance_tests()`, dogfood through a full two-plan pipeline.

## Technical Decisions

### Decision 1: Where the multi-goal tracking lives

**Context**: Claude Code holds one `/goal` condition; concurrent plans each
inject one, and the last writer wins. Something must remember the losers.

**Options Considered**:

1. **(a) Daemon-side goal ledger** — `goal_injection` records every emitted
   goal (and detects displacement) in a state file under the daemon untracked
   dir; `auto_continue_stop` challenges a stop while ANY ledgered goal's plan
   is still In Progress; entries retire when their plan reaches a terminal
   status. Pros: durable across restarts, enforced at the Stop choke point,
   no upstream dependency. Cons: new state file + retirement bookkeeping;
   Stop handler gains a read dependency.
2. **(b) Composite goal text** — on injecting while another plan is In
   Progress, the supervisor types a combined condition ("Work on Plans 00274
   AND 00275 until completion"). Pros: zero new machinery, the condition
   itself stays truthful. Cons: text grows unboundedly, stale plans linger in
   the condition, the 500-char joined-line cap bites quickly, and the daemon
   must reconstruct "what is currently live" anyway to compose it — i.e. it
   needs the ledger regardless.
3. **(c) Advisory only** — on displacement, inject context telling the agent
   "goal displaced: Plan NNNNN still In Progress" and rely on the agent.
   Pros: zero durable machinery, ships fast. Cons: weakest — nothing enforces
   at Stop time, and advisories fade from context.

**Decision**: Lean **(a)**, delivered with **(c) as its first shipped
increment** — the displacement advisory needs the same detection the ledger
needs, so it is the natural Phase 3 slice, with Stop-time enforcement
following in Phase 4. Option (b) is rejected as a primary mechanism but its
composite phrasing may inform the Stop-challenge message. Recorded honestly:
the supervisor typing `/goal` per new plan remains last-writer-wins at the
Claude Code layer; the ledger compensates daemon-side rather than fixing the
slot.
**Date**: 2026-08-26

### Decision 2: Ledger durability vs the /goal condition (open)

**Context**: the ledger under `untracked/` survives a session restart; the
`/goal` condition does not. Options: SessionStart advisory listing still-live
ledgered goals and suggesting re-arming; or rely on `goal_injection`'s
new-session re-fire (which only re-establishes the plan whose PLAN.md is
edited next). To be settled in Task 2.4.

## Success Criteria

- [ ] A ledger file exists under the daemon untracked dir recording every
  goal emission with plan number, session id, and timestamps; verified by
  unit tests and a live two-plan dogfood run.
- [ ] Emitting a second goal while a prior ledgered plan is In Progress marks
  the prior entry displaced AND injects an advisory naming it (Phase 3
  acceptance test).
- [ ] With two ledgered In Progress plans, a Stop lacking `STOPPING BECAUSE:`
  is challenged with a message naming BOTH plans (Phase 4 test).
- [ ] Flipping a plan to Complete (with its archive `git mv`) retires its
  ledger entry; a subsequent Stop is not challenged on its behalf.
- [ ] A missing or corrupt ledger never breaks a Stop event or a PLAN.md
  write (fail-open tests).
- [ ] `./scripts/qa/llm_qa.py all` passes; daemon restart verified RUNNING.

## Risks & Mitigations

| Risk                                                                    | Impact | Probability | Mitigation                                                                               |
| ----------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------- |
| Stale ledger entries (plan abandoned without terminal flip) block stops | Medium | Medium      | Fail-open + staleness window; challenge message names the entry so a human can retire it |
| Ledger corruption breaks Stop handling                                  | High   | Low         | Fail-open reads, atomic writes, corrupt-file tests                                       |
| Retirement misses an archive `git mv` (no Write/Edit event fires)       | Medium | Medium      | Reconcile at session sweep / next Stop consult by checking plan folder location          |
| Double-defence with the live `/goal` condition confuses the agent       | Low    | Medium      | Challenge message states it is the daemon-side ledger speaking, listing all live plans   |

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
