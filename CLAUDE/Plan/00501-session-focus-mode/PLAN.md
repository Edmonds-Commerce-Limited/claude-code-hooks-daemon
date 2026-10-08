# Plan 00501: session focus mode

**Status**: Not Started
**Created**: 2026-10-08
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #91
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's work-driving machinery is right for a long-running worker session, but in a session the owner has
pointed at ONE task it pulls the agent off it: declared crons (issue-sdlc, failsafe, watchdog) fire into the
session, the goal ledger challenges every stop on behalf of every open plan, goal injection and session-start
directives push general work, and the ccy supervisor types its own prompts.

Plan 00498 already switches all of that off, but per ENVIRONMENT and from config (`autonomy:`). Focus mode is the
per-SESSION, runtime, user-driven switch: the owner types `hooks-daemon focus <what I am working on>` as a prompt,
and until they type `hooks-daemon focus off` (or the session or the daemon restarts) that session gets no
work-driving pressure. No config edit, nothing persisted.

The design reuses 00498's single verdict rather than building a second mechanism. Work-driving handlers reach
`utils/autonomy.autonomy_verdict` by two routes: those marked `drives_autonomy` are gated centrally in
`core/chain.py`, and two that are not flagged (`auto_continue_stop`'s stand-in and goal-ledger paths,
`background_process_tracker`) call `autonomy_allowed(hook_input)` themselves. Focus mode adds one more input to
the verdict itself, "this session is focused", so both routes see it. Today the verdict is keyed by environment
and hostname only; keying it by the hook input's `session_id` is new (see the fact-check in `subagent-reports/`).

## Goals

- A prompt `hooks-daemon focus <message>` turns focus mode on for that session only; `hooks-daemon focus off`
  (aliases: `done`, `end`, `disable`) turns it off. Recognition is case-insensitive and tolerant of speech-to-text
  spellings (`hooks daemon`, `hooks demon`).
- While focused, every `drives_autonomy` handler is skipped for that session, exactly as an `autonomy:`-disallowed
  environment is, and the goal-ledger stop challenge names only the focus task, not every ledgered plan.
- Delivered cron ticks (`[tick:...]` prompts) are dropped at UserPromptSubmit before reaching the model, as
  `failsafe_cron_blockage_suppressor` already does for an `[awaiting-human]` session (that handler stays ungated
  and marker-keyed; focus gets its own drop, sharing only the tick recognition).
- The ccy supervisor does not inject goals or prompts into a focused session.
- Focus state is visible (status line) and stated back to the agent once when set and when cleared.
- State lives in daemon memory only: a daemon restart or a new session clears it.

## Non-Goals

- Guards: safety and blocking handlers are never gated, focused or not (as in 00498).
- A config key or persistent state. The `autonomy:` block stays the persistent, per-environment switch.
- Release-in-progress blocking: `release_blocker` is a guard on a part-done release and stays on.

## Open questions for the owner (defaults chosen; change them on the issue)

1. **Daemon restarts clear focus.** That was the stated wish, but in this repo the daemon is restarted after
   most merges, so focus would silently drop mid-task. Default: clear on restart as asked, AND say so loudly (the
   status-line badge disappears; the first prompt after a restart in a session that WAS focused gets a one-line
   "focus mode was cleared by a daemon restart" notice, via a tiny session-id marker under `untracked/` that
   records only "was focused", never re-enables it).
2. **Should the stop hook's `STOPPING BECAUSE:` rule still apply?** Default: yes. It is a reporting rule, not a
   distraction; only the goal-ledger plan list is suppressed.
3. **Does the trigger prompt also go to the model?** Default: yes, with the focus message attached as the
   session's stated task, so `hooks-daemon focus fix the flaky test` both sets focus and starts the work.

## Tasks

### Phase 1: Session focus state and the gate

- [ ] ⬜ **Task 1.1**: Read Plan 00498 (`Completed/00498-autonomy-only-where-allowed/`) and its handler inventory;
  list every distraction source and the route by which it reaches `autonomy_verdict` (the chain gate, or a
  direct `autonomy_allowed` call as in `auto_continue_stop` and `background_process_tracker`); anything reaching
  neither needs its own focus check.
- [ ] ⬜ **Task 1.2**: TDD an in-memory, thread-safe `FocusRegistry` (session_id -> focus message), cleared on
  daemon start.
- [ ] ⬜ **Task 1.3**: TDD `autonomy_verdict`/`autonomy_allowed` returning "not allowed: session focused" when the
  hook input's session is focused; the `explain()` text names focus mode.

### Phase 2: User trigger

- [ ] ⬜ **Task 2.1**: TDD a UserPromptSubmit handler recognising `hooks-daemon focus <message>` /
  `hooks-daemon focus off` (spellings above), updating the registry and adding one line of context.
- [ ] ⬜ **Task 2.2**: TDD tick dropping: a delivered `[tick:...]` prompt in a focused session is blocked before
  the model, in a new focus-keyed handler (or a focus branch of the suppressor) reusing `classify_tick`; the
  suppressor itself must stay ungated or it stops dropping ticks.
- [ ] ⬜ **Task 2.3**: TDD the goal-ledger stop challenge naming only the focus task while focused.

### Phase 3: Supervisor and visibility

- [ ] ⬜ **Task 3.1**: Find every ccy-supervisor prompt/goal injection and give it a way to ask the daemon
  whether the session is focused (socket query; no file the daemon does not own).
- [ ] ⬜ **Task 3.2**: Status-line focus badge; the restart notice from open question 1.
- [ ] ⬜ **Task 3.3**: Docs: the handler's `get_claude_md()` guidance, the `autonomy:` docs gain a "per-session:
  focus mode" section, and a release-note callout in the UNRELEASED holding area.

### Phase 4: Acceptance

- [ ] ⬜ **Task 4.1**: Acceptance tests in the handler(s), then a real session: set focus, let a cron tick fire,
  stop, clear focus, confirm behaviour returns.

## Success Criteria

- [ ] In a focused session no cron tick reaches the model, no goal-ledger plan list appears in a stop challenge,
  and no work-driving advisory or supervisor prompt is injected.
- [ ] `hooks-daemon focus off`, a new session, or a daemon restart restores normal behaviour.
- [ ] No config change is needed; guards behave identically when focused.
- [ ] Full QA gate passes.

## Delivery & Milestones

- Plan filed; GitHub issue #91 opened from the owner's request.
