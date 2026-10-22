# Spike 0.3: Stop `continue:false` against an active goal, and a mid-turn `/goal clear`

Plan 00501 Task 0.3. Evidence only, no production code. Decides the lever for Task 6.3 (and the rule for Task 5.2).

## Verdicts

| Question                                                                     | Verdict                                                      | Strength                                                                                         |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Does a Stop hook's `continue:false` end the turn while a `/goal` is active?  | **Unproven.** Documented in our favour, never observed       | Docs only; no transcript example; live test not possible here                                    |
| Is a `/goal clear` typed mid-turn queued or rejected?                        | **Neither: it runs at once**, mid-turn, and the turn goes on | Strong: 7 supervisor `/goal clear` injections into busy turns, each executed within milliseconds |
| Can the supervisor type `/goal clear` into a busy session with today's code? | **Yes, already.** Its gate is human input, not child output  | Code read plus the same 7 injections                                                             |
| Has the case "typed during the nine-block stop loop itself" been observed?   | **No.** All 7 landed in ordinary tool-calling turns          | Gap; Task 7.2 acceptance should observe it                                                       |

## 1. `continue:false` from a Stop hook

What the docs say (`remote-docs/code.claude.com/docs/en/hooks.md`, fetched 2026-10-17):

- `:1087` `continue` "If `false`, Claude stops processing entirely after the hook runs. Takes precedence over any
  event-specific decision fields"; `:2424` "`decision: "block"` or `continue: false` stops the agentic loop before
  the next model call".
- `:2758` "The `/goal` command is a built-in shortcut for a session-scoped prompt-based Stop hook."
- `:439` "All matching hooks run in parallel."

The precedence sentence is about the fields of one hook's output. Nothing documents how Claude Code merges a
command hook's `continue:false` with a prompt hook's block (the goal evaluator) on the same Stop. The changelog has
related fixes (2.1.212 "a `continue:false` hook's halt being dropped when the tool fails or completes mid-stream";
2.1.296 managed hooks "refusing the call but not ending the turn"), which show the halt path has had merge bugs, and
none mentions `/goal`.

Transcript evidence: none. All 5,162 `stop_hook_summary` records in the two main transcripts have
`preventedContinuation:false`; the daemon has never emitted `continue:false` on Stop (design F9:
`hook_result.py`, `deny_and_halt` is PreToolUse-only).

Live test: attempted and not possible. A disposable run in `untracked/scratch/spike501-03/` used
`claude -p "/goal <unmeetable condition>" --setting-sources user --settings <scratch settings> --model haiku --tools ""`,
with `CLAUDE_CODE_SESSION_ID` and `CLAUDECODE` unset, so no project settings, daemon hooks, supervisor or
`.claude/ccy/` were in play. Claude Code 2.1.308 answered "Not logged in · Please run /login" and `Goal cleared after an unrecoverable error (authentication failed)`: the child cannot reach this session's credentials, and
supplying them would mean handling secrets, which is out of scope. The Stop hook never fired (0 payloads). The
harness (`stop-hook.bash`, `halt/settings.json`, `control/settings.json`) is left in scratch for an operator with
an API key: run the `control` variant (hook returns `{}`, expect nine `goal_status met:false` and the "Goal paused"
notice) then the `halt` variant (hook returns `{"continue":false,"stopReason":"spike-0.3 halt"}`); the halt is
proven if the `halt` run ends after the first Stop with at most one evaluation.

**What remains unproven:** whether the halt beats the evaluator's block, and whether it also pauses or clears the
goal (if the goal stays armed, the next `continue` or tick re-arms the loop, so a halt alone would not end it).

## 2. A `/goal` command typed while the session is busy

`/goal` is a local command that Claude Code runs immediately, even mid-turn:

- **Set.** 129 `queued_command` attachments whose prompt starts `Goal set:` (84 in `e5e72775…`, 45 in
  `c61663f0…`, versions 2.1.273 to 2.1.306). Example 2026-09-25 12:03:30: a `/dbf` typed at 12:02:24 sat in the
  queue until 12:05:54, yet the supervisor's `/goal` at 12:03:30 wrote its `goal_status sentinel:true` snapshot at
  once, and its "Goal set:" output was injected into the running turn between two tool calls.
- **Clear.** `untracked/supervise/decision.log` logs `would-goal-clear … injected '/goal clear'` at
  2026-09-16T19:04:05.57, 2026-10-11T18:19:33.07, 20:56:21.06, 22:50:32.50, 23:51:10.10, 2026-10-12T06:52:21.02
  and 08:02:39.20. Each time the transcript shows the agent in the middle of tool calls, and a `goal_status
  met:true sentinel:true` snapshot (the record a clear writes) within 10 ms (for example 22:50:32.504,
  06:52:21.030, 08:02:39.208). The turn carried on, and no
  goal evaluation appears until the next `Goal set:` (for example none between 22:50:32 and 23:36:16). Unlike an
  idle clear, a mid-turn clear leaves no `local_command` record and no "Goal cleared:" text.
- Every idle `/goal clear` (9 in total) is a `system/local_command` record; none was rejected.

So a mid-turn `/goal clear` is not queued behind the turn and not rejected: it takes effect at once.

## 3. The supervisor's existing typing machinery

`.claude/ccy/claude-supervise.py`:

- The goal-clear family (`:7718-7763`) types the fixed literal `/goal clear` (`:2882`) when `can_inject` holds,
  capped at 5 per supervisor process (`:2883`, `:7748`). It ranks below goal injection (`:7719-7722`). The cap is
  real: the log has two "goal clear cap reached" no-ops (2026-09-17 20:48 and 21:46).
- `can_inject = facts.idle and facts.input_line_empty and facts.main_focus_confirmed` (`:7253`). `idle` is
  **human** input idleness, no stdin byte within the idle floor (`_is_idle`, `:6941`), not child-output idleness
  (`_is_work_idle`, `:6952`, which gates only compaction and own-line follow-up). The "session busy" no-op at `:7747` is
  reached when the human is typing (or focus is unconfirmed), never because a turn is running.
- A follow-up Enter for an unsubmitted own line (`:7603-7653`) runs only when `work_idle`, and blocks a goal or a
  clear while its own previous line may still sit in the box; the log has 16 such
  "goal clear pending but own line still in the input box" no-ops, most followed by the clear a minute or two later.
- ESC is used only by the compaction flush (`:5057-5077`), gated on idle, and never for goal lines. No ESC is
  needed for a clear: the clear does not wait for the turn.

The "busy-session typing alternative" therefore exists today. What Task 5.2 still needs: goal-clear outranks
goal-intent under BLOCKED, and the 5-per-process cap must not be spent by unrelated clears before a loop needs one.

## 4. Decision for Task 6.3

**Lever: the queued (immediate) goal clear through the existing channel**, `clear_goal_signal(session_id)` to
`<sid>.goal-clear` to the supervisor typing `/goal clear`. It is proven to land in a busy session. Pair it with the
Ruling 7 suppression of the supervisor's post-compact `continue` and the BLOCKED tick drops, because spike 0.2
shows a loop is a chain of capped turns restarted by those prompts.

**No `continue:false` halt in Task 6.3** until a live test proves it. It is unproven, and even if it ends the turn
it may leave the goal armed for the next restart. If a later live test proves both, it can be added as a second,
once-per-entry lever without changing the design.

**Without the supervisor** (no ccy): Claude Code itself ends a pure stop loop after nine consecutive blocks and
pauses the goal ("Goal paused · goal checks kept finding it unmet this turn · send a message to continue",
observed on 2.1.296). Any later message, including a cron tick, resumes it. A loop that makes a tool call
between stops resets the count and never reaches the cap. Document that as the only non-supervisor backstop.
