STOPPING BECAUSE: the round-2 review is done. The verdict is REQUEST CHANGES: the fixes added one new critical, and two round-1 findings are only partly fixed.

# Code Review, round 2: Plan 00479 Phase 4 pause gates (`origin/worktree-p479-pause-gate`, head d5c9d2552)

Reviewed: the round-1 diff c082efbbc to d5c9d2552 (26 files, +1539/−236).

**Probe:** `/workspace/untracked/scratch/p479-review/probe2.py`, run against `/workspace/untracked/scratch/p479-review/tree2/` (taken with `git archive`). Keep the script; it is the evidence for the findings below. The round-1 `probe.py` was not re-run because it imports names this head no longer has. `probe2.py` covers P2 to P7 again, plus P2b and P8 to P11. Line numbers below refer to the tree2 copy of `src/claude_code_hooks_daemon/`.

## Round-1 findings

| ID | Status | Evidence |
|---|---|---|
| C1 ToolSearch denied | **RESOLVED** | `utils/usage_pause_gate.py:93-95`. P7: `ToolSearch halted: False`. Step 0 of the directive names it (`:337-338`). New finding N1 undoes much of this fix. |
| C2 owner lockout | **PARTIAL** | (a) The ceiling is now re-checked on every held prompt (`handlers/user_prompt_submit/usage_pause_gate.py:161-167`). P5: with no ceiling, the prompt is allowed and the record is cleared. **Resolved.** (b) The `usage-pause clear` command exists (`daemon/cli.py` `cmd_usage_pause`), but the owner's next prompt undoes it while usage is still over the ceiling. P9: `decision: allow \| re-paused: True`, and the prompt carries "Do NOT act on the request". (c) The rule text (`:96-99`), the tool-gate verbose text (`:72`) and the CLI message ("the session then works again") all say the clear lifts the pause "at once". That is only true once usage is under the ceiling. The one real override while still over it is removing the ceiling from `hosts:`. See N4. |
| M1 read errors fail closed | **RESOLVED** (the read path) | `utils/usage_pause.py:233-239` uses `FileNotFoundError` instead of `exists()`. `active_usage_pause` is total (`usage_pause_gate.py:298-317`), and `current_breaches` catches `OSError` (`:526-530`). P2: `read_usage_pause: None`, and both the tool and stop gates return `False`. The new entry path brings back a fail-closed case (N3). |
| M2 date-pinned cron | **RESOLVED** | A pause needs at least 10 minutes of lead (`:84`, `:553`). The Stop gate checks the schedule (`handlers/stop/usage_pause_stop_gate.py:360-374`, `schedule_fires_in_window`). P3: entry with the reset 5 s away gives `None`, a past cron `fires in window: False`, a good one `True`. Two small gaps remain (N5, N6). |
| M3 entry only on a prompt | **PARTIAL** | Entry now also happens in the tool gate (`usage_pause_tool_gate.py:106-108`) and the Stop gate (`usage_pause_stop_gate.py:313-315`, `:329-332`). But the tool-gate entry is a `deny_and_halt`, which almost certainly stops the model from carrying out the directive (N2). |
| M4 no upper bound | **RESOLVED** | `MAX_PAUSE_SPAN_SECONDS` is in `utils/usage_pause.py:76,149-150`. The supervisor has the same check (`claude-supervise.py:2388,2435`), and a test pins the two equal. P4: `write refused: resume_at must be within 691200 s`. |
| Minor 1: missing session id | **RESOLVED** | Prompt gate `:144-147`, `try_start_pause:571-573`. P6: `allow \| unknown record: False`. |
| Minor 2: "lifted" after a failed clear | **RESOLVED** | Prompt gate `:200-205`, `render_lift_not_recorded_note` (`:469-481`). |
| Minor 3: dropped prompts reach other handlers | **RESOLVED** | Prompt gate `terminal=True` (`:113-118`). ALLOW does not end the chain, so the directive context still reaches the model. |
| Minor 4: docstring table | **RESOLVED** | `utils/cron_tick.py:8-13`. |
| Minor 5: duplicated schedule | **RESOLVED** | `FAILSAFE_CRON_SCHEDULE_HINT` in `utils/cron_enforcement.py:76`. |
| Minor 6: record read twice | **RESOLVED** | The Stop gate passes the record from `matches` to `handle` through `_found` (`:296`, `:318`, `:324`). A test checks the read count. |

## New findings, ranked

### N1. CRITICAL (confidence 85): the directive tells the model to run `date`, and the tool gate halts Bash
- **Location:** `utils/usage_pause_gate.py:347-351` (step 3: "Run `date` first: if this session's UTC offset differs…"), against `PAUSE_ALLOWED_TOOLS` (`:93-95`) and `usage_pause_tool_gate.py:124`.
- **Evidence:** P8: `directive asks for date: True`, `Bash date halted: True`.
- **What happens:**
  1. An obedient model runs CronList and CronDelete on every cron (step 2), then runs `date` (step 3).
  2. The `date` call is denied and the turn halts before CronCreate.
  3. The session is left with **no crons and no resume cron**.
  4. If Stop fires after the halt, the Stop gate repeats the same directive. The model runs `date` again and is halted again. The next stop has `stop_hook_active` set and is allowed.
  5. Either way, nothing wakes the session. The only exceptions are a human, or a ccy supervisor after the record expires. This is the same end state C1 described.
- **Why it matters for review:** this comes from the M2 fix, and no test checks that every step in the directive uses only allowed tools.
- **Fix:**
  - Delete the `date` instruction. Rely on "Check that CronCreate reports a next run of X" plus the Stop gate's schedule check.
  - Add a test that every tool the directive names is in `PAUSE_ALLOWED_TOOLS`.
- **Related, smaller issue:** the Stop gate reads the cron in the daemon's time zone. It therefore could not confirm a cron the model had converted to another zone; only the 1-day tolerance hides this.

### N2. MAJOR (confidence 75): pause entry from the tool gate halts the turn, so the model probably cannot carry out the directive
- **Location:** `usage_pause_tool_gate.py:106-108`, `:124`; the docstring claim is at `:22-23`.
- **Problem:** `CLAUDE/Code/HooksSystem.md:424-425` says `continue: false` "stops Claude entirely" and that `stopReason` is not shown to Claude. The first, entering call therefore ends the turn with the directive unread. The docstring's "The Stop gate then re-delivers the directive" only holds if Stop fires after a `continue: false` halt. That is unverified (RESEARCH.md:73 lists a neighbouring question as open).
- **What still works:** the hold drops cron ticks at no cost and lifts at the first tick after the reset, so usage stays capped for a session that has crons.
- **What does not:** the cron swap the protocol is built around does not happen, and a session with no crons sleeps until a human returns.
- **Subagents** (answering your question; P11):
  - The tool gate has scope `ALL`.
  - A subagent's tool call writes the shared session's record and halts the subagent with the directive.
  - The subagent is also barred from CronDelete (`R-SUBAGENT-CRON-DELETE`).
  - The coordinator only meets the directive as a halting deny on its next tool call. It sees it properly only if its own Stop fires.
- **Fix:**
  - On the **entering** call (`try_start_pause` just returned a pause), use a plain `deny` with the directive, without halting. Halt only on later non-cron calls, once the model has seen the directive.
  - Consider not entering from a subagent (`agent_id` present): write the record and allow, and let the main thread's gates deliver the directive.
  - Add both cases to the Task 4.8 live probe.

### N3. MAJOR (confidence 70): if the record can be written but not read, every tool call is halted and every Stop is denied, re-entries included
- **Location:** tool gate `:106-108`; Stop gate `:311-315`, `:329-332`.
- **Evidence:** P2b with the read failing (EACCES) and the ceiling reached: `tool call 1 halted: True`, `tool call 2 halted: True`, and `stop (stop_hook_active=True) -> deny` twice.
- **Why it happens:** each call sees "no pause", writes a new record, and is treated as a fresh entry. The fresh-entry path ignores `stop_hook_active`, so a fault traps the session in a stop loop. That breaks the "never a trap" rule M1 was meant to restore.
- **How likely:** the trigger (asymmetric permissions, read EIO) is narrow, but the loop has no bound.
- **Fix:** have `start_pause` read the record back through `read_usage_pause` and return `None` unless it reads as live. As a separate guard, never deny a stop with `stop_hook_active` more than once per session.

### N4. MAJOR (confidence 80): `usage-pause clear` is not an override while usage is over the ceiling, and the docs say it is
- **Location:**
  - `daemon/cli.py` `cmd_usage_pause`
  - Prompt gate `:88` and `:96-99`, the handler's CLAUDE.md text (`:246-248`)
  - Tool gate rule text (`:72`) and `render_lift_not_recorded_note` (`:480`)
- **Evidence:** P9. After a clear, the next prompt (or the next tool call, through N2's path) pauses the session again.
- **Fix, choose one:**
  - (a) Have `clear` write a per-session override marker valid until the deciding window's reset. `try_start_pause` honours it.
  - (b) Correct every one of those texts to say that clearing only helps once usage is under the ceiling, and that removing the ceiling from `hosts:` is the override.
- **Still to verify in Task 4.8:** whether a `!` bash-mode command goes through UserPromptSubmit or PreToolUse. If it does, the gates would intercept the escape itself.

**Your question on whether an agent can use `clear` to escape:** this is acceptable. In a paused session Bash is halted, so the model cannot run the command. Another session using `--session` can, but because of N4 the pause comes back on the next prompt or tool call while usage is over the ceiling. The command cannot be used to keep spending past the ceiling.

### N5. MINOR (confidence 75): a resume tick inside the lead time lifts the pause with false text
- **Location:** prompt gate `_resume` (`:181-190`); text from `render_resume_lifted_directive` (`utils/usage_pause_gate.py:441`).
- **Evidence:** P10: usage still at 97% with the reset 5 min away. The pause is lifted and the model is told "usage is back under the ceiling".
- **Effect:** at most 10 minutes of work over the ceiling. The same lead floor means a session that crosses the ceiling in the last 10 minutes of a window is never paused. That trade-off is reasonable but undocumented.
- **Fix:** a separate "resets within minutes; resuming" text, and a line in the docs about the 10-minute floor.

### N6. MINOR (confidence 70): the imminent-lift path in the Stop gate lets the session stop with possibly zero crons
- **Location:** Stop gate `:339-348`.
- **Problem:** after `clear_pause`, the stop is allowed with whatever the model left behind, which may be nothing or a cron pinned a year out. Nothing re-establishes the crons.
- **Fix:** deny with the lift directive ("re-establish crons, continue") instead of allowing.

## Your other questions
- **Pausing with no ceiling configured:** no. `current_breaches` (`:523-525`) returns before reading any usage data.
- **Pausing on stale data:** no false pause. Windows past `resets_at` read as absent, and within one window usage only grows, so an old snapshot can only under-report. `observed_at` is not checked, which is fine for that reason.
- **Exception coverage on the tool path:** `try_start_pause` catches only `(OSError, ValueError, RuntimeError)`. Any other exception from `effective_hostname` or the data layer, now on every tool call in every session, becomes a chain DENY because the gate is SAFETY-tagged. This is a suggestion only: catch `Exception` there, log it, and return `None`.

## Process notes from the builder's report
- `changed_tests` fails on 11 test files that are not mapped to any source.
- The `R-USAGE-PAUSE-TOOL` row in CLAUDE.md is not regenerated (`ToolSearch` is missing from it).
- Docs QA was not re-run after the `CONTRIBUTING.md` edit.

## Good work
- Every gate reads the same total predicate, and the entry logic is shared once (`PauseEnvironment`, `try_start_pause`).
- The Stop gate's schedule check is careful.
- M4 is mirrored in the supervisor, with a test pinning the two constants equal.
- The failed-clear note is honest.
- The tests are broad: M1 stand-down coverage across all seven handlers, and a read-count test.

## Verdict
**REQUEST CHANGES.** In order:
1. Fix N1: remove `date`, and add the test that the directive names only allowed tools.
2. Fix N2: no halt on the entering call; decide what a subagent does.
3. Fix N3: read the record back after writing it.
4. Fix N4: a real override, or correct the texts.
5. N5 and N6 can be filed as non-blocking.

C1, M1, M2, M4 and all six minors are resolved. C2 and M3 are partial.