# Delta review (final gate): PR #226, owner_wait_stop_guard after the F1-F9 fixes

- Branch `plan-00636-stop-guard`, head `9d1a4f7b7`, worktree `.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`.
- Read-only. Light runs only: the six touched unit files (243 passed) and a `_text_declares_waiting` probe on 18 strings.
- Paths are relative to `src/claude_code_hooks_daemon/`; `G` = `handlers/stop/owner_wait_stop_guard.py`.

## Verdict

**Safe to merge for the shipped default, with follow-ups recorded before any adapter reads flags or a project sets `refuse`.**

With `on_unreadable_bus: auto` (default) and the v1 adapter (`flags_readable()` is False, `utils/owner_wait_bus.py:84-86`), the guard never denies on the normal path: it allows plus a one-shot advisory. The only live deny is the F5 fault path. No path found that loops the stop hook. The remaining defects (N1-N3) bite under `refuse`, a future flag-reading adapter, or a fault.

## F1-F9: fixed?

| #   | Status                                                                                      | Evidence                                                                                                                                                                        |
| --- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | Fixed on the normal deny path; **not** on the F5 fault path (N1)                            | `G:596-598` appends `stand_in_requirement`; shared gate `utils/stand_in_cron.py:156-174`; chain test `tests/unit/handlers/stop/test_owner_wait_stand_in_cooperation.py:149-186` |
| F2  | Fixed (whole declaring text, wider wordings, negation, quote blanking); over-broad now (N2) | `G:145-178`, `G:384-407`                                                                                                                                                        |
| F3  | Fixed: pass only on this rule's id in a recent block; spurious flag re-evaluated            | `G:431-455`, `G:463`; `utils/stop_hook_helpers.py:240-306`; id is in the reason via `under_rule` headline (`core/result_types.py:115-129`)                                      |
| F4  | Fixed: UNRESOLVED and ROLE_UNKNOWN stay armed as unconfirmed                                | `G:488-512`                                                                                                                                                                     |
| F5  | Fixed: any fault denies an armed seat once, static text                                     | `G:514-547`, `G:465-473`                                                                                                                                                        |
| F6  | Fixed: `--team` always named                                                                | `utils/owner_wait_bus.py:88-92`                                                                                                                                                 |
| F7  | Fixed: mentions and thread ids stripped, stopwords added                                    | `utils/owner_wait_check.py:56-69, 159-167`                                                                                                                                      |
| F8  | Fixed: `started_at` required, seconds documented                                            | `utils/owner_wait_check.py:118-128, 138-139`                                                                                                                                    |
| F9  | Fixed: only `awaiting-human` counts as the mode                                             | `G:409-418`                                                                                                                                                                     |

## Questions asked

**(a) Stand-in.**

- It cannot be dropped on the normal deny path.
- auto_continue_stop behaves as before. `stand_in_requirement` is a verbatim lift of the old inline checks: autonomy, focus, `persistent_crons.enabled`, then `stand_in_verdict` (`handlers/stop/auto_continue_stop.py:721-736`).
- Over-demand is possible but bounded. The guard's gate (`G:364-374`) is looser than auto_continue's (`auto_continue_stop.py:838-863`), see N4. It never loops, because `stand_in_verdict` returns None on any re-entry (`stand_in_cron.py:140-142`).

**(b) `auto`.**

- An invalid value fails closed to `refuse` (`G:307-318`).
- `auto` refuses only on a literal `True` (`G:329`), so a crafted config cannot turn it into an allow.
- A **raising** `flags_readable()` makes `auto` ALLOW with an advisory (`G:330-336`). That contradicts the F5 "any fault fails closed" contract (N3).

**(c) Spoofing the re-entry marker.**

- It cannot be spoofed on the first stop. The check runs only under the harness-owned `stop_hook_active` (`G:463`).
- Markers are matched only in two places: `user` entries whose STRING content starts with `Stop hook feedback:`, and Stop `hook_blocking_error` attachments. Assistant text is never a match. Tool results carry list content, so they never match either.
- Residual risk: the 200-line lookback (`G:143`) can see this guard's deny from an EARLIER stop chain. Example sequence:
  1. A short turn ends in another handler's deny.
  2. The next waiting re-stop finds the old rule id in the lookback and skips the check.
  3. Result: zero refusals in that chain.
- Rated LOW (N5).

**(d) False positives.** These are real and frequent (N2). They cost one extra turn per stop and do not loop: the advisory is suppressed on re-entry (`G:586-592` and `core/hook_result.py:784-786`), and a deny's re-stop takes the own-rule pass.

**(e) No team.**

- No runtime: `matches` returns False and nothing is read (`G:461`).
- Runtime present plus `whoami` exit 69: the state is ABSENT, `role_gate` returns NOT_APPLICABLE (`utils/team_role_gate.py:71-72`), no team is armed, and the stop is allowed. A fault there is allowed too (`G:532-533`). The only cost is one cached probe.

**(f) Advisory continue turn.** It is bounded, with no infinite loop:

- The guard suppresses the advisory under `stop_hook_active` (`G:588-591`).
- The formatter drops ALLOW context on re-entry.
- auto_continue treats the flagged re-stop as fresh. On that fresh stop it either allows a `STOPPING BECAUSE:` stop or denies once.

One caveat: while the awaiting-human mode is live, EVERY first stop of the coordinator is "waiting" (`G:417`), so each one pays the extra turn.

## New findings (ranked)

### N1 MEDIUM: the F5 fault deny drops the stand-in, and any guard deny still hides other Stop denies

- **Stand-in dropped:** `G:534` returns `_FAIL_CLOSED_REASON` without `_stand_in_reason`. On a fault during an `[awaiting-human]` coordinator stop, F1 is back exactly: the guard deny wins (`core/chain.py` first-restrictive), the re-stop is a confirmed re-entry, and both handlers stand down. No stand-in cron gets scheduled.
- **Other denies hidden:** F1 was fixed for the stand-in alone. Any guard deny also hides auto_continue's QA-failure deny, its tautological-question hard block and its goal-ledger challenge, and the re-stop skips them all (`auto_continue_stop.py:772-782`). Under v1 `auto` this is reachable only via N1's fault path. Under `refuse` or a flag-reading adapter it is reachable on every waiting stop.
- **Fix direction:**
  - Append the stand-in on the fault path too.
  - Either enable `collect_all_violations` for Stop, or have the guard stand aside when auto_continue would deny on a branch other than Branch 2.

### N2 MEDIUM: the widened F2 detector fires on ordinary non-waiting stops

`_PERSON` treats any capitalised word as a person (`G:150`), and `_HUMAN` includes `response|reply|decision|input` (`G:145-148`). The probe returned **True** for each of these:

- "Tests should confirm the fix on CI"
- "Docker needs to pick up the new image"
- "waiting for Renovate to rebase"
- "blocked on Docker daemon restart"
- "pending CI response"
- "Next to review is Plan 00641"
- "finished, waiting for Monday cron"
- "Phase 3 needs a decision record written next"
- "waiting for the worker reply on Q12"
- "pending the release decision ... (not blocking)"
- "Not blocked on anyone; Joseph to review later"

The last one is detected because negation is scoped to the first clause only.

**Impact by mode:**

- v1 `auto`: one spurious advisory and one extra turn per stop.
- `refuse` or a flag-reading adapter: one spurious deny that also triggers N1's hiding.

It never loops. **Fix direction:** drop the bare-capitalised `_PERSON` (keep `@handle` and a configured owner name), and narrow `_HUMAN` to owner, human and user nouns.

### N3 LOW: a raising `flags_readable()` fails OPEN under `auto`

`G:330-336` returns False on an exception, and the result is allow plus an advisory. This is inert under v1 (the method returns a constant). Under a future adapter that reads flags, a crashing probe silently downgrades every refusal. That conflicts with the module docstring's "A fault fails closed" (`G:39-43`). **Fix direction:** return True (refuse) on a raise, or route the raise into `handle()`'s F5 path.

### N4 LOW: the guard's stand-in gate is looser than auto_continue's

| Gate                | Message read                                                         | Requires `STOPPING BECAUSE:` | Requires the marker write |
| ------------------- | -------------------------------------------------------------------- | ---------------------------- | ------------------------- |
| Guard (`G:366-368`) | possibly stale `get_last_assistant_text()`                           | no                           | no                        |
| auto_continue       | freshness-resolved current message (`_resolve_current_turn_message`) | yes                          | yes (`marker_written`)    |

`_text_declares_waiting` also accepts the human-blocked shapes without the prefix (`G:394-395`). So a stop can be told to create a stand-in for a stop that never entered awaiting-human. The cost is a stray one-off cron that no-ops when no marker is live, and it never loops.

### N5 LOW: the own-refusal lookback spans earlier stop chains

`G:143` and `G:447-455` scan 200 tail lines. A rule-id hit from a previous chain grants the pass to a later chain that another handler denied first. **Fix direction:** require that the guard's marker is the LAST block marker, or that it falls after the last real user prompt.

### N6 LOW: an unreadable transcript makes every team-session stop "waiting"

With no transcript reader, `_waiting` returns UNREADABLE (`G:425-427`), and `matches` is True for every stop. On a coordinator under v1 `auto`, each such stop gets an advisory claiming "this stop waits on a human". This is rare in production.

## Not verified

- The exact transcript shape Claude Code writes for a Stop `additionalContext` continue (assumed: no `hook_blocking_error` marker).
- Live behaviour. No probe could stand up a coordinator seat.
