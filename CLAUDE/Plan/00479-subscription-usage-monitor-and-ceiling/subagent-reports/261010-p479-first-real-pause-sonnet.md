# Plan 00479: why the usage ceiling did not pause the session before the weekly hard limit

Read-only investigation. Sources: main transcript (lines about 12600-12760 and 26285-26330), `src/claude_code_hooks_daemon/utils/usage_pause.py`, `utils/usage_pause_gate.py`, `daemon/cli.py` (`cmd_usage_pause`), `handlers/user_prompt_submit/usage_pause_gate.py`, `handlers/status_line/usage_indicator.py`, `docs/guides/CONFIGURATION.md`, release note 213 (v3.67.0-to-v3.68.0).

## Q1. Who wrote the override

A human, with a `!` command typed in the session. Evidence:

- Record at 2026-10-08T14:59:50.768Z is a user record whose content is `<bash-input>bin/hooks-daemon usage-pause clear</bash-input>`. The `<bash-input>` and `<bash-stdout>` pair is the shape Claude Code writes for a user `!` command. It is not an assistant `tool_use`.
- The stdout record (15:00:00.357Z) reads: "Usage pause cleared ... Until 2026-10-09 23:00 UTC (the latest reset among the windows over the ceiling, at most 8 days) no pause will be started for this session, even if usage is still over the ceiling." The same output says the session's crons were replaced by the pause.
- It is the only `<bash-input>bin/hooks-daemon usage-pause` record in any transcript under /root/.claude/projects/-workspace/. The other transcripts (120a0cfb, 9679b063, e5e72775, ec5d431d) have no such record. The only other file mentioning the phrase is e5e72775, as guidance text.
- No assistant Bash `tool_use` of `usage-pause clear` exists in 14:42-15:05. The assistant's calls in that window are release-QA waits. Its first reaction (15:00:13) was to restore the crons the pause had removed, so it treated the clear as a human action.
- The agent could not have run it while paused anyway: `R-USAGE-PAUSE-TOOL` denied Bash at 14:52:36-37.

Sequence:

1. 14:52:36: the pause is in force and Bash is denied.
2. 14:52:46: the ccy supervisor injects `/compact` saying the session is PAUSED until 2026-10-09 23:02 UTC.
3. 14:53:59: compaction ends.
4. 14:59:50: the human runs `! bin/hooks-daemon usage-pause clear`.
5. 15:00: the agent resumes release work. The release gate and its QA legs were running, and the owner's standing ask was to ship the release.

## Q2. What the session saw at 14:52

The `R-USAGE-PAUSE-TOOL` deny text and the supervisor message carried this directive:

- "USAGE CEILING REACHED - this session is PAUSED until 2026-10-09 23:02 UTC."
- "Usage: seven_day window at 80% (ceiling 80%)."
- Window: seven_day only. Percentage: 80% exactly, at the ceiling. Resume: 23:02 UTC on 10-09, which is the window reset plus the 2-minute resume margin.

The deny text and the prompt-gate text both told the human: type `! bin/hooks-daemon usage-pause clear`; "no pause is started for this session again until the latest reset among the windows over the ceiling (at most 8 days)". The clear command's own stdout repeated that no pause would start "even if usage is still over the ceiling". So the owner was warned at the moment of clearing.

## Q3. Was the session told while the override was active

Nothing told the model. The override was silent to the session.

- A scan of the main transcript from 10-08 15:00 to 10-09 23:35 found no hook context saying "override active" or "usage at N%". The matches were code-reading output and file listings, such as the marker listing showing `10-08_14:59 ...usage-override`.
- The code agrees. With an override active, `start_pause` returns `None` after a single `logger.info("... the owner's override is active, not pausing")` in the daemon log. There is no context injection, no deny and no status chip. The `⏸ usage` chip only renders from an active pause record, and the override exists precisely because that record was removed.
- The status line is the only passive signal. It shows the usage percentages (coloured bands) and a `⛔ 80%` ceiling chip, so a human watching it could see usage over the ceiling. It has no override awareness: no "override until HH:MM" and no warning that the ceiling is being ignored. The model does not see the status line.
- The first model-visible signal after the override was the 10-09 23:35 pause directive, after the override expired. In the interim, subagents hit HTTP 429 weekly-limit errors (from about 22:30 UTC). The transcript has 429 mentions from those failures. Those are provider errors, not a daemon warning, and they came after the ceiling had been exceeded.

## Q4. Does the design say the override should outlast a reset, and can it hide a later breach

What the design says (code comments, CONFIGURATION.md, release note 213, the prompt-gate text) is the same everywhere. `clear` records an override "until the latest reset among the windows over the ceiling (at most 8 days): while it is valid no pause is started for that session, even though usage is still over the ceiling. It then ends by itself and the ceiling applies again."

The design therefore intends:

- Suppression holds while usage is over the ceiling, until the reset of the breaching window(s).
- It expires at that reset, not at some earlier "usage fell below the ceiling" point.
- It does not say the override should stop applying when the breaching window has reset.

In the code, `cmd_usage_pause` computes `until = max(record.resume_at - margin, resets_at of each current breach)` and `write_usage_override` caps it at now + 8 days. `usage_override_active` is only `now < until`. It never re-reads usage and never looks at which window or how high.

So yes, "latest reset among the windows over the ceiling" can hide a later breach, in three ways:

1. **Same window, after the cap.** The override was written at 80% on the seven_day window. Usage kept rising to 100% inside the same window, up to its hard limit. The gate was blind the whole time. Hidden span: the entire remaining window. Here that was 14:59 on 10-08 to 23:00 on 10-09, about 32 hours. In general, up to the window length (7 days) and never beyond the 8-day cap.
2. **A different window.** `until` is the max of the breaching windows' resets, but the override suppresses every window. If only five_hour was over, `until` would be at most 5 hours away. If seven_day was over, a five_hour breach is hidden for up to 7 days. The override is not scoped per window.
3. **Reset slip.** The override's end (23:00) is a snapshot of `resets_at` at clear time. At 23:35 on 10-09 the daemon reported the seven_day window at 100% with its next reset at 2026-10-11 08:02, not a freshly reset window. So the clock the override trusted differed from the live one, and the override ended while the account was still over. This is consistent with the account's real weekly window moving, but I could not confirm why from the transcript. Treat it as an open question for the plan.

Note the clear command's output says the same thing in words ("even if usage is still over the ceiling"). The behaviour matches the documentation. What is missing is any feedback loop: no re-arm threshold, no hard-limit backstop, and no visible indicator that an override is in force.

## Conclusion

The pause did start (14:52, at 80% exactly). It was lifted deliberately by the owner with `! usage-pause clear` at 14:59:50, which wrote an override to 23:00 on 10-09. Nothing in that period could re-pause the session, and nothing told the model or the human that usage had passed 80%. The ceiling worked as designed; the override design has no upper guard.

Candidate fixes for the plan, not implemented:

- Cap the override by percentage as well as time. For example, still pause if any window reaches a hard threshold such as 95%, or rises more than N points above the level recorded at clear time. Store that level in the marker.
- Make the override per-window, or at least record which windows it covers.
- Emit a warning context on each prompt while an override is active and usage is over the ceiling, and add a status-line chip such as `override until HH:MM`.
- Re-read `resets_at` instead of trusting the snapshot, or end the override when the live reset moves.
