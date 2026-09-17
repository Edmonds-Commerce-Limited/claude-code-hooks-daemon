# Plan 00423: per handler scope main sub

**Status**: Complete
**Created**: 2026-09-16
**GitHub Issue**: #40 (and #41, triaged into decision 2)
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #40 asks that every handler declare where it is active — `ALL | MAIN | SUB` — as a config key in `hooks-daemon.yaml` with a per-handler default, and
that the registry refuse to run a `MAIN` handler on a `SubagentStop` event or
on any event whose payload carries subagent metadata.

The motivating symptom is verified. `auto_continue_stop` owns
`R-STOP-GOAL-LEDGER` and contains no mention of subagents at all, so it has no
role-awareness to gate on: a subagent session that stops is told to continue
every In Progress plan in the coordinator's ledger, none of which was its
assignment. The reporter observed a finished agent re-waking on failsafe ticks
and, on its last wake, deleting the project's single failsafe recovery cron on
its own initiative to stop the nudges.

**This plan is a QUESTION for the owner, not an implementation brief.** The
issue-sdlc loop classified #40 as needs-human and stopped; no code was written.
Three decisions have to be made by a human before anything moves.

## The three decisions this plan is waiting on

### 1. Does a library-level scope key reverse Plan 00418's ruling?

Plan 00418 (Complete, for issue #14) already built main-thread-vs-subagent
detection and validated it empirically: `agent_id` reaches `PreToolUse` only
INSIDE a subagent call, so absent means main thread and present means subagent.
The mechanism #40 needs exists and is proven.

But 00418 shipped it as a SIMULATE-ONLY **project-level** handler under an
explicit ruling recorded in `orchestrator_simulate.py`: there is no config key,
because nothing about this ships to the library yet, and a library config key
would be shipping it.

Issue #40 asks precisely for a library config key. That is the owner's ruling
to reaffirm or reverse — the reasoning behind it (earn the right to block
before shipping the control) does not survive being inferred from a ticket.

### 2. Is scoping the right lever, or is reaping?

#40 and #41 are one cluster, filed the same day by the same reporter, citing
the SAME incident — a subagent deleting a shared recovery cron — as evidence
for two different remedies:

- **#40**: scope the handlers so nudges never reach a subagent.
- **#41**: reap idle subagents so there is nothing left to nudge.

They interact, so acting on one alone could be wrong. `teammate_reap_advisor`
shipped in v3.65.0 and already reports unreaped background work at Stop, which
addresses part of #41 — the cluster's baseline moved after both were filed and
before either was triaged.

#### What #41 asks for that already exists (verified at triage)

#41 was triaged into this decision rather than into a plan of its own. Three of
its five asks have already moved, which changes what the owner is ruling on:

- **Worktree cleanup already ships, and is stricter than the ask.**
  `worktree-reap` and `core/worktree_reaping.py` (Plans 00349, 00372, 00380)
  refuse an unmerged branch, treat an unreadable merge listing as unmerged,
  refuse a history-free worktree below a minimum age, detect a live process by
  working directory, and surface the uncertain rather than removing it.
- **An idle-agent census cannot be built from the Stop payload.**
  `background_tasks` lists an idle teammate with `status: "running"`, so a
  threshold counting "idle subagents" would in fact be counting registered
  tasks. `ListAgents` holds the distinction; the daemon sees only payloads.
- **The `hooks-daemon agents` verb name is already taken** by the
  daemon-shipped agent-asset lifecycle (Plan 00279).

The attribution work may also be smaller than #41 estimates: contracts already
exist for `SubagentStart`, `TaskCreated`, `TaskCompleted` and `TeammateIdle`,
none of which has a handler package yet. `TeammateIdle` is a first-class
went-idle signal, which is what #41's ask 2 proposes to infer from a silence
timer — whether it fires for Agent-tool subagents as well as named teammates is
unverified.

What remains in #41 is three new destructive or blocking controls: a hard cap
that blocks the coordinator's stop, an `auto_reap` that stops agents, and
automatic cron deletion. The last is the sharpest point for the owner: the harm
#41 reports is an agent deleting a shared recovery cron on its own initiative,
and its proposed remedy is cron deletion on the daemon's own initiative. Same
operation, different actor.

### 3. Per-handler defaults are a safety decision, ~136 times over

The proposal needs a default scope for every registered handler. Getting one
wrong in the `SUB`/`MAIN` direction silently switches a guard off for a whole
class of session, and a handler that stops firing looks exactly like a handler
with nothing to report. The issue's suggested split (content guards `ALL`,
nudge handlers `MAIN`) is a starting hypothesis, not a substitute for that
per-handler review.

Issue point 3 — making failsafe-cron deletion coordinator-only — is a
permissions change to a safety control, which the issue-sdlc runbook stops on
by rule regardless of its merits.

## Goals

- Record the owner's decision on each of the three questions above.
- If the answer is "build it": scope the work against Plan 00418's existing
  detection rather than re-deriving it, and triage #40 and #41 together.

## Non-Goals

- Implementing the scope key before decision 1 is answered.
- Re-deriving main/sub detection — Plan 00418 proved it against live payloads.
- Changing the failsafe cron's deletion permissions before a human rules.

## Tasks

### Phase 1: Owner decisions (RULED — 2026-09-17)

**The owner approved #40 and #41 together, in session, with one binding
condition**: the MAIN/SUB detectability assumption must be dogfooded and shown
to work, not assumed. In their words — "make sure we carefully dog food this to
confirm assumptions about detectability of MAIN and SUB scenarios are actually
working".

That condition is not a nicety. This whole plan rests on `agent_id`
discriminating MAIN from SUB at the moments these handlers fire, and Plan 00418
was built once and DELETED because hooks could not tell which agent fired an
event. If the discrimination does not hold at Stop/SubagentStop time, the
defaults below are decoration.

- [x] ✅ **Task 1.1**: RULED — approved. A library-level `scope` key may ship;
  this reverses Plan 00418's "nothing ships to the library yet" for this key.
- [x] ✅ **Task 1.2**: RULED — approved as a cluster, both #40 and #41.
- [x] ✅ **Task 1.3**: RULED — approved, including making failsafe-cron
  deletion coordinator-only. Recorded explicitly because it is a permissions
  change to a safety control, which this loop may not decide for itself.

### Phase 2: prove the assumption BEFORE building on it

- [x] ✅ **Task 2.1**: DONE — measured via `daemon.payload_capture`. `agent_id`
  present in all 5 SubagentStop payloads (17-char string, never empty), absent
  on the main-thread Stop. Its ABSENCE is a sound MAIN discriminator.

- [x] ✅ **Task 2.2**: Discrimination HOLDS for `agent_id`. One case remains
  unverified by direct observation and must not be assumed: a session started
  with `--agent`, where the contract says `agent_type` appears on a main-thread
  stop. It cannot be produced from inside this session.

  **The measurement also disqualified `agent_type` outright**: present but
  EMPTY in 4 of 5 subagent stops. It both over-reports (the contract's
  `--agent` warning) and under-reports (measured here). A handler keying on it
  would misclassify 4 of 5 subagents as main-thread — firing nudges exactly
  where they were meant to be suppressed. Task 3.1 must key on `agent_id`
  presence and nothing else.

### Phase 3: build

**Prior art to copy, not rediscover.** `.claude/project-handlers/pre_tool_use/orchestrator_simulate.py`
already discriminates on `agent_id` and has been live in simulate mode. Two of
its decisions carry straight over, and the second one is a trap:

- It keys on `hook_input.get("agent_id")` truthiness. Safe here — measured,
  `agent_id` is a 17-character string whenever present, never empty — but the
  property that makes it safe is worth stating rather than inheriting by
  accident.

- **A synthetic event has no `agent_id`, so it is indistinguishable from a
  main-thread one.** The acceptance playbook fabricates events, and that
  handler guards with `is_synthetic_event()`
  (`daemon/synthetic_traffic.py`), recording in its own docstring that without
  it the suite would go red "with hundreds of denied probes AND, under
  most-restrictive-wins, other handlers' expected ALLOWs turned into failures —
  on the day blocking was first enabled".

  A `scope: MAIN` handler inherits that failure mode exactly. `MAIN` cannot
  mean "no `agent_id`"; it has to mean "no `agent_id` AND not synthetic".

- [x] ✅ **Task 3.1**: DONE — `scope: ALL|MAIN|SUB` ships as a config key,
  refused at load on an event that cannot carry `agent_id`, gated in the chain
  before `matches()`, keyed on `agent_id` presence alone. Synthetic events are
  excluded from every restricting scope. Defaults: `auto-continue-stop`,
  `cron-stop-enforcer` and `teammate-reap-advisor` are `MAIN`; everything else
  `ALL`. The acceptance suite is unaffected — measured, not assumed: all five
  probes for those handlers are already SKIPPED, because the harness cannot
  drive a `Stop` event at all.

- [x] ✅ **Task 3.2**: DONE — `subagent_cron_delete_blocker` (PreToolUse,
  `scope: SUB`, terminal, on by default) denies `CronDelete` inside a subagent.
  Deliberately wider than "the failsafe cron": `session_crons` reaches `Stop`,
  not `PreToolUse`, so at deletion time the daemon holds an opaque id and a
  narrower rule would be guessing. The handler never reads `agent_id` itself —
  the scope key is the whole role test.

- [x] ✅ **Task 3.3**: DONE — scoped in
  [ISSUE-41-SCOPE.md](ISSUE-41-SCOPE.md), ask by ask. The deliverable is the
  scoping, not new controls: three of the five asks are destructive or blocking
  and are NOT built here, for a reason recorded there.

  Two protocol facts were checked rather than assumed, and one reverses an
  assumption this plan was working from:

  - **The daemon CAN stop a teammate.** `TeammateIdle`/`TaskCompleted` document
    a `continue: false` block, implemented at `core/hook_result.py:94` and
    `:870` and schema-valid at `core/response_schemas.py:379`, used by NO
    shipped handler — there is no handler package for either event. So
    `auto_reap` is buildable, from a first-class went-idle signal rather than a
    silence timer.
  - **The daemon CANNOT delete a cron.** No contract output field expresses it;
    every response passes `_enforce_response_contract` against schemas that are
    all `additionalProperties: false`. #41 ask 3 is not implementable as
    written.

## Success Criteria

- [x] ✅ Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/06-handlers-can-declare-where-they-are-active.md`
  and `UNRELEASED/config-changes/v3.66.0.yaml` (the `scope` key and the
  `subagent_cron_delete_blocker` handler).
- [x] ✅ Each of the three decisions is recorded here with its reasoning —
  Phase 1, Tasks 1.1–1.3.
- [x] ✅ #40 and #41 carry a comment pointing at the ruling, so neither is
  re-triaged from scratch by a later tick.
  ([#40](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/40#issuecomment-5715251634),
  [#41](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/41#issuecomment-5715252759))

## Separable second report in the same issue

The issue's final paragraph reports something unrelated to scoping: in a
consuming project the daemon's own CLI wrapper had lost its execute bit, so
invoking it failed, and it suggests a self-check in the shape of the existing
`git_hooks_executable_fixer`.

That is smaller, self-contained, has a precedent in the codebase, and depends
on none of the three decisions. Recorded here so it is not lost while #40 is
parked; a candidate for its own plan if the owner wants it split out.

## Delivery & Milestones

- Filed by the issue-sdlc loop from issue #40; triaged needs-human, no code
  written.
