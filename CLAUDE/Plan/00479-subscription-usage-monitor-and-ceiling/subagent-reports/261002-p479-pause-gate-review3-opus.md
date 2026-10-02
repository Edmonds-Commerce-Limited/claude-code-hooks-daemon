STOPPING BECAUSE: the round-3 review is done. The verdict is REQUEST CHANGES, with two blocking findings and four that can be filed as follow-ups.

# Code Review, round 3 (final): Plan 00479 pause gates, `origin/worktree-p479-pause-gate` 563b78f2a

Every round-2 finding (N1 to N6) is fixed, and all of the round-1 findings still hold. But this round introduced one enforcement regression: a subagent now runs past the ceiling with nothing stopping it. And the switch to UTC for the resume cron rests on no evidence. If `CronCreate` actually reads local time, a session on a host east of UTC can sleep for a year, and the Stop gate approves the dead cron.

**Evidence:**
- Probe: `/workspace/untracked/scratch/p479-review/probe3.py`, run against `/workspace/untracked/scratch/p479-review/tree3/` (taken with `git archive`).
- Output: `/workspace/untracked/scratch/p479-review/probe3.out`.
- `probe2.py` cannot run as it is, because it imports names this round removed. `probe3.py` ports P2 to P11 and adds P12 to P15.

## Round-2 findings

| ID | Status | Evidence |
|---|---|---|
| N1 `date` step | **RESOLVED** | The `date` step is gone from `_steps` (`utils/usage_pause_gate.py:689-694`). A test pins every tool the directive names to the allow-list (`tests/unit/utils/test_usage_pause_gate.py:520`). P8 gives `'Run \`date\`' in directive: False`. The cron's time zone changed as part of this fix; that is new finding R3-2. |
| N2 halt on entry | **RESOLVED for the main thread** | The entering main-thread call is a plain deny that carries the directive. P11 gives `main entering call halt: False \| directive: True`, and the second call halts. The subagent handling regressed (R3-1), and the per-session hand-off can race (R3-4). |
| N3 written but unreadable | **RESOLVED** | `start_pause` reads the record back and removes it on a mismatch (`:815-823`). P2b: `matched: False` on both tool calls and on all three stops, and `record file left behind: False`. |
| N4 clear is not an override | **RESOLVED** | The override marker is in `utils/usage_pause.py:470-534` and `start_pause` checks it (`:806`). P9: after a clear, the prompt is `allow`, it is not re-paused, and there is no context; the tool call is not matched. After the override ends, the session re-pauses. A different session (s9b) is not covered. The marker can be abused (R3-3). |
| N5 lift text inside the lead time | **RESOLVED** | P10: still paused, with the text "USAGE STILL OVER THE CEILING". The "back under the ceiling" wording now appears only when `verified_under_ceiling` is true. |
| N6 imminent lift in the Stop gate | **RESOLVED** | The Stop gate never clears the pause; `renew_pause` moves the resume time ahead instead (`usage_pause_stop_gate.py:152`). P15: a good cron is still accepted after the renewal, and an early resume tick is harmless because `is_resume_tick` ignores the time. |

## Round-1 findings, re-confirmed

- **C1:** P7, ToolSearch is not matched.
- **C2:** P5 (the ceiling is removed, so the prompt is allowed and the record cleared) and P9 (the override).
- **M1:** P2, `read_usage_pause` gives None and both gates give False.
- **M2:** P3, a past cron is refused and a good one accepted. The 10-minute floor is replaced by a 2-minute one (R3-5).
- **M3:** holds for the main thread; R3-1 is the hole.
- **M4:** P4, a 10-year record is refused.

## New findings

### R3-1. MAJOR, BLOCKING (confidence 80): a subagent over the ceiling is never paused, and can turn off the main thread's pause
- **Location:**
  - `handlers/pre_tool_use/usage_pause_tool_gate.py`, `matches` (`if in_subagent(...): return False`, about `:123-126`)
  - `tests/unit/handlers/pre_tool_use/test_usage_pause_tool_gate.py:228-229`
- **Evidence:** P11 gives `subagent over ceiling matched x3: [False, False, False] | record written: False`.
- **What happens:**
  1. While the main thread waits on an Agent call, it makes no tool calls. Its Stop is the only other gate, and it is scoped MAIN.
  2. So a long subagent, or several in parallel, keeps spending past the ceiling until it finishes.
  3. A subagent can also run `bin/hooks-daemon usage-pause clear` itself. That writes an override until the reset, so the main thread never pauses either.
- **Why it is a regression:** in round 2 the subagent's call entered the pause. The round-2 suggestion was to write the record and allow; this round does not write the record, and the test pins that misreading.
- **On the signal:** `in_subagent` (a truthy `agent_id`) is the project's real main/sub discriminator, as documented in `core/handler_scope.py:7-30`.
- **Fix:**
  1. In a subagent, call `try_start_pause` and return the plain `_SUBAGENT_REASON` deny.
  2. Keep a set of sessions whose pause a subagent started. The main thread's first call in such a session gets a plain deny with the directive (no halt); its later calls halt.
  3. Change the test to assert that the record is written.

### R3-2. MAJOR, BLOCKING until checked (confidence 75): the resume cron's zone changed to UTC with no evidence, and the failure on hosts east of UTC is silent
- **Location:**
  - `utils/usage_pause_gate.py`: `PauseEnvironment.tz = UTC` (`:779`), `resume_schedule` (`:617`), `schedule_fires_in_window` (`:670`)
  - The prompt gate's `_tz` setting
- **The gap:** the builder says the docs are silent, but the relevant page, `code.claude.com/docs/en/scheduled-tasks`, is not vendored. `tools-reference.md:35` links to it.
- **What happens if `CronCreate` reads local time, on a host at UTC+2:**
  1. The expression `32 12 …` meant as 12:32 UTC fires at 10:32 UTC.
  2. If 10:32 UTC has already passed, the cron next fires a year later.
  3. If it has not, it fires 2 hours early. The tick finds usage still over, and the next cron is pinned at or before "now", which also means a year away.
  4. In both cases the Stop gate reads the cron in UTC, finds it in the window, and allows the stop. Nothing wakes the session.
- **Why the builder's argument does not hold:** the claim that the one-day tolerance "delays rather than loses" is only true west of UTC.
- **Where it is invisible:** this container is UTC (`date` gives `UTC+0000`, `TZ` unset), so the problem does not show here.
- **Fix:** run `hooks-daemon remote-docs add https://code.claude.com/docs/en/scheduled-tasks` and use the zone that page states. A better option is to avoid pinned minutes altogether:
  - Use a recurring `*/10 * * * *` resume cron, which is the same in every zone.
  - Have `_resume` drop any tick before `resume_at` with a DENY, which costs nothing.
  - This also removes the "a year later" and lead-time fragility.

### R3-3. MINOR, FOLLOW-UP-OK (confidence 75): the override is capped only when written, and an unreadable marker counts as active forever
- **Location:** `utils/usage_pause.py:511-534`.
- **What it does right:** it is scoped to its own session (the payload's `session_id` must match; P9 s9b), and writes are capped at 8 days.
- **Evidence:** P13 gives `hand-written 10-year override honoured 9 years on: True` and `unreadable override active a year on: True`.
- **How it can be abused:**
  - The model can create the marker with Write or Bash before it crosses the ceiling. The ceiling is then never enforced again for that session.
  - The owner-only analogue, the upgrade-approval markers, is guarded against agent writes (`R-UPGRADE-APPROVAL-AGENT`). This marker is not.
- **Fix:**
  1. When reading, reject an `until` later than now plus `MAX_PAUSE_SPAN_SECONDS`.
  2. Bound an unreadable marker by its `stat().st_mtime` plus the same span.
  3. Add the override path to an agent-write guard.

### R3-4. MINOR, FOLLOW-UP-OK (confidence 70): the per-session `_entered` hand-off can race
- **Location:** the tool gate's `_entered` (`:103`, `:176`, `:205-207`).
- **Why it can race:** dispatch runs on executor threads (`daemon/server.py:2327`), and the set is keyed by session, not by tool call.
- **Evidence:** P12 gives `B (handled first) halt: False | A (the entering call) halt: True`, so the halt lands on the call that entered the pause.
- **Effect:** in practice the same as a correctly keyed parallel batch, where one call is denied and its sibling halts the turn. So in a batch of parallel calls that crosses the ceiling, the directive may still go unread.
- **Fix:**
  - Key `_entered` by `tool_use_id`.
  - Do not halt calls within a short grace period after `paused_at`, so the whole batch gets plain denies.

### R3-5. MINOR, FOLLOW-UP-OK (confidence 70): the 2-minute resume floor is tight, and a second miss is allowed with a dead cron
- **Location:** `build_pause` (`:595`) and `refresh_resume`.
- **Evidence:** P3 shows 124 to 141 seconds before the pinned minute passes.
- **The steps that must fit in that time:** ToolSearch, CronList, one CronDelete per cron (failsafe, persistent crons, watchdog), then CronCreate.
- **What happens on a miss:**
  1. The first miss is caught: the cron fires out of window, so the Stop gate denies with a new expression.
  2. A second miss arrives on a stop with `stop_hook_active` set, which is allowed with the year-out cron.
- **Fix:** raise the floor to 5 minutes. R3-2's recurring cron would remove the issue entirely.

### R3-6. MINOR, FOLLOW-UP-OK (confidence 70): the record read-back compares for exact equality and deletes on a mismatch
- **Location:** `utils/usage_pause_gate.py:815-823`.
- **Evidence:** P14 gives `A reads back its own: False` when two writers interleave.
- **Effect:**
  - Usually both writers return None, and the next call enters the pause again.
  - In one interleaving, B's directive is delivered and then A deletes B's record. This heals on the next call.
- **Fix:** accept any live record for this session as the read-back, and delete only when the read fails.

### Also worth filing
- **Location:** `daemon/cli.py`, the `except` around `current_breaches` in the `clear` path (about `:5177-5185`).
- **Problem:** it catches only `(OSError, ValueError, RuntimeError)`. Any other exception crashes the owner's escape command before it clears anything.
- **Fix:** catch `Exception`, the same as `try_start_pause` now does.

## Good work
- The read-back fix closes the N3 loop cleanly.
- The `verified_under_ceiling` wording is honest.
- The Stop gate never clears the pause, so it cannot strand a session.
- The test pinning every directive tool to the allow-list exists.
- The override is scoped to its own session and capped when written, and has tests for both expiry and the other-session case.

## Verdict
**REQUEST CHANGES.**
- **BLOCKING:** R3-1 (subagent bypass) and R3-2 (find out which zone `CronCreate` reads, or switch to a zone-independent resume cron).
- **FOLLOW-UP-OK:** R3-3, R3-4, R3-5, R3-6, and the CLI `except`.