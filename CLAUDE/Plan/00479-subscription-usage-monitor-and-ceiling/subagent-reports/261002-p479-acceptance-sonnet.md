STOPPING BECAUSE: Task 4.8 acceptance run complete; every step behaves as the plan says, one expectation-wording note below.

# Plan 00479 Task 4.8 acceptance run (Sonnet)

## Method

Mode used: (b), an in-process harness, not (a) a second daemon.

Why not (a): the handlers read project state through the process-wide `ProjectContext` singleton and the process-wide data layer, so everything the cycle needs can be pointed at a scratch project inside one throwaway Python process with no socket, no daemon start, and no risk to the live daemon at /workspace. A second daemon would have added nothing to what is under test (the handlers) and some risk (shared CLI/venv paths).

What is real and what is injected:

- Real `ProjectContext.initialize()` against `/workspace/untracked/scratch/p479-accept/proj/.claude/hooks-daemon.yaml` (its own git repo with a dummy origin). The daemon untracked dir resolved to `proj/.claude/hooks-daemon/untracked`, asserted to be under the scratch project.
- Real config: `hosts: accept-host: {pattern: p479-accept-host, usage_ceiling: {max_used_percent: 80}}` plus one declared `persistent_crons` job `accept-job`. The hostname comes from `HOOKS_DAEMON_HOSTNAME=p479-accept-host`, set inside the harness process only.
- Real usage path: Status payloads with `rate_limits` are folded in by the real `UsageTracker.update_from_status_event` (the exact call the controller makes), persisted to the scratch `usage-snapshot.json`, and read back through the default `latest_usage` loader. The status line handler `UsageIndicatorHandler` renders from the same snapshot.
- Real handlers: `UsagePauseGateHandler` (UserPromptSubmit), `UsagePauseToolGateHandler` (PreToolUse), `UsagePauseStopGateHandler` (Stop), `AutoContinueStopHandler`, `CronStopEnforcerHandler`, `CronSubagentStopEnforcerHandler`, `PersistentCronAssertorHandler`, `FailsafeCronSessionAdvisorHandler`, `UsageIndicatorHandler`.
- Injected: only the clock (a mutable value, so "advance past resume_at" is exact). Handlers are driven by calling `matches()` then `handle()`, the way the chain does; the chain itself (scope filter, priority order, response formatter) is NOT exercised.
- Synthetic session ids only: `accept-0001` to `accept-0004`, `accept-control`. Records exist only under the scratch project (verified: `/workspace/untracked/context-sidecar` holds no `accept-` file, `git status` of /workspace is clean). No `hosts:` entry was added to the live config. No daemon, supervisor or settings file was touched. No daemon instance was started, so there is nothing to clean up.

Files (scratch, not tracked): `/workspace/untracked/scratch/p479-accept/harness.py`, `harness2.py`, full outputs `run1.txt`, `run2.txt`. Run with `PYTHONPATH=/workspace/src /workspace/untracked/venv-workspace-py311-81c29529/bin/python <script>`.

## Results

PASS means the handler behaved as the plan's Phase 4 text says. Handler outputs are trimmed; full text is in run1.txt / run2.txt.

### Step 6 (run first): data safety, no `rate_limits`

Payload: Status with no `rate_limits`. Snapshot reads `None`. UserPromptSubmit `hello` gives `decision=allow`, no context. Tool gate and stop gate do not match. No pause record. **PASS.**

### Step 1: Status with five_hour 85%, resets in 2h

Payload `rate_limits = {"five_hour": {"used_percentage": 85.0, "resets_at": <T0+7200>}}`. Snapshot: `five_hour=UsageWindow(85.0, ...)`. Status line before pause: `📈 5h 85% 1h 59m` (orange chip). **PASS.**

### Step 2: UserPromptSubmit, normal prompt

Output: `decision=allow` carrying the directive as `context` (a block would not reach the model, per the handler docs):

```
USAGE CEILING REACHED - this session is PAUSED until 2026-10-02 16:36 UTC.
Usage: five_hour window at 85% (ceiling 80%). ...
Do NOT act on the request that arrived with this message ...
  1. CronList ...
  2. CronDelete EVERY cron listed: the failsafe recovery cron, every persistent_crons job, the watchdog ...
  3. CronCreate ONE cron: schedule `*/10 * * * *`, recurring: true, durable: false, with this exact prompt ... [tick:usage-resume] ...
  4. Subagents: do not start new subagents ... Let running subagents finish ...
  5. Stop with `STOPPING BECAUSE: usage paused until 2026-10-02 16:36 UTC` ...
```

Record written: `{"window": "five_hour", "used_percentage": 85.0, "ceiling": 80.0, "paused_at": 1790951667.78, "resume_at": 1790958987.0, ...}`; `resume_at` = `resets_at` + 120 s margin exactly. Status line while paused: `⏸ usage 16:36 📈 5h 85% 1h 59m`. A second prompt while paused: `decision=deny`, `R-USAGE-PAUSE-PROMPT`, "Paused on: five_hour window at 85% (ceiling 80%). Resumes about 2026-10-02 16:36 UTC." **PASS.**

Note: the host `resume_at` check is the only place that clock times appear; the cron itself names none.

### Step 3: PreToolUse

Main-thread Bash:

- When the pause was entered by the prompt gate (as in step 2, so the model already holds the directive), the FIRST Bash call is already `deny` + `halt_turn=True` with `stop_reason='Session paused on its usage ceiling: only the cron and subagent wind-up tools are allowed until the resume cron fires.'`. This is not what the task brief expected for "first", see Findings F1. It matches the handler's design: the plain, non-halting first deny is only for a pause THIS gate (or a subagent) started, which the model has not yet been told about.
- When the pause is entered by the tool gate itself (accept-0002, no prompt ever sent): call 1 is `deny`, `halt_turn=False`, reason carries the full directive (`CronDelete` ... `*/10 * * * *`); call 2 is `deny`, `halt_turn=True`. **PASS.**
- Pause started by a SUBAGENT call (accept-0003): the subagent call is never matched; the record is written anyway; main's first Bash is plain deny with directive; main's next call halts; subagent calls remain unmatched afterwards. **PASS.**
- `Agent` (main thread): `deny` + halt. **PASS.**
- `CronList`, `CronDelete`, `CronCreate`, `ToolSearch`, `SendMessage`, `TaskStop`: handler does not match (allowed). **PASS.**
- Subagent (`agent_id` present) `Bash` and `Agent`: not matched (allowed). **PASS.**

### Step 4: Stop

- `session_crons = [failsafe cron, resume cron]`: `deny`, "USAGE PAUSE NOT COMPLETE - session_crons holds 2 crons ... exactly ONE cron remains: the resume cron." plus the 4 numbered steps. **PASS.**
- `session_crons = [resume only, */10 * * * *]`: `allow`. **PASS.**
- Extra: resume cron on `5 14 * * *`: `deny`, "Its schedule `5 14 * * *` is not `*/10 * * * *`". Empty `session_crons=[]`: `deny`. Same Stop with `stop_hook_active=True`: `allow` (never a trap). **PASS.**
- Entry through Stop (accept-0004, never prompted): the first Stop is `deny` with the full directive even though the cron set was already right; the next Stop with only the resume cron is `allow`. **PASS.**
- Stand-down while paused (`matches()` False): `auto_continue_stop`, `cron_stop_enforcer`, `cron_subagent_stop_enforcer`. Controls: `cron_stop_enforcer` and `auto_continue_stop` match again after the pause lifts (step 5), and `cron_subagent_stop_enforcer` matches for an unpaused session, so the stand-down is caused by the pause. **PASS.**
- Extra (Task 4.4): `persistent_cron_assertor` and `failsafe_cron_session_advisor` do not match on a compact `SessionStart` while paused; both match for an unpaused control session. **PASS.**

### Step 5: resume ticks

- Tick (`[tick:usage-resume]` prompt) before `resume_at`: `decision=deny`, reason "Usage pause: the resume cron fired before 2026-10-02 16:36 UTC; the pause holds.", no context, record kept, usage not read. **PASS.**
- Clock advanced to `resume_at + 5 s`; no new Status: the five_hour window is past its `resets_at` so the snapshot reads `None`; tick gives `allow` and the pause lifts (record removed). **PASS.**
- Variant with a fresh 20% Status reading after re-pausing (accept-0001, clock `resume_at + 5`): `allow` with the lift directive, record removed:

```
USAGE PAUSE LIFTED - usage is back under the ceiling and the session may work again.
1. CronList ... The recurring resume cron (its prompt starts `[tick:usage-resume]`) still fires every ten minutes: CronDelete it now ...
2. Re-establish this session's crons ...
   - failsafe recovery cron: CronCreate recurring: true ... [tick:failsafe] ...
   - declared job `accept-job`: CronCreate recurring: true, schedule `17 * * * *`, prompt verbatim ... [tick:job:accept-job] do the declared thing
3. Then continue the active work where it stopped; the pause is over.
```

After the lift the tool gate no longer matches. **PASS.**

- Extra: tick after `resume_at` with the weekly window still at 95%: `allow` with "USAGE STILL OVER THE CEILING - seven_day window at 95% ... Do NOT create another cron ... until 2026-10-09 10:38 UTC"; record rewritten with the new `resume_at`. **PASS.**

### Step 6: see above (run first). **PASS.**

## Summary table

| Step                                                   | Result        |
| ------------------------------------------------------ | ------------- |
| 1 Status snapshot over ceiling                         | PASS          |
| 2 UserPromptSubmit directive                           | PASS          |
| 3 PreToolUse (deny, halt, allow-list, Agent, subagent) | PASS (see F1) |
| 4 Stop (block, allow, stand-downs)                     | PASS          |
| 5 Resume tick (early drop, lift, still-over)           | PASS          |
| 6 No `rate_limits`, no pause                           | PASS          |

Harness totals: harness.py 44 of 45 checks pass; the one FAIL (3a) is F1 and is an expectation mismatch in my script, not a defect. harness2.py (entry paths, SessionStart, subagent-started pause) 14 of 14.

## Findings

- **F1 (expectation, not a defect).** "First main-thread Bash: plain deny; second: deny + halt" holds only for a pause the tool gate or a subagent started. After the prompt gate enters the pause (the normal path, directive delivered as context), the first main-thread call already halts. This is the documented behaviour (`usage_pause_tool_gate.py` module docstring; round 4 report). If the brief's wording is the intended contract for every entry path, the plan text for Task 4.2 should say which entry each rule applies to.
- **F2 (limit of this run).** Handlers were driven directly, not through the daemon chain. Not exercised: the `HandlerScope.MAIN` filter on the stop gate, the response formatter and schema for `continue:false`/`stopReason` on the wire, and the real Claude Code treatment of a halting deny. Those need a live session or a full daemon instance; the plan's "live probe" wording could not be satisfied by this method alone. No cron tool was actually called, so "cron set reduced to the resume cron" was verified through the Stop gate's reading of `session_crons`, not by real `CronDelete`/`CronCreate`.
- **F3 (observation).** With the harness clock set near real time, a tick that arrives with no live record and usage under the ceiling would still give the lift directive (the round 4 report already notes this; not re-tested).
- No behaviour contradicting the plan was found in steps 1 to 6.
