# Plan 00501: session modes

**Status**: Not Started
**Created**: 2026-10-08
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #91
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's work-driving machinery is right for a long-running worker session, but wrong for a session that is
pointed at ONE task, is genuinely blocked, or is paused on a usage ceiling. Today these conditions are scattered:
the `[awaiting-human]` marker, usage pause, the daemon-wide `unattended` mode and Plan 00498's per-environment
`autonomy:` verdict each hold their own state, with different scopes and no common display.

This plan (owner approved the concept) makes a **session mode** a first-class, per-session concept: a named
condition with a suppression set, an entry source, exit conditions, a lifetime and a status-line label. Modes
compose (suppressions union; a mode that halts work beats one that drives it). Guards are never part of any mode.

The modes: `focus` (user intent), `BLOCKED` (reason `declared` = awaiting-human, or `goal-loop` = goal-blocked,
detected), `usage-paused` (existing state, shown not migrated) and daemon `unattended` (shown on the badge). The
plain unattended worker is the absence of a mode and shows nothing.

Depth, the state inventory, the suppression matrix, precedence and code citations live in
[subagent-reports/261008-session-modes-design-opus.md](subagent-reports/261008-session-modes-design-opus.md); this
plan does not repeat them. The earlier code fact-check is in `subagent-reports/261008-plan-fact-checker-sonnet.md`.

## Goals

### Focus mode (the original scope of this plan)

- A prompt `hooks-daemon focus <message>` turns focus on for that session only; `hooks-daemon focus off` (aliases
  `done`, `end`, `disable`) turns it off. Recognition is anchored to the start of the prompt, case-insensitive and
  tolerant of speech-to-text spellings (`hooks daemon`, `hooks demon`). The prompt still reaches the model with the
  message attached as the stated task.
- While focused, every `drives_autonomy` handler is skipped for that session through the same
  `autonomy_verdict` Plan 00498 built (both the central chain gate and the direct `autonomy_allowed` callers see
  it), and the goal-ledger stop challenge is replaced by a one-line focus reminder.
- Delivered cron ticks are dropped before the model; the ccy supervisor injects no goals or prompts.
- Focus is stated back to the agent once when set and when cleared.

### BLOCKED: awaiting-human and goal-blocked (closes ledger N378)

- One `BLOCKED` family with reasons `declared` and `goal-loop`, sharing one suppression set and the human-prompt and
  expiry exits, shown under different labels.
- **Per-session storage** replaces the single project-wide awaiting-human marker. Only a genuine human prompt in
  the SAME session clears it (a prompt in another session, or a line typed by the supervisor, does not). A legacy
  marker is imported once on upgrade. Closes N378 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`.
- **Detection (goal-blocked).** A new Stop handler, separate from `auto_continue_stop` and running on Stop-hook
  re-entry, reads the transcript's structured goal-evaluation records. A cycle is a `STOPPING BECAUSE:` stop followed
  by an unmet goal evaluation with no genuine human prompt between. It fires on consecutive cycles within a window,
  near-identical stop text and no repository change (journal files and untracked scratch excluded from the
  fingerprint).
- **Loop break.** Reuse the existing goal-clear signal so the supervisor types the goal-clearing command; a spike
  decides whether a Stop `continue:false` can also end the turn.
- **No re-arm.** While BLOCKED, goal injection writes no goal signal, the goal-ledger challenge is suppressed, the
  supervisor skips goal and session-action prompts, and declared and failsafe ticks are dropped. Nothing sets a goal
  again on exit; the next plan status flip does that normally.
- **Unblock conditions.** A genuine human prompt in the session, a repository change a blocked input could have
  produced, a capped timer, or an explicit clear.
- **Log-only first.** The detector ships in `observe` mode, recording every transition and near miss (counts,
  window, similarities, repo fingerprints, thresholds, exit cause) so a false positive is visible and thresholds
  can be tuned before `act` becomes the default.

### Usage-paused and display

- `usage-paused` is read as a mode; its storage is not migrated. The unattended stop-block interceptor stands down
  while a session is BLOCKED or usage-paused.
- A new status-line segment shows the top mode by precedence (`usage-paused > goal-blocked > awaiting-human > focus > unattended`) plus a `+N` count, with an entry in `status-line-explained`. The daemon `unattended` mode
  is finally visible there.
- The supervisor reads modes from a per-session file the daemon owns (the established channel pattern), not a
  socket.

## Non-Goals

- Guards: safety and blocking handlers (including `release_blocker`) are never gated by any mode.
- Making daemon `unattended` per session, or renaming the `/mode` skill (its existing verbs and IPC stay).
- Replacing `autonomy:`: it stays the persistent per-environment switch and feeds the same verdict.
- Migrating usage-pause, cron-pause or goal-signal storage.

## Open questions for the owner (recommended default in each; change them on the issue)

01. **Does a daemon restart clear focus?** Default: no. Focus is session-lifetime: cleared by `off`, a new session
    or the TTL below; the only record is a per-session runtime file. Restarts follow most merges, so clearing on
    restart would silently drop focus mid-task. If the owner keeps "restart clears", it is a one-line lifetime change
    and the restart notice becomes mandatory.
02. **Focus TTL?** Default: 12 hours, renewed by each genuine human prompt in the session.
03. **Merge goal-blocked into awaiting-human?** Default: yes, one `BLOCKED` family with two reasons and two badges.
04. **Does focus drop the failsafe tick?** Default: yes (its prompt is the distraction).
05. **Should `unattended` become per session?** Default: not in this plan; show it on the badge.
06. **Does entering focus also clear an existing goal?** Default: yes, once.
07. **Under BLOCKED, suppress the supervisor's post-compact `continue`?** Default: yes; `/compact` still runs.
08. **Goal-loop rollout.** Default: `observe` for one release; thresholds 3 cycles (2 if every stop declared
    awaiting-human), 30 minute window, similarity 0.75, repo unchanged excluding journal files, 4 hour timer.
09. **Use a Stop `continue:false` halt if the spike shows it works?** Default: yes, once per entry, logged.
10. **Rename the plan to "session modes"?** Approved by the owner; done.

## Tasks

### Phase 0: Spikes and evidence (no production code)

- [ ] ⬜ **Task 0.1**: Fold the design report's findings into the journal; correct the fact-check's open items.
- [ ] ⬜ **Task 0.2**: Spike: capture real Stop payloads and record order during a goal re-arm (including
  `stop_hook_active`) from existing transcripts and stop events.
- [ ] ⬜ **Task 0.3**: Spike: does a Stop `continue:false` end a turn while a goal is active; is a goal clear typed
  mid-turn queued or rejected?

### Phase 1: The model (pure, no behaviour change)

- [ ] ⬜ **Task 1.1**: TDD `utils/session_modes.py`: mode enum, frozen entries, policy union and precedence, tick-drop
  truth table.
- [ ] ⬜ **Task 1.2**: TDD the thread-safe registry with write-through per-session file: lifetime classes on load,
  TTL, reaping, restart note.
- [ ] ⬜ **Task 1.3**: TDD `autonomy_verdict`/`autonomy_allowed` honouring session modes with `explain()` wording;
  cover the chain route and each direct-call route.

### Phase 2: Awaiting-human folds in, with the bug fixes (shippable alone)

- [ ] ⬜ **Task 2.1**: TDD the suppressor clearing only on a genuine human prompt in the same session; regression
  tests for cross-session prompts and supervisor-typed lines.
- [ ] ⬜ **Task 2.2**: TDD `auto_continue_stop` writing the registry, one-time legacy marker import, suppressor
  reading the policy.
- [ ] ⬜ **Task 2.3**: TDD the unattended stop-block interceptor standing down while BLOCKED or usage-paused.

### Phase 3: Focus

- [ ] ⬜ **Task 3.1**: TDD the UserPromptSubmit trigger (spellings, `off` aliases, start-anchored, one context line).
- [ ] ⬜ **Task 3.2**: TDD focus tick-drop through the suppressor and the focus reminder replacing the goal-ledger
  challenge.
- [ ] ⬜ **Task 3.3**: TDD the `/mode focus` verbs, a session-mode CLI and the IPC actions.

### Phase 4: Visibility

- [ ] ⬜ **Task 4.1**: TDD the status-line segment and its explanation entry.
- [ ] ⬜ **Task 4.2**: Restart notice (only if question 1 keeps "restart clears").
- [ ] ⬜ **Task 4.3**: Transition log and a CLI printing active modes and recent transitions with evidence.

### Phase 5: Supervisor

- [ ] ⬜ **Task 5.1**: TDD the supervisor reader for the session-modes file (field-pin test) and the gate skipping
  goal, session-action and standing-auth prompts.
- [ ] ⬜ **Task 5.2**: TDD goal-clear outranking goal-intent under BLOCKED, per spike 0.3; run the supervisor
  hot-reload check from `.claude/rules/ccy-supervisor-dogfooding.md`.

### Phase 6: Goal-loop detector

- [ ] ⬜ **Task 6.1**: TDD transcript extraction from scrubbed fixture records.
- [ ] ⬜ **Task 6.2**: TDD the cycle ring, similarity, repo fingerprint, thresholds, `observe` mode, near-miss logging.
- [ ] ⬜ **Task 6.3**: TDD `act` mode: enter BLOCKED(goal-loop), clear the goal signal, one-time context line,
  optional halt per spike 0.3.
- [ ] ⬜ **Task 6.4**: TDD exits: human prompt, repo change, timer, explicit clear.

### Phase 7: Docs and acceptance

- [ ] ⬜ **Task 7.1**: Handler guidance, a "Session modes" section in the autonomy docs, release note in the
  UNRELEASED holding area.
- [ ] ⬜ **Task 7.2**: Acceptance: focus on, tick dropped, focus off; awaiting-human in one session not cleared by
  another; a live goal loop caught in observe mode, then act mode.
- [ ] ⬜ **Task 7.3**: After a release in `observe`, tune thresholds from the log and flip the default in a
  follow-up.

## Success Criteria

- [ ] A focused session receives no cron tick, no goal-ledger plan list and no work-driving advisory or supervisor
  prompt; `focus off`, a new session or the TTL restores normal behaviour.
- [ ] An awaiting-human declaration in one session is not cleared by a prompt in another or by a supervisor line
  (ledger N378 closed).
- [ ] A goal tight loop is detected, logged with its evidence, broken and not re-armed; every unblock condition
  exits the mode.
- [ ] The status line shows the active mode(s) and `status-line-explained` documents them.
- [ ] Guards behave identically in every mode; no config change is needed.
- [ ] Full QA gate passes.

## Delivery & Milestones

- Plan filed; GitHub issue #91 opened from the owner's request.
- Owner approved the session modes concept and the rename; this revision folds in the design report.
