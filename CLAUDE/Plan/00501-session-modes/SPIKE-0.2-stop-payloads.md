# Spike 0.2: Stop payloads and record order during a goal re-arm

Plan 00501 Task 0.2. Evidence only, no production code. Sources: the two main-session transcripts under
`~/.claude/projects/-workspace/` (`e5e72775…`, Claude Code 2.1.273 to 2.1.291; `c61663f0…`, 2.1.288 to 2.1.307),
`untracked/stop-events.jsonl`, the supervisor's `untracked/supervise/decision.log`, the vendored contract
`contracts/claude-code-hooks/Stop.json` and `remote-docs/code.claude.com/docs/en/hooks.md`. The jq filter used for
the timelines is `untracked/scratch/spike501-timeline.jq` (not tracked).

## 1. `goal_status` attachment: settled (fact-check item 10)

`goal_status` exists and is structured. It is a transcript record of `type: "attachment"` whose `attachment` is:

| Variant                  | Fields                                                              | Count (e5e7 / c616) | Meaning                                                                                                                                            |
| ------------------------ | ------------------------------------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| evaluation, unmet        | `type, met:false, condition, reason`                                | 28 / 79             | One evaluator verdict. **This is the record the detector counts.**                                                                                 |
| evaluation, met          | `type, met:true, condition, reason, iterations, tokens, durationMs` | 16 / 12             | Goal achieved; Claude Code then clears the goal itself (a later `/goal clear` answers "No goal set").                                              |
| snapshot `sentinel:true` | `type, met, sentinel:true, condition` (no `reason`)                 | 175 / 100           | A state snapshot, not an evaluation. Written when a goal is set, after every `/compact`, at skill loads, and when `/goal clear` runs (`met:true`). |

`iterations`/`tokens`/`durationMs` appear only on a met evaluation, so the design report's `"iterations"?` is right
that the field is optional; a `met:false` record never carries it. **The detector must ignore `sentinel:true`**,
otherwise every compaction counts as an unmet evaluation.

## 2. The goal is a prompt-type Stop hook

Setting a goal writes `<command-name>/goal</command-name>` (a `user` record), `<local-command-stdout>Goal set: …`,
and a meta `user` record "A session-scoped Stop hook is now active with condition: …". The evaluator appears in
`stop_hook_summary.hookInfos` as a second hook whose `command` is the condition text (`hookCount: 2`), beside the
daemon's `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/stop`.

## 3. Record order of one loop cycle (observed, 2.1.296, 2026-10-11 13:00:57 to 13:01:33)

```
assistant           text "STOPPING BECAUSE: [awaiting-human] …"
attachment          hook_success  hookName=Stop  stdout "{}"          <- the daemon's Stop hook answered allow
user (isMeta:true)  "Stop hook feedback:\n[<condition>]: <reason>"    <- the evaluator's block, fed to the model
attachment          goal_status   met:false  reason:"Not satisfied. …"
system              stop_hook_summary  hookCount:2  preventedContinuation:false  stopReason:""  hookErrors:[]
assistant           (next stop text; the turn continues, no human record in between)
```

Points the detector must respect:

- The evaluator's block is **not** visible as `preventedContinuation:true`. Every one of 2,072 + 3,090
  `stop_hook_summary` records has `preventedContinuation:false`; the block shows only as the meta `Stop hook feedback:` user record plus `goal_status met:false`.
- The `Stop hook feedback:` record is `type:"user"` with `isMeta:true`. A "genuine human prompt" test must exclude
  `isMeta` records, or every cycle looks like the human came back.
- The daemon's Stop hook runs **in parallel** with the evaluator (docs: "All matching hooks run in parallel"), and
  the `goal_status` record is written after both hooks finish (timestamps above). Inferred, not separately
  tested: a Stop handler reading the transcript sees the verdict on the previous Stop, not on its own. A cycle is
  therefore observable one Stop late; the thresholds in Task 6.2 must count that way.

## 4. How a loop ends today: Claude Code's own cap, then the goal pauses

The 9th consecutive block in one turn ends it:

```
system informational warning  "A hook blocked the turn from ending 9 consecutive times — overriding and ending turn.
                               For Stop/SubagentStop hooks, check stop_hook_active … Set CLAUDE_CODE_STOP_HOOK_BLOCK_CAP to raise this limit."
system informational notice   "Goal paused · goal checks kept finding it unmet this turn · send a message to continue"
system turn_duration
```

Six cap events on 2026-10-11 (13:01, 13:03, 13:39, 13:58, 14:28, 14:38, version 2.1.296), five of them followed by
the "Goal paused" notice (13:58 was not). The
count is consecutive blocks with no tool call: the 12:59:48 Agent call reset it and the run started again. What
re-arms the paused goal is the next message: at 13:01:37 the supervisor typed `/compact`, a `goal_status sentinel:true met:false` snapshot re-armed it at 13:02:24, the supervisor's post-compact `🤖 [ccy-supervisor …] continue` at 13:02:31 started a new turn, and a second nine-block run followed. So a **goal loop is a chain of
capped turns, each restarted by a supervisor `continue`, a cron tick or a task notification**, not one endless
turn. This confirms Ruling 7 (suppress the post-compact `continue` under BLOCKED) as necessary, not cosmetic.

## 5. `stop_hook_active` in real payloads

Stop hook input (contract `Stop.json`, docs `hooks.md` "Stop input"): the common fields (`session_id`,
`transcript_path`, `cwd`, `permission_mode`, `hook_event_name`) plus `stop_hook_active`, `last_assistant_message`,
`background_tasks`, `session_crons` (both conditional: absent is not empty) and `effort` when the model supports it.

`stop-events.jsonl` records `{timestamp, session_id, stop_hook_active, decision, reason_prefix, transcript_bytes}`
only when `auto_continue_stop.matches()` is true (`auto_continue_stop.py:1260`, call sites 822-926). Totals:
794 `true/allow`, 444 `true/deny`, 4,264 `false/allow`, 933 `false/deny`. In the 13:00-13:04 loop window the
transcript shows about 25 Stop firings but the log has five lines, which matches `matches()` standing down on a
re-entry whose transcript tail carries a block marker (`auto_continue_stop.py:765-779`). Two findings follow:

- `stop_hook_active` **stays true for the rest of a continued turn, across tool calls.** 13:02:56 logged
  `stop_hook_active:true` although the turn made Bash and Read calls after the 13:02:43 evaluator block. A
  detector cannot read `stop_hook_active` as "the previous Stop was blocked".
- The design report's F5 holds with a refinement: `auto_continue_stop` skips a re-entry only when it finds a block
  marker in the tail. When tool calls push the evaluator's feedback out of the tail, it treats the Stop as fresh
  (the "silent-stop" path). Either way it cannot count cycles, so the separate detector of Task 6.x stands.

`untracked/payload-capture/` is empty, so no raw Stop JSON was captured. The headless capture attempted in spike
0.3 could not authenticate (see SPIKE-0.3), so the field list above rests on the vendored contract plus the
`stop-events.jsonl` projection, not on a raw dump.

## 6. Consequences for Phase 6

- Extract: `goal_status` with `met:false` and no `sentinel`; `isMeta` user records are never human; a
  `/goal` local command or `Goal set:` queued command marks a (re)arm; `informational` "Goal paused" marks Claude
  Code's own pause.
- Count cycles across capped turns: the run spans turns joined by `continue`/tick prompts, so the window (30 min)
  matters more than consecutive stops inside one turn.
- A `continue` typed by the supervisor starts with `🤖 [ccy-supervisor`; a tick starts with `[tick:`. Neither is
  a genuine human prompt (F2).
