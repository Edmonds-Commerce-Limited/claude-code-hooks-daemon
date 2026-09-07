# Plan 00337 — Phase 4/5 design: cron cadence and stop-event instrumentation

Durable design output extracted from `PLAN.md`, which was crossing its size
threshold. Everything here was derived by reading the code on 2026-09-07; the
narrative of how it was derived is in `JOURNAL/00337-Journal-26-09-07.md`
(entries 18:30, 18:40, 18:55).

This document is the specification Phase 4 and Task 5.0 are built against. If
implementation disagrees with it, the disagreement is the finding — record it
rather than quietly following the code.

## Phase 4 — the cadence algorithm

### Inputs

Both are reachable inside `failsafe_cron_blockage_suppressor`, which is where
Task 4.4 placed the backoff.

| Signal     | Source                                                   |
| ---------- | -------------------------------------------------------- |
| `declared` | `marker_is_valid(...)` — already computed in `handle()`  |
| `owed`     | `GoalLedger.live_plan_numbers(plan_dir)` being non-empty |

### The rows

| owed | declared | action                                    |
| ---- | -------- | ----------------------------------------- |
| yes  | no       | ALLOW every tick; reset cadence to hourly |
| yes  | yes      | back off, capped                          |
| no   | yes      | DENY — today's behaviour; reset cadence   |
| no   | no       | back off, capped                          |

Row 1 is the net doing its job: work is owed and the agent has not said it is
blocked, so it most likely stopped wrongly and the tick is the correction. It
must never be backed off — that is the case the cron exists for.

Row 3 is unchanged from today. Suppression there is already correct and
already tested; Phase 4 must not perturb it.

### The backoff (rows 2 and 4)

State is a **separate file** under the daemon's untracked directory —
session-scoped like the marker, but with its own lifetime:

```json
{"session_id": "...", "dropped_since_allowed": 0, "cadence_hours": 1}
```

It cannot share the marker file. The marker is cleared on any real prompt and
is absent whenever the agent has declared nothing — which is exactly row 4, so
sharing would erase the state precisely when it is needed.

On a tick in a backoff row:

- if `dropped_since_allowed + 1 < cadence_hours` → DENY and increment
- otherwise → ALLOW, reset `dropped_since_allowed` to 0, and double
  `cadence_hours` capped at 4

So the tick pattern is hourly, then every 2h, then every 4h, and never
sparser. That is Task 4.2's ceiling: backed off, never silent.

### Resets

Any genuine (non-cron) prompt resets `cadence_hours` to 1 and the counter to
0, in the branch that already clears the marker (Task 4.3). Rows 1 and 3 also
reset, so a session that starts producing again — or that declares a real
blockage — does not carry stale backoff into its next phase.

### Two things to be careful about

**Fail open, like every other path in this handler.** If the state file is
unreadable or the ledger raises, ALLOW the tick. A cadence bug that denied
everything would silently disable recovery, which is worse than a wasted turn
and invisible, because the symptom is nothing happening.

**Row 4 must never become row 3.** "No goals owed and nothing declared" is the
case where the ledger's blind spot bites, so it backs off rather than
suppressing. That is the whole reason the bottom row is not "silence".

## The ledger is narrower than it looks (Task 4.1b)

`live_plan_numbers` returns only entries that are **already in the ledger**
(so a plan for which a `/goal` was never set is invisible) **and** resolve to
`_STATE_IN_PROGRESS` (so `Not Started` maps to `_STATE_OTHER` and does not
count).

Both biases point the same way — towards "nothing owed", the direction that
backs the cron off. The concrete failure: a plan being ACTIVELY WORKED whose
header still reads `Not Started` is not counted as owed, so row 4 fires and
the net is withdrawn from a session that is working normally. That is a real
dependency on **Plan 00341**, which makes `Not Started` falsifiable.

## Prerequisite: the suppressor cannot reach the ledger yet (Task 4.5)

`auto_continue_stop._goal_ledger_challenge()` does:

```python
ledger_path = ProjectContext.daemon_untracked_dir() / LEDGER_FILENAME
plan_dir = resolve_plan_dir(ProjectContext.project_root(), self._track_plans_in_project)
live = GoalLedger(ledger_path).live_plan_numbers(plan_dir)
```

`self._track_plans_in_project` is injected by the registry, gated on
`plan_workflow is not None and "planning" in instance.tags`.
`FailsafeCronBlockageSuppressorHandler` is tagged WORKFLOW / AUTOMATION /
NON_TERMINAL / BLOCKING — **no PLANNING** — so today it would read an
attribute that was never set.

Two ways out:

- Add `HandlerTag.PLANNING`. Honest once the handler reads plan status, and it
  inherits the whole injected bundle — but tags drive filtering and reporting
  elsewhere, so this is a behaviour change beyond the one line.
- Resolve the plan directory independently. Narrower, but duplicates a
  resolution the registry already performs.

**Plan 00311 Task 1.1 hits the identical obstacle** in `dispatch_declaration`,
which also needs the configured plan directory and also lacks the tag. Two
handlers wanting the same injected value argues for one decision about how a
non-planning handler reaches plan config, not two local workarounds.

**Related trap.** `resolve_plan_dir` falls back to `PlanWorkflowConfig().directory`,
so a missing attribute yields "wrong directory → no goals found → back off" —
the wrong direction. The ledger consult therefore needs an explicit "could not
determine" state, distinct from "nothing owed", and it must behave like row 1
(tick).

## Task 5.0 — the stop-event discriminator

`stop-events.jsonl` records `decision`, `reason_prefix`, `stop_hook_active`,
`timestamp` and (when applicable) `marker_written`. Nothing joins a row to the
turn it came from, which is why Task 5.1 is blocked on instrumentation rather
than effort.

Add two fields to `_log_stop_event`:

- **`session_id`** — free, already in `hook_input`. Separates sessions, but
  cannot tell two stops within one session apart.
- **`transcript_bytes`** — the discriminator that actually settles it. The
  transcript is append-only, so its size is monotonic within a session and
  reachable in O(1) via `stat`, with no parsing.

Task 5.1's classification then becomes arithmetic over the ledger:

| between consecutive records | meaning                                     |
| --------------------------- | ------------------------------------------- |
| size unchanged              | one stop logged twice — a hook re-fire      |
| size grew a little          | a text-only turn that stopped again — waste |
| size grew a lot             | work happened — the DENY was productive     |

Both fields must honour the existing contract: `_log_stop_event` swallows its
own errors, so a missing transcript or a failed `stat` omits the field rather
than breaking the line.
