# Phase 7/8 feasibility advice (Tasks 7.2, 7.3, 8.1)

Plan 00501. Advice only; nothing edited. Evidence read: PLAN.md, `CLAUDE/core/SessionModes.core.md`,
`SPIKE-0.3-continue-false.md`, `utils/session_modes.py` (tick truth table), `core/session_mode_registry.py`,
`handlers/stop/goal_loop_detector.py`, `.claude/ccy/claude-supervise.py` (read only), the two main transcripts
under `~/.claude/projects/-workspace/`, `untracked/supervise/decision.log`, `untracked/logs/hooks/verdicts.jsonl`,
`untracked/context-sidecar/*.session-modes`, the vendored `remote-docs/code.claude.com/docs/en/hooks.md` and
`changelog.md`.

State at 2026-10-23 01:24 UTC: session `c61663f0…` is BLOCKED(declared), entered 2026-10-22 19:46 UTC, cap expiry
2026-10-23 19:46 UTC; `mode-history` shows no transitions recorded; `payload_capture` is OFF; the supervisor host
(pid 2) started 2026-10-22 14:51 UTC, before Phase 5 landed (bc99fb917, 21:50 UTC), so only its hot-reloaded
`--worker` runs the session-modes gate.

## 1. Task 7.2: what this session can honestly run now

Hard constraints that decide it:

- No live goal is possible here. A goal is only ever set by the supervisor typing `/goal` from a `.goal-intent`
  the daemon writes on a plan status flip, and goal injection is withheld under BLOCKED (suppression table). The
  agent cannot type a slash command itself.
- Focus CAN be entered from a Bash call (`bin/hooks-daemon session-mode focus <task>`; `SessionModeRegistry.enter`
  does not refuse while BLOCKED), but it is pointless for the tick evidence: `SessionPolicy.tick_action` takes the
  most suppressive action across modes, so with BLOCKED live a declared tick is dropped either way and the
  failsafe tick is dropped (or thinned) instead of delivered with the focus line. Nothing focus-specific is
  observable while BLOCKED.
- Nothing may end the block: a genuine human prompt in this session, or the 24-hour cap, are the only exits.

### Run now (collect evidence, do not call it the acceptance)

1. **Awaiting-human suppression, this session.** Evidence: `verdicts.jsonl` lines at :47 each hour from
   `failsafe-cron-blockage-suppressor` showing the failsafe tick dropped, and `issue-sdlc` ticks at :23 delivered
   (`runs_while_awaiting_human: true`). Read with `grep` on the file; no new tooling.
2. **Supervisor BLOCKED gate (Task 5.1 live check), this session.** The supervisor injected `/compact` at
   01:11:56 and is "awaiting idle to resume". The acceptance line is the NEXT idle decision: expect
   `noop: post-compact continue skipped: session BLOCKED (awaiting-human)` in `decision.log`. Today
   `decision.log` holds zero `session BLOCKED` lines, so this is still open. Watch for the failure shape too: a
   `would-continue: … injected 'continue'` after 19:46 UTC on 10-22 is a defect. Specific risk to name in the
   journal: at 01:02 and 01:14 the host logged "worker did not answer -> host deciding in-process"; the host's
   in-memory code predates Phase 5 (started 14:51), so a decision made during a fallback window has no gate. I
   am not certain the fallback path reaches the same decide function, but the log wording says the host decides
   "throughout"; treat a `would-continue` in a fallback window as a known gap, not a Phase 5 bug.
3. **Per-session storage is real.** `untracked/context-sidecar/c61663f0….session-modes` holds the declared entry
   (version 1, source agent, lifetime session). The supervisor's reader opens only files named for its own
   sessions, so a second session's file is never consulted. This is code-level, not behavioural, evidence for
   "not cleared by another session"; it does not replace the live test.
4. **Optional smoke, not acceptance:** `session-mode focus <task>` then `focus off` from this session would show
   the entry/exit lines, the `⚑` segment, two transition-log records and a two-entry sidecar file the supervisor
   parses without error. Harmless (no goal exists to clear; BLOCKED still leads), but it proves no acceptance
   criterion and spends a prompt. I would skip it.

### Owner-gated (needs a human-driven session)

- Focus on with a live goal, the dropped declared tick, the rewritten failsafe tick, focus off: a session that is
  NOT BLOCKED, where the supervisor has typed a goal. Evidence: the `focus mode: the active task is …` line on
  the failsafe prompt in the transcript, a `R-DECLARED-CRON-SUPPRESSED` verdict at :23, the one-time goal-clear
  context line and the supervisor's `/goal clear` in `decision.log`, `mode-history` ENTER/EXIT records.
- Awaiting-human in one session not cleared by another: two sessions on the same daemon, one declaring, a human
  prompt typed in the other; evidence `session-mode get --session <id>` still BLOCKED and the suppressor's
  verdict on the next failsafe tick.
- Goal loop caught in observe, then act, with `/goal clear` landing during the nine-block stop loop: needs a live
  goal and a session that stops in a loop. `goal_loop_detector` is `observe` by default and `act` is a config
  flip (`mode: act`); the evidence is `near-miss`/`would-enter` then ENTER(goal-loop) in the transition log, the
  `would-goal-clear` line in `decision.log` timestamped INSIDE a run of `stop_hook_summary` records with
  `goal_status met:false`, and the `goal_status met:true sentinel:true` snapshot that follows (spike 0.3 saw
  this only in tool-calling turns).

### A second session started from here: no

A `claude -p` started by this coordinator is out, on two independent grounds:

- It has already been tried (spike 0.3, `untracked/scratch/spike501-03`): the child answers "Not logged in"
  because it cannot reach this session's credentials, and supplying them means handling secrets. The scratch
  transcript shows 19 lines and no hook event.
- Even if it ran, the supervisor discovers its own sessions by scanning `/proc/*/environ` for
  `CLAUDE_CODE_SESSION_ID` across the whole PID namespace, union-only, never forgotten (`cached_own_session_ids`).
  A second session in this container is adopted as the supervisor's own, so its `.goal-intent`, `.goal-clear` and
  `.session-modes` files would be acted on and typed into THIS coordinator's terminal. That does not edit
  `claude-supervise.py`, but it does change what the live supervisor does, which is the line the ruling draws.
  The supervisor's own comment names the fix: a separate runtime (`CLAUDE_HOOKS_SOCKET_PATH` etc.), which only
  helps if the session is also outside this PID namespace. So: a separate container or host, human-driven.

Timing note the coordinator should journal: the declared block caps out at 19:46 UTC today. That exit is the
daemon's, not the agent's, and does not breach the ruling; if the owner has still not decided, the next stop
re-declares. The window between cap expiry and the next declared stop is NOT a place to run the focus checks.

## 2. Task 8.1: answerable from disk, with one gap

**Verdict: `UserPromptSubmit` does NOT fire for a typed `/goal clear`.** Claude Code 2.1.273 to 2.1.308.

Evidence (transcripts under `~/.claude/projects/-workspace/`):

- Every idle `/goal clear` is a pair of `system`/`local_command` records only (`<command-args>clear`, then
  `<local-command-stdout>Goal cleared: …` or `No goal set`) with NO `type:user` record, NO
  `hook_additional_context` with `hookName: UserPromptSubmit`, and no turn: the next record is the next queued
  prompt or tick minutes later. Four in `c61663f0…` (lines 47459, 83444, 84283, 85355: 2026-10-11 15:02:59,
  2026-10-14 07:30:44, 10:40:07, 15:44:44) and five in `e5e72775…` (lines 5672, 7403, 8522, 17256, 55538, from
  2026-09-16).
- The control: every `/goal <condition>` set (44 in `e5e72775…`, 23 in `c61663f0…`) is a `type:user` record
  (`<command-name>/goal</command-name>` with the condition) followed by "A session-scoped Stop hook is now
  active" and then the daemon's UserPromptSubmit git-status `hook_additional_context` (for example
  `c61663f0…` lines 909 to 912, 2026-10-06 13:17). So the daemon's UserPromptSubmit hook demonstrably runs for
  a `/goal` SET and leaves no trace after a CLEAR.
- The mechanism matches the docs: `hooks.md:1497` "Runs when a prompt is submitted"; a set starts a turn (the
  "Stop hook is now active" prompt), a clear starts none. A mid-turn clear is even quieter: only the
  `goal_status met:true sentinel:true` attachment (spike 0.3 section 2).

Gaps, stated plainly:

- The aliases (`stop`, `off`, `reset`, `none`, `cancel`) have never been typed here; the supervisor types the
  literal `/goal clear`. By mechanism they behave the same (same local command, no turn), but that is inference.
- There is no daemon-side record: `verdicts.jsonl` begins 2026-10-22 and no clear has happened since;
  `payload_capture` is off and `untracked/payload-capture/` is empty.
- Changelog line 313 says `UserPromptSubmit` now runs before a skill or CUSTOM slash command expands; nothing
  says built-ins changed. Re-check on the next Claude Code upgrade.

Consequence for Task 8.2, as the task already anticipates: detection moves to the next Stop's transcript read
(the `local_command` pair, or for a mid-turn clear only the sentinel snapshot). A five-minute confirmation in the
owner's human-driven session (payload capture on for `UserPromptSubmit`, type `/goal stop`) would close the alias
gap; it is not needed to start 8.2.

## 3. Task 7.3: waiting, not worked

Confirmed. The detector merged 2026-10-23 00:27 (7d10af548); the transition log holds no `near-miss` or
`would-enter` record (`mode-history`: "no transitions recorded"); no release has shipped since. Neither gate
(three true positives, two releases) has started counting. Record it as waiting and journal the counter's start:
the first release that carries the detector is release one of two. Do not tune thresholds from zero records.
