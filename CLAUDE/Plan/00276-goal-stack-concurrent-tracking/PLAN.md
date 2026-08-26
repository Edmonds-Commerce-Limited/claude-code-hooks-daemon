# Plan 00276: goal stack concurrent tracking

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Read `goal_injection.py`, `auto_continue_stop`, and the
  supervisor's goal-signal consumption path; document the exact write points,
  the once-per-`(session, plan)` latch, and where a ledger write would slot in
  without changing trigger semantics (findings in JOURNAL/ 26-08-26 entry).
- [ ] ⬜ **Task 1.2**: Reproduce the displacement shape from today's session
  (two plans flipped to In Progress in one session) against the live daemon
  and record the resulting signal-file history as the failing-behaviour
  baseline. (Deferred to main checkout: implemented worktree-side; the unit
  displacement tests encode the same two-plan shape.)
- [x] ✅ **Task 1.3**: Survey existing daemon state-file conventions under
  `ProjectContext.daemon_untracked_dir()` (context-sidecar signals,
  `background-processes.jsonl`, verdict log) and pick the ledger's format,
  location, and locking approach consistent with them.

### Phase 2: Design decisions

- [x] ✅ **Task 2.1**: Finalise the ledger schema (see Decision 3): plan
  number, session id, rendered goal line, emitted timestamp, displacement
  record (`displaced_by`/`displaced_at`), retirement record
  (`retired_at`/`retired_reason`).
- [x] ✅ **Task 2.2**: Retirement triggers specified: reconciliation runs on
  every ledger read/write — a PLAN.md carrying a terminal status retires as
  `terminal-status`; a folder absent from the active plan root (archive move)
  retires as `archived`. No new event plumbing needed.
- [x] ✅ **Task 2.3**: Stop-time behaviour specified: `auto_continue_stop`
  appends a goal-ledger challenge naming every still-In-Progress ledgered
  plan to the default explain-or-continue denial; any ledger failure fails
  open to the unchanged default message.
- [x] ✅ **Task 2.4**: Session-restart semantics decided (Decision 2 closed):
  no SessionStart advisory — the ledger consult at Stop time is
  session-agnostic and already surfaces displaced plans, and
  `goal_injection`'s new-session re-fire re-arms the newest plan.
- [x] ✅ **Task 2.5**: Latch reconciliation: the ledger records only
  successful signal emissions; a re-emission for a plan with a live entry
  refreshes that entry (session id, timestamp, clears displacement) rather
  than double-counting.

### Phase 3: Increment 1 — displacement advisory (option c)

- [x] ✅ **Task 3.1**: TDD: on emitting a goal while another ledgered goal's
  plan is still In Progress, mark the older entry displaced and inject
  advisory context ("GOAL DISPLACED ... Plan NNNNN ... still In Progress").
- [x] ✅ **Task 3.2**: Ledger write/read module
  (`src/claude_code_hooks_daemon/utils/goal_ledger.py`) with tests (atomic
  writes, corrupt-file tolerance, bounded growth/pruning of retired entries).
- [ ] 🔄 **Task 3.3**: QA passed in worktree; daemon restart verification and
  two-concurrent-plan dogfood deferred to the main checkout.

### Phase 4: Increment 2 — Stop-time defence (option a)

- [x] ✅ **Task 4.1**: TDD: `auto_continue_stop` consults the ledger and the
  default explain-or-continue denial names every still-In-Progress ledgered
  plan (`tests/unit/handlers/stop/test_goal_ledger_stop_defence.py`).
- [x] ✅ **Task 4.2**: Retirement on terminal-status flip and archive move,
  with tests (retirement persists; retired plans are no longer named).
- [ ] 🔄 **Task 4.3**: QA passed in worktree; displacement acceptance test
  added to `get_acceptance_tests()`; daemon restart verification and the
  full two-plan live dogfood deferred to the main checkout.

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

### Decision 2: Ledger durability vs the /goal condition (CLOSED)

**Context**: the ledger under `untracked/` survives a session restart; the
`/goal` condition does not.

**Decision**: no SessionStart advisory. The Stop-time ledger consult is
session-agnostic (keyed by plan, not session), so displaced/forgotten goals
are surfaced at the exact choke point where they matter, and
`goal_injection`'s new-session re-fire re-arms the `/goal` slot for whichever
plan is touched next. A SessionStart listing would duplicate the Stop
challenge with weaker (fading-context) delivery — YAGNI.
**Date**: 2026-08-26

### Decision 3: Ledger format, location, and concurrency

**Context**: Task 1.3/2.1 — pick conventions consistent with existing state
files (context-sidecar signals, `background-processes.jsonl`).

**Decision**: a single JSON document `goal-ledger.json` under
`ProjectContext.daemon_untracked_dir()` with an `entries` list
(`plan_number`, `session_id`, `rendered_line`, `emitted_at`, `displaced_by`,
`displaced_at`, `retired_at`, `retired_reason`). Writes are atomic
(pid-suffixed tmp file + `replace`, the same idiom as the goal signal); no
file locking — all writers run inside the single daemon process. Reads are
fail-open (missing/corrupt → empty ledger, logged). Growth is bounded at 100
entries, pruning oldest retired entries first. Reconciliation (terminal
status → `terminal-status`; folder absent from the active plan root →
`archived`) runs on every record and every live-plan query, so `git mv`
archive moves are caught at the next Stop consult without new event plumbing.
**Date**: 2026-08-26

### Decision 4: Review-driven hardening (code review, 2026-08-26)

**Context**: the branch code review returned FIX FIRST with three majors.

**Decisions taken**:

1. **Concurrency**: hook events dispatch on threads of one daemon process, so
   every ledger read-modify-write holds an exclusive `flock` on a sibling
   `.lock` file (daemon-start idiom) and the atomic-replace tmp file is
   uuid-named, not pid-named. Lock acquisition is itself fail-open.
2. **Retirement safety**: a nonexistent/unscannable plan dir reports
   `unreadable` and never retires — only a plan dir that EXISTS but lacks the
   folder retires as `archived`. The plan dir is resolved from the same
   config source the plan-QA handlers use (`track_plans_in_project`, injected
   via the `planning` tag; `PlanWorkflowConfig().directory` is the fallback),
   shared through `goal_ledger.resolve_plan_dir()`. `goal_injection` keeps
   deriving the plan dir from the edited PLAN.md's own path: for the emission
   surface the event's path is ground truth, and it is identical to the
   configured dir whenever the handler's matcher fired at all.
3. **Status parsing**: delegated to `plan_qa.model.PlanDoc.parse` (handles
   date qualifiers, trailing icons, fenced blocks) with `PlanStatus` /
   `TERMINAL_STATUSES` as the vocabulary — no hand-rolled status regex.
4. **Advisory wording**: softened to state the last-writer-wins mechanism
   ("any live /goal condition ... is now superseded") rather than asserting
   "has just been overwritten", which is untrue when the displaced goal was
   set in an earlier session and had already expired with it.
   **Date**: 2026-08-26

## Success Criteria

- [ ] A ledger file exists under the daemon untracked dir recording every
  goal emission with plan number, session id, and timestamps; verified by
  unit tests and a live two-plan dogfood run.
- [x] Emitting a second goal while a prior ledgered plan is In Progress marks
  the prior entry displaced AND injects an advisory naming it (Phase 3
  acceptance test).
- [x] With two ledgered In Progress plans, a Stop lacking `STOPPING BECAUSE:`
  is challenged with a message naming BOTH plans (Phase 4 test).
- [x] Flipping a plan to Complete (with its archive `git mv`) retires its
  ledger entry; a subsequent Stop is not challenged on its behalf.
- [x] A missing or corrupt ledger never breaks a Stop event or a PLAN.md
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
