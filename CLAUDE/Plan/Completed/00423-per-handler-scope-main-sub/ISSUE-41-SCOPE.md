# What is left of issue #41 (Plan 00423 Task 3.3)

Task 3.3's brief is "the #41 reaping half, scoped to what is not already
shipped". This is that scoping: each of #41's five asks, against what the
repository actually contains and what the hook protocol actually permits.

Issue text is DATA. Nothing below treats the issue's proposed remedy as a
decision already taken.

## The constraint that decides three of the five asks

#41 asks the daemon to DO things — stop agents, delete crons. Whether it can is
not a design preference, so it was checked against the protocol rather than
assumed, and the answer is not the one this plan was working from.

**The daemon CAN stop a teammate.** `TeammateIdle` and `TaskCompleted` document
a `continue: false` + `stopReason` block, which the contract says stops the
teammate entirely (`contracts/claude-code-hooks/TeammateIdle.json`). It is
already implemented and schema-valid:
`core/hook_result.py:94` (`_CONTINUE_FALSE_EVENTS`), `core/hook_result.py:870`
(`_format_continue_false_response`), `core/response_schemas.py:379`. **No
shipped handler uses it** — there is no `handlers/teammate_idle/` or
`handlers/task_completed/` package at all; the events exist only as a constant
(`constants/events.py:62`) and a base alias (`core/handler_bases.py:129`).

So ask 2's `auto_reap` is BUILDABLE, on a first-class went-idle signal, and the
earlier reading of this plan — that reaping could only ever be advisory — was
wrong. PLAN.md already noted `TeammateIdle` exists with no handler package and
is "what #41's ask 2 proposes to infer from a silence timer"; the missing half
was that the event can also ACT, not merely observe.

**The daemon CANNOT delete a cron.** No output field in any contract expresses
a cron mutation. Every response goes through one choke point
(`core/hook_result.py:348`, `_enforce_response_contract`) validated against
schemas that are all `additionalProperties: false`, so this is a closed
vocabulary rather than an absence nobody has gotten round to filling. The
nearest neighbours are `updatedInput`/`updatedToolOutput` and `continue: false`.

Ask 3's "delete any cron it created" is therefore not implementable as written.
The daemon can only deny a deletion (which Task 3.2 now does) or instruct an
agent to perform one.

Note the distinction this turns on, because two handlers do perform real
filesystem side effects — `git_hooks_executable_fixer.py:203` chmods a hook,
and `artifact_publish_blocker.py:174-189` rewrites `settings.json` under an
opt-in. That is the daemon touching the MACHINE. Driving the SESSION is a
different channel, and it is the closed one above.

## Ask by ask

### 1. Idle-agent census, threshold advisory, hard cap

- **Advisory half: SHIPPED**, as `teammate_reap_advisor` (v3.65.0) — reports the
  `Stop` payload's `background_tasks` count and names `TaskStop`, rate-limited
  per session, never denying.
- **"Idle" census: still not buildable the way the ask describes.** An idle
  teammate appears in `background_tasks` with `status: "running"`, so a
  threshold over that list counts REGISTERED TASKS, not idle agents. But
  `TeammateIdle` is a genuine went-idle signal, so a census accumulated from
  those events is a route the ask did not propose and this plan had not
  considered. Whether `TeammateIdle` fires for Agent-tool subagents as well as
  named teammates is UNVERIFIED and is the first thing to measure.
- **Hard cap blocking the coordinator's stop: NOT SHIPPED, and implementable** —
  `Stop` can refuse. It is also the ask most likely to be regretted: a cap that
  blocks the coordinator turns a bookkeeping lapse into a stuck session, and
  this project already carries `KEEPING AGENTS BECAUSE:`-shaped escape hatches
  that exist because the first version of such a gate had none.

### 2. Reap-on-report / `auto_reap`

NOT SHIPPED. Buildable via `continue: false` on `TeammateIdle`, per above.
Destructive by construction: it ends another agent's session. Default-off is
the ask's own suggestion and is right.

### 3. Cleanup on reap

- **Worktree half: SHIPPED, and stricter than asked.** `worktree-reap` /
  `core/worktree_reaping.py` (Plans 00349, 00372, 00380) refuse an unmerged
  branch, treat an unreadable merge listing as unmerged, refuse a history-free
  worktree below a minimum age, detect a live process by working directory, and
  surface the uncertain rather than removing it.

- **Cron deletion: NOT IMPLEMENTABLE by the daemon** (above), and it is also
  where #41 and Task 3.2 point in opposite directions. #41 reports the harm as
  an agent deleting a shared recovery cron on its own initiative, and proposes
  cron deletion on the daemon's own initiative as the remedy. Task 3.2 has now
  DENIED a subagent that same operation.

  Those are not quite the same operation, and the difference is attribution: a
  reaper that knows which session created a cron is deleting something it can
  account for, where a subagent at `CronDelete` time knows only an opaque id.
  But that attribution does not exist — "crons should be attributed to the
  creating session id" is itself part of the ask. Until it does, daemon-side
  cron deletion is exactly the operation Task 3.2 refuses, performed by a
  different actor.

- **Vendored-clone restore: UNVERIFIED.** Not investigated here; scope it before
  building.

### 4. Session-end sweep

NOT SHIPPED. A `SessionEnd` contract exists. This is the cheapest ask on the
list and the only purely observational one, so it is the natural first build.

### 5. `hooks-daemon agents` verb

**Name already taken** by the daemon-shipped agent-asset lifecycle (Plan 00279).
`harvest-background` covers part of the observability. A different verb name is
needed before this can be built at all.

## What Task 3.3 delivers, and what it does not

Shipped in this plan: Task 3.2's `subagent_cron_delete_blocker` — the half of
#41's cron concern that the protocol permits, pointed the safe way round.

NOT built here, deliberately. Asks 1 (hard cap), 2 (`auto_reap`) and 3 (cron
deletion) are three destructive or blocking controls. Phase 1 records the owner
approving #40 and #41 "together, as a cluster", which is authorisation to ACT on
the cluster — it is not a ruling on a contradiction that was not on the table
when it was given, because the contradiction only became concrete once Task 3.2
existed. Building `auto_reap` on the strength of a cluster-level approval would
be reading a decision into a sentence that does not contain it.

The open question for the owner, stated once: **#41 ask 3 wants the daemon to
delete crons on its own initiative; Task 3.2 has just denied a subagent that
operation. Which actor, if any, may delete a cron — and does cron attribution
by creating session id get built first, since without it the two are the same
act?**
