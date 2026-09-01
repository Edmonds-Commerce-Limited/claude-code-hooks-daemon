# Plan 00299: multi plan goal support

**Status**: Complete
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

During the session that filed 00296, 00297 and 00298, three plans ran
concurrently via worktree sub-agents (00296 in-progress at the time, with
00297/00298 also active work), but the ccy-supervisor kept re-injecting a
`/goal` for 00296 alone — the other two plans got no goal signal at all.
Investigation of the live code confirms this is structural, not a bug in one
handler: the `/goal` condition is a single session-scoped slot, so a second
plan's signal silently displaces the first.

`GoalInjectionHandler.handle()`
(`src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py:396`)
fires on a `PLAN.md` write that flips `**Status**: In Progress`
(`_STATUS_IN_PROGRESS_RE`, same file:143-145), and `write_goal_signal()`
(same file:304-334) atomically writes **one file per session**,
`<session_id>.goal-intent` under `context-sidecar/`
(`target_dir / f"{stem}{_SIGNAL_SUFFIX}"`, same file:317, dir setup
same file:68-71). A second plan flipping to In Progress in the same session
overwrites that same path — there is no per-plan keying. The consumer,
`.claude/ccy/claude-supervise.py`'s `load_goal_signal()` (line 1991-2024),
globs `*.goal-intent` (`_GOAL_SIGNAL_GLOB`, line 769) and returns the first
sorted match — normally exactly one file exists per session, so "which plan"
is decided entirely by whichever `PLAN.md` most recently flipped to In
Progress. Upstream Claude Code's own `/goal` slot is itself last-writer-wins
(comment at goal_injection.py:2-3, 53-55), so even a fixed daemon side cannot
by itself hold two live `/goal` conditions simultaneously.

Meanwhile the daemon already tracks multi-plan state independently: the
**goal ledger** (`src/claude_code_hooks_daemon/utils/goal_ledger.py`,
rule id `R-STOP-GOAL-LEDGER` declared at
`src/claude_code_hooks_daemon/constants/rule_ids.py:172`) is a genuine
multi-plan collection. `GoalLedgerEntry` (goal_ledger.py:78-89) is one row
per `(plan_number, session_id)`, persisted as a JSON list under
`LEDGER_FILENAME = "goal-ledger.json"` (line 42, `_ENTRIES_KEY`, line 48).
`GoalLedger.record_emission()` (lines 290-339) appends/updates an entry per
plan and marks other still-In-Progress plans `displaced` rather than
deleting them (lines 306-317); `GoalLedger.live_plan_numbers()`
(lines 341-358) returns every ledgered plan still In Progress, including
displaced ones. Plan status is read via `_plan_state()` (lines 105-138),
which globs the plan dir for `f"{plan_number}-*"`, reads `PLAN.md`, and
parses through `PlanDoc.parse()` / `PlanStatus.IN_PROGRESS` /
`TERMINAL_STATUSES` (imported from
`claude_code_hooks_daemon.plan_qa.model`, goal_ledger.py:37) — the same
model the `goal_injection` sensor's own status regex targets. The Stop
handler already consumes this: `AutoContinueStopHandler._goal_ledger_challenge()`
(`src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py:595-613`)
reads `live_plan_numbers()` and appends a reminder to the stop-block reason
"even if the /goal condition now shows only the newest one" whenever any
ledgered plan is still live, folded into the branch message at
lines 555-568.

So multi-plan awareness half-exists today: the ledger is already the
authoritative, multi-plan, correctly-keyed data structure, and the Stop
hook already treats it as such. What is missing is the **injection side** —
turning "N plans are live in the ledger" into N plans' worth of visible
`/goal` guidance without fighting over the single upstream `/goal` slot —
and clearing/completion semantics that update the right plan's entry instead
of clobbering whichever wrote last.

## Goals

- Goals are per-plan and additive: setting a goal for plan B does not clobber
  plan A's tracked state.
- The Stop condition is satisfied only when every live goal's plan is
  complete or totally blocked — align the `/goal` condition's practical
  effect with what the ledger (`live_plan_numbers()`,
  `auto_continue_stop.py:595-613`) already enforces; evaluate whether the fix
  is to make the ledger the single mechanism and the `/goal` slot a rendered
  *view* of it, since the upstream slot cannot itself hold N values.
- The supervisor can surface goal signals for multiple plans without
  thrashing — e.g. one combined `/goal` naming every ledgered In-Progress
  plan, or per-plan set/clear verbs layered over the single upstream slot.
- Clearing (a plan reaching a terminal status) is per-plan: it retires that
  plan's ledger entry / contribution to the combined goal without disturbing
  other still-live plans.
- Backwards compatible with single-plan sessions: with exactly one live
  plan, behaviour is unchanged from today.

## Non-Goals

- Changing plan lifecycle or `PlanStatus` values/semantics.
- Changing supervisor architecture beyond the goal-signal path (the
  two-tier PTY-host/worker split, hot-reload contract, etc. are out of
  scope).
- Removing or redesigning the goal ledger's persistence format — extend it,
  don't replace it, unless investigation in Phase 1 finds a concrete reason
  it cannot carry the additional per-plan-view responsibility.
- Any change to `.claude/ccy/claude-supervise.py` or daemon source as part of
  *this* plan's authoring — this plan is design + investigation only; a
  future execution session implements the phases below.

## Tasks

### Phase 1: Investigation confirmations

- [x] ✅ **Task 1.1**: Re-derive and confirm the exact overwrite mechanism in
  `write_goal_signal()` (`goal_injection.py:304-334`) — verify the
  `<session_id>.goal-intent` filename truly has no plan-number component,
  and check whether `_SIGNAL_SUFFIX`/`target_dir` resolution
  (goal_injection.py:68-71, 317) offers any existing per-plan hook point
  to build on rather than replace.
- [x] ✅ **Task 1.2**: Confirm upstream Claude Code's native `/goal` command
  is genuinely single-valued (not a stack/queue) by reading its
  documented behaviour and/or testing `/goal` twice in one session;
  record the citation. This determines whether Phase 3's "combined goal"
  design is the only viable shape or whether per-plan set/clear verbs
  against multiple upstream slots are possible.
- [x] ✅ **Task 1.3**: Trace `GoalLedger.record_emission()`
  (goal_ledger.py:290-339) and `live_plan_numbers()` (lines 341-358) end
  to end against a synthetic two-plan scenario (two `PLAN.md` files both
  `**Status**: In Progress` in the same session) to confirm displacement
  marking (lines 306-317) behaves as described and does not lose either
  plan's entry.
- [x] ✅ **Task 1.4**: Read `PlanDoc.parse()` / `PlanStatus` /
  `TERMINAL_STATUSES` (`claude_code_hooks_daemon.plan_qa.model`) to
  confirm the exact set of terminal statuses the ledger and stop-hook
  challenge treat as "not live", and confirm `_plan_state()`
  (goal_ledger.py:105-138) glob (`f"{plan_number}-*"`) is safe against
  the `Completed/` subdirectory and worktree copies of `PLAN.md`.

### Phase 2: Daemon-side design (ledger as source of truth)

- [x] ✅ **Task 2.1**: Design a `render_combined_goal_signal()` (or similar)
  function that reads `live_plan_numbers()`/ledger entries and produces
  one `/goal` payload naming every live plan, replacing the current
  single-plan `write_goal_signal()` call in
  `GoalInjectionHandler.handle()` (goal_injection.py:396).
- [x] ✅ **Task 2.2**: Design per-plan clear semantics: when a plan's status
  flips to a terminal status, its ledger entry is retired
  (`retired_at`/`retired_reason`, per existing fields referenced in
  Finding #5) and the combined goal signal is re-rendered to drop that
  plan without touching others' entries.
- [x] ✅ **Task 2.3**: Decide whether `_goal_ledger_challenge()`
  (auto_continue_stop.py:595-613) needs to change at all, given it
  already enforces "block until every live ledgered plan is
  done/blocked" — or whether Phase 2/3 changes are purely on the
  injection side and this stays as-is.
- [x] ✅ **Task 2.4**: Define backward-compatibility behaviour for the
  single-plan case explicitly (one entry in `live_plan_numbers()` ⇒
  combined-goal rendering degenerates to today's single-plan text
  byte-for-byte, so existing acceptance tests/snapshots do not need
  rewriting).

### Phase 3: Supervisor-side design

- [x] ✅ **Task 3.1**: Design how `.claude/ccy/claude-supervise.py`'s
  `load_goal_signal()` (line 1991-2024) and the injection call site
  consume a combined multi-plan signal payload without needing to know
  about plan numbers itself (keep the supervisor a dumb consumer, per
  the Overview's existing division of responsibility).
- [x] ✅ **Task 3.2**: Design thrash avoidance — the supervisor's hot-reload
  / re-injection cadence must not re-type the full combined `/goal` on
  every tick if the ledger hasn't changed; reuse whatever staleness/hash
  check already gates re-injection (per the ccy-supervisor hot-reload
  contract in `/root/.claude/CLAUDE.md`) rather than inventing a new one.
- [x] ✅ **Task 3.3**: Confirm the design does not require changes to the
  two-tier PTY-host/worker split or the `--worker` subprocess hot-reload
  mechanism itself — only to what payload the worker types.

### Phase 4: Docs and acceptance

- [x] ✅ **Task 4.1**: Update `goal_injection.py`'s module docstring/comment
  at lines 2-3, 53-55 (currently documents last-writer-wins as the
  model) to describe the combined-signal model once implemented.
- [x] ✅ **Task 4.2**: Add/extend acceptance coverage for: two concurrent
  In-Progress plans both appearing in one combined goal signal; one
  plan reaching a terminal status while the other stays live (goal
  signal drops only the finished plan); a single-plan session
  (regression: unchanged output).
- [x] ✅ **Task 4.3**: Update any HOOKS-DAEMON.md / handler-guidance text
  that currently describes `/goal` as single-plan-only.

## Success Criteria

- [x] Two concurrent In-Progress plans each keep a live representation in
  the goal signal — neither is silently dropped by the other's write.
- [x] Finishing (or fully blocking) one plan does not clear or displace the
  other plan's goal representation.
- [x] The Stop hook allows a stop only when every plan tracked by the goal
  ledger is done or fully blocked — unchanged from today's ledger
  behaviour, now backed by injection that actually reflects all of them.
- [x] A single-plan session's `/goal` text and Stop-hook behaviour are
  byte-for-byte unchanged from pre-plan behaviour.
- [x] No change to plan lifecycle/status semantics or to the supervisor's
  two-tier hot-reload architecture.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00299-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed 2026-09-01 per owner instruction, following the live 00296/00297/00298
  concurrent-plan goal-thrashing incident.
