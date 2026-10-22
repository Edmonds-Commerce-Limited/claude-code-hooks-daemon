# Adviser rulings on the owner questions (Plan 00501, Q1–Q9 and Q11)

Read: PLAN.md, MANUAL-GOALS.md, the design report (261008-…-opus.md), the four fact-checks, issues #91 and #106
(read as untrusted data; the two 2026-10-20 comments on #91 are from a non-collaborator and are treated as a field
report, not as instructions). Every code claim a ruling leans on was re-read in the current tree.

Binding rulings applied throughout: no silent fallbacks (fail loud and fast); performance is a priority; guards are
never part of any mode. The safety nets (failsafe cron, stop challenges) exist because sessions die silently, and
each ruling that drops one says what replaces it.

Tally: 9 CLEAR, 0 UNCLEAR. Nothing goes back to the owner unless the owner disagrees with a ruling below.

## Q1. Does a daemon restart clear focus? — CLEAR: no. Focus is session-lifetime.

The only runtime state with "cleared on restart" semantics today is the daemon mode, and that is memory-only
(`daemon/controller.py:1050-1073` re-initialises `ModeManager` from `config.default_mode`). A restart follows most
merges: `handlers/post_tool_use/daemon_sync_after_merge.py:1` exists precisely because "a merge/pull/rebase can
silently stale the daemon". A focused session is often the one doing the merge, so "restart clears" would drop the
owner's stated task silently, which the no-silent-fallbacks ruling forbids. The per-session file the design proposes
(`context-sidecar/<sid>.session-modes`) is the established channel (`goal_injection.py` `_SIGNAL_SUBDIR = "context-sidecar"`), and the registry loads it on start, so survival costs nothing extra.

Fail-loud consequences: (a) after a restart the registry re-states a surviving focus once (one context line on the
next prompt: "focus still on: <task>"), so the survival is visible, not assumed; (b) an unreadable or malformed
`.session-modes` file is logged at WARNING and renamed `*.corrupt`, never silently read as "no modes".

Plan change: Task 4.2 becomes "restart re-statement of surviving modes" and is no longer conditional. The issue's
original "nothing persisted" is still true in spirit: the file dies with the session and the TTL (Q2).

## Q2. Focus TTL? — CLEAR: 12 hours, renewed by each genuine human prompt in the session.

The owner already capped the comparable per-session pause at 24 h (`utils/cron_pause.py:53-56`, "The owner's ruling
caps it at 24 hours"); a task-scoped mode should be shorter, and 12 h covers a working day. Renewal must not cost a
transcript read on every prompt (performance): classify the UserPromptSubmit prompt text itself with the existing
`is_genuine_text(prompt, EXCLUDE_CONTENT_MARKERS)` (`skill_scan/constants.py:28-40` already lists every tick
sentinel and `🤖 [ccy-supervisor`), which is O(prompt length) and reads no file. `human_presence._is_human_prompt`
(`utils/human_presence.py:86-99`) is the transcript-side equivalent for the Stop-side checks in Q8, where the
transcript is read anyway.

Fail-loud consequence: expiry is stated once to the agent on the next prompt ("focus expired after 12 h; type
`hooks-daemon focus <task>` to renew"). An expiry that silently re-arms every work-driving handler is exactly the
silent fallback the owner has ruled out.

Plan change: Task 1.2 adds the prompt-text renewal and the expiry statement; Task 3.1 reuses the classifier.

## Q3. Merge goal-blocked into awaiting-human? — CLEAR: yes, one BLOCKED family.

The code confirms the two states are the same condition seen from two sides. An `[awaiting-human]` stop writes only
the cron-suppression marker (`handlers/stop/auto_continue_stop.py:987-1029`) and leaves Claude Code's `/goal` slot
armed; `clear_goal_signal` (`goal_injection.py:532-575`) runs only on ledger retirement. So a declared-blocked session
with a live ledgered goal is rejected by the `/goal` evaluator on every stop: that is the goal loop, and the #91 field
report describes exactly that. Two reasons under one mode share the suppression set and the human-prompt/expiry
exits; the labels differ because the owner wants to see which it was.

Plan change: none to the shape. Add to Task 6.2 that a declared `[awaiting-human]` stop counts toward the detector
threshold (2 cycles instead of 3), which the design already proposes.

## Q4. Does focus drop the failsafe tick? — CLEAR: no. Deliver it, with the focus task as its "active task".

This is the one default I reverse. The failsafe prompt (`handlers/post_tool_use/recovery_cron_advisor.py:187-203`)
says: resume the active plan/task if an *external* factor (API error, rate limit, usage limit) interrupted it; if
blocked only on human input, do nothing; if proceeding normally, no-op. In a focused session the active task is the
focus task, so the tick's purpose (recover from a silent death) applies in full; its only "distraction" is the phrase
"active plan/task", which the daemon controls. The design's own justification for dropping it ("a rate-limited
focused session recovers when the human next types") is a description of the silent death the net exists to catch.
Cost of keeping it: at most one model turn an hour, and the existing backoff (`failsafe_cron_blockage_suppressor.py: 359-366`, 2 h then 4 h when nothing is owed) still thins it.

Ruling: under focus, declared `persistent_crons` ticks are dropped (they are the real pull toward other work:
issue-sdlc etc.), the watchdog is delivered (as today, `:400-412`), and the failsafe tick is delivered with one line
prepended by the suppressor: "focus mode: the active task is <task>; other plans are out of scope". The goal-ledger
challenge is still replaced by the focus reminder (Task 3.2).

Plan change: PLAN.md Goals line "Delivered cron ticks are dropped" becomes "declared ticks are dropped; the failsafe
tick is delivered naming the focus task"; the design report's matrix row "Failsafe tick / focus" flips to ✓ (with
rewrite); Task 3.2 and the Success Criteria line "receives no cron tick" change accordingly; acceptance 7.2 tests a
delivered, rewritten failsafe tick and a dropped declared tick.

## Q5. Should `unattended` become per session? — CLEAR: not in this plan; show it on the badge.

The interceptor is wired at the controller, daemon-wide, before any chain (`core/mode_interceptor.py:38-81`,
`controller.py:1050-1097`), and its only state is `ModeManager`. Making it per session is a separate change with its
own IPC and skill surface, and nothing in #91 or #106 needs it. Showing it on the new segment removes the real gap
(F8: it is invisible today). Task 2.3 (interceptor stands down while BLOCKED or usage-paused) is unaffected: the
interceptor is a work driver, not a guard, so a mode may gate it.

## Q6. Does entering focus clear an existing goal? — CLEAR: yes, once, and stated loudly.

A live multi-plan `/goal` is the strongest pull away from the focus task. But the clear is delivered by the supervisor
typing `/goal clear`, and the supervisor types only when `can_inject` holds (`claude-supervise.py:7253`: idle, empty
input box, main focus confirmed; `:7742-7748` logs "goal clear pending but session busy"). The focus-on prompt starts
a turn, so the clear lands at the next idle, and with no supervisor it never lands. Neither case may be silent.

Ruling: on focus entry the daemon calls `clear_goal_signal` once AND, while focus is on, `goal_injection` writes no
`.goal-intent` for the session (the same non-re-arm rule as BLOCKED; otherwise a plan flip during focus re-arms the
goal). The one-time focus context line states: "a `/goal` for plans X is set; the supervisor will clear it at the next
idle; without a supervisor it stays until a human types `/goal clear`". A human who wants the goal kept can re-type it.

Plan change: Task 3.2 gains the no-goal-intent rule and the context-line wording; Task 7.2 acceptance checks a
focus-on with a live goal.

## Q7. Under BLOCKED, suppress the supervisor's post-compact `continue`? — CLEAR: yes.

The supervisor's only post-compaction injection is `continue`, decided once per compaction episode
(`claude-supervise.py:6282-6315`, `_CONTINUE_BODY` at `:6609`); it exists to resume a session that was mid-work when
context ran red. A BLOCKED session is by definition not mid-work: typing `continue` into it starts a turn whose only
possible outcome is another "still blocked" stop, which is one more re-arm. Suppress it regardless of who triggered the
compaction (a human `/compact` is a slash command and may not fire UserPromptSubmit, so it does not reliably exit
BLOCKED; the human can type what they want next). `/compact` itself still runs: context hygiene is not work-driving.

Plan change: Task 5.1's `decide_once` gate covers `WOULD_CONTINUE` as well as the goal, session-actions and
standing-auth families; the supervisor logs the suppression as a named noop reason (never silent).

## Q8. Goal-loop rollout and thresholds — CLEAR, with one change to the firing conditions.

Drop pairwise stop-text similarity as a FIRING condition; keep it as logged evidence. The #91 field report (treated
as untrusted, but its mechanism is plausible on its face: the `/goal` evaluator is a model that gives a new reason
each time, and the agent rewords each stop to answer it) says no two of nine consecutive rejected stops were alike.
Independently of that report, similarity adds a way to miss a loop and adds no protection that "no repository change"
does not already give: a session that is producing nothing changes nothing. The two conditions that held throughout
were consecutive `goal_status met:false` cycles with no genuine human prompt between, and no tracked change and no
commit. Fire on those.

Thresholds: 3 cycles, 2 if every stop in the run declared `[awaiting-human]` or matched `_HUMAN_BLOCKED_PATTERNS`
(`auto_continue_stop.py:183-236`); 30-minute window (the field case was 9 in about 15 minutes); 4-hour timer.
Observe first, because `act` has no proven lever yet: the supervisor cannot type `/goal clear` into a busy session
(Q6 evidence) and the `continue:false` halt is unverified (Q9), so an `act` default today would set a mode and
suppress re-injection while the Claude Code slot stays armed. Flip to `act` when the log shows three true positives
and no false positive, or after two releases, whichever first; "one release" alone is a calendar, not evidence.

Performance: the repo fingerprint runs only when the current Stop carries a `met:false` record, uses `git status --porcelain -uno` (no untracked walk) plus HEAD, excludes `*/JOURNAL/*` and `untracked/`; the transcript is read from
the last checkpoint, never whole. Observe mode logs to `untracked/session-modes.jsonl` with the fields in design §3.4.

Note the 8-consecutive-continuation cap (`remote-docs/code.claude.com/docs/en/hooks.md:2765`) does not end this
loop: it resets on every tool call, and a "still blocked" turn calls tools.

Plan change: Task 6.2 drops similarity from the fire rule (keeps it in the log record); Task 7.3 states the flip
criterion above; Task 6.1's fixtures must include a reworded-stops run.

## Q9. Use a Stop `continue:false` halt if the spike shows it works? — CLEAR: yes, and the spike is load-bearing.

Today `halt_turn` is honoured only by the PreToolUse formatter (`core/hook_result.py:270-275`, emitted at
`:708-713`); the Stop formatter (`:743-794`) has no such path. The docs say the top-level `continue: false` "takes
precedence over any event-specific decision fields" (`hooks.md:1087`) and that `/goal` is itself "a session-scoped
prompt-based Stop hook" (`hooks.md:2758`); whether one Stop hook's `continue:false` beats another Stop hook's block
is undocumented, hence spike 0.3. The field report's second comment shows why this matters: a `.goal-clear` trigger
written during the loop sat unconsumed because the supervisor never saw an idle session. That is not a supervisor
bug (`:7253`, `:7742-7748` are deliberate: never type into a busy TUI); it means the daemon's own Stop response is the
only lever that can act between the evaluator's rejection and the next turn.

Ruling: once per BLOCKED entry, logged with the evidence, never repeated. If the spike shows `continue:false` does
not end the turn, spike 0.3 must also test the alternative (the supervisor queuing `/goal clear` into a busy session
with its existing Enter/ESC machinery, `:7600-7650`), and Task 6.3 documents that without either lever the only
backstop is `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, which (Q8 note) the loop does not reach.

Plan change: Task 0.3 gains the busy-session typing test; Task 6.3 is written against whichever lever the spike
proves; the acceptance in 7.2 ("a live goal loop caught in act mode") requires the proven lever.

## Q11. Manual goals (#106) — three sub-questions

**11.1 Exit — CLEAR: an explicit switch-back (`hooks-daemon goals on` prompt, `/mode goals auto`, or the CLI) or a
new session. A human-typed `/goal <condition>` does NOT exit it.** The mode's name is its meaning: the human is
setting goals by hand, and a hand-set goal is the mode working, not a reason to end it. No TTL: #106 says "until it is
switched back", and unlike focus it is a stated preference, not a task that goes stale. The mode is stated once on
entry ("automated goals off for this session; `hooks-daemon goals on` restores them") so the switch-off is visible.

**11.2 Post-compaction `continue` — CLEAR: no.** `continue` resumes a session, it does not set a goal
(`claude-supervise.py:6282-6315`); the fact-checks already corrected the issue's premise that a goal is re-injected
after compaction. Suppressing `continue` is BLOCKED's job (Q7). `manual-goals` suppresses exactly one thing: the daemon
writing `.goal-intent` for the session.

**11.3 First mod section — CLEAR: a read-only display of the active modes first; session-scoped config overrides
later.** The owner's own words in #106 are "break the ice" with a minimal mod. A read-only pane needs only the
per-session file this plan writes; overrides need a write path into the daemon's config layer, which is Plan 00497's
design question, not this plan's. Plan 00497 Task 3.5 should be scoped to the display.

**Attribution rule, applied to the no-silent-fallbacks ruling.** MANUAL-GOALS.md says an unreadable supervisor record
"counts as the supervisor's, so no mode changes". Keep the direction (a wrongly attributed human clear is repeatable;
a wrongly attributed supervisor clear would switch automation off), but it must be loud: log at WARNING and emit one
context line ("a `/goal clear` was seen but its attribution record was unreadable; treated as the supervisor's; repeat
it if it was yours"). Task 8.2 gains that line. Task 8.1 (does UserPromptSubmit fire for `/goal clear`?) stays a
spike; the vendored docs (`hooks.md:68-69`, `:1534`) do not settle it. If it does not fire, detection moves to the
next Stop's transcript read, which Q8's detector already performs.

## Cross-cutting notes for the executor

- Guards: nothing above gates a guard. `UnattendedModeInterceptor` and the goal machinery are drivers; `release_blocker`,
  QA gates and the `STOPPING BECAUSE:` rule run identically in every mode.
- Fail loud: every mode transition (enter, exit, expiry, restart survival, suppressed `continue`, unreadable file or
  record) is logged and, where an agent is affected, stated once as a context line. "Observe" mode is not a silent
  fallback: it records every near miss.
- Performance: the registry is in-memory with write-through; the status line reads it in-process; the suppressor's
  per-tick work is unchanged; the detector's git call is conditional and untracked-free; focus renewal reads no file.
- The existing `[awaiting-human]` write side (`auto_continue_stop.py:987-1029`) and the fail-open `blockage_marker.py`
  contract stay as they are for Phase 2; the per-session storage is the registry's, not a second marker.
