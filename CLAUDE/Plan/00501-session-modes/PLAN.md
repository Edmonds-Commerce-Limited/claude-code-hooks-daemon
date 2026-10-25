# Plan 00501: session modes

**Status**: Blocked on the owner (Task 7.2 needs an owner-driven live acceptance session; Task 7.3 needs a human-gated release or a third organic true positive)
**Created**: 2026-10-08
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #91; #106 (manual goals, Phase 8)
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
- Declared `persistent_crons` ticks are dropped before the model; the watchdog is delivered; the failsafe tick is
  delivered with a prepended line naming the focus task (Q4). The ccy supervisor types no goal and no
  session-actions directive while focused, because the daemon writes neither signal (goal cleared once on entry,
  `.goal-intent` and `.session-actions` not written); the supervisor itself reads no focus state. The post-compact
  `continue` and the standing-authorisation reminder are unaffected: focus is a working mode, not a halt.
- Focus is stated back to the agent once when set, when cleared, when it expires (TTL 12 hours, renewed by each
  genuine human prompt, classified from the prompt text with no file read) and when it survives a daemon restart
  (Q1, Q2). An unreadable session-modes file is logged at WARNING and renamed `*.corrupt`, never read as "no modes".
- Entering focus clears an existing goal once and, while focused, `goal_injection` writes no `.goal-intent`; the
  one-time context line says the supervisor clears it at the next idle, or a human must type `/goal clear` (Q6).

### BLOCKED: awaiting-human and goal-blocked (closes ledger N378)

- One `BLOCKED` family with reasons `declared` and `goal-loop`, sharing one suppression set and the human-prompt and
  expiry exits, shown under different labels.
- **Per-session storage** replaces the single project-wide awaiting-human marker. Only a genuine human prompt in
  the SAME session clears it (a prompt in another session, or a line typed by the supervisor, does not). A legacy
  marker is imported once on upgrade. Closes N378 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`.
- **Detection (goal-blocked).** A new Stop handler, separate from `auto_continue_stop` and running on Stop-hook
  re-entry, reads the transcript's structured goal-evaluation records. A cycle is a `STOPPING BECAUSE:` stop followed
  by an unmet goal evaluation with no genuine human prompt between. It fires on consecutive cycles within a window,
  no repository change (journal files and untracked scratch excluded from the fingerprint). Stop-text similarity is
  logged as evidence only, not a firing condition (Q8).
- **Loop break.** Reuse the existing goal-clear signal so the supervisor types `/goal clear`; spike 0.3 showed a
  `/goal clear` typed mid-turn takes effect at once. A Stop `continue:false` halt (Q9) stays out until a live test
  proves it beats the goal evaluator and disarms the goal (spike 0.3: unproven). Without ccy, the docs name Claude
  Code's own cap-and-pause as the only backstop.
- **No re-arm.** While BLOCKED, goal injection writes no goal signal, the goal-ledger challenge is suppressed, the
  supervisor skips goal, session-action and post-compact `continue` prompts (`/compact` still runs; the suppression
  is logged as a named noop reason), and declared and failsafe ticks are dropped. Nothing sets a goal
  again on exit; the next plan status flip does that normally.
- **Unblock conditions.** A genuine human prompt in the session, a repository change a blocked input could have
  produced, a capped timer, or an explicit clear.
- **Log-only first.** The detector ships in `observe` mode, recording every transition and near miss (counts,
  window, similarities, repo fingerprints, thresholds, exit cause) so a false positive is visible and thresholds
  can be tuned. `act` becomes the default after three true positives and no false positive, or after two releases,
  whichever is first. Thresholds: 3 cycles (2 if every stop declared awaiting-human), 30 minute window, 4 hour timer.
  The fingerprint runs only when the Stop carries a `met:false` record and the transcript is read from a checkpoint.

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

## Rulings (adviser, delegated by the owner)

All CLEAR; rationale and code citations in
[subagent-reports/261022-owner-questions-advice-fable.md](subagent-reports/261022-owner-questions-advice-fable.md).

01. **Restart clears focus?** No. Focus is session-lifetime; a surviving focus is re-stated once after a restart.
02. **Focus TTL?** 12 hours, renewed by each genuine human prompt (prompt-text classifier); expiry is stated once.
03. **Merge goal-blocked into awaiting-human?** Yes, one `BLOCKED` family with two reasons; a declared stop counts as
    2 cycles toward the detector.
04. **Focus drops the failsafe tick?** No (reversed). Declared ticks are dropped, the failsafe tick is delivered
    naming the focus task.
05. **`unattended` per session?** Not in this plan; shown on the badge.
06. **Focus clears an existing goal?** Yes, once and stated; no `.goal-intent` is written while focused.
07. **BLOCKED suppresses post-compact `continue`?** Yes; `/compact` still runs; logged as a named noop reason.
08. **Goal-loop rollout?** `observe` first; similarity dropped from the fire rule (kept as evidence); flip to `act`
    on three true positives and no false positive, or two releases.
09. **Stop `continue:false` halt?** Yes, once per entry, logged; spike 0.3 is load-bearing and also tests the
    busy-session typing alternative. Spike 0.3 left the halt unproven, so Task 6.3 uses the goal clear only.
10. **Rename to "session modes"?** Approved by the owner; done.
11. **Manual goals (#106)?** Exit by explicit switch-back or new session (a typed `/goal` does not exit; no TTL);
    does not suppress `continue`; first mod section is a read-only display. Detail in
    [MANUAL-GOALS.md](MANUAL-GOALS.md).

## Tasks

### Phase 0: Spikes and evidence (no production code)

- [x] ✅ **Task 0.1**: Fold the design report's findings into the journal; correct the fact-check's open items.
- [x] ✅ **Task 0.2**: Spike: capture real Stop payloads and record order during a goal re-arm (including
  `stop_hook_active`) from existing transcripts and stop events. Report: [SPIKE-0.2-stop-payloads.md](SPIKE-0.2-stop-payloads.md).
- [x] ✅ **Task 0.3**: Spike: does a Stop `continue:false` end a turn while a goal is active; is a goal clear typed
  mid-turn queued or rejected? Also test the busy-session typing alternative (the supervisor typing `/goal clear`;
  its gate is human-input idleness, not child output); the result decides the lever for Task 6.3. Report:
  [SPIKE-0.3-continue-false.md](SPIKE-0.3-continue-false.md). The halt question stays unproven (no live test was
  possible); the clear runs at once mid-turn.

### Phase 1: The model (pure, no behaviour change)

- [x] ✅ **Task 1.1**: TDD `utils/session_modes.py`: mode enum, frozen entries, policy union and precedence, tick-drop
  truth table.
- [x] ✅ **Task 1.2**: TDD the thread-safe registry with write-through per-session file: lifetime classes on load,
  TTL with prompt-text renewal (`is_genuine_text`, no file read), one-time expiry statement, reaping, restart note;
  a malformed file is logged at WARNING and renamed `*.corrupt`.
- [x] ✅ **Task 1.3**: TDD `autonomy_verdict`/`autonomy_allowed` honouring session modes with `explain()` wording;
  cover the chain route and each direct-call route.

### Phase 2: Awaiting-human folds in, with the bug fixes (shippable alone)

- [x] ✅ **Task 2.1**: TDD the suppressor clearing only on a genuine human prompt in the same session; regression
  tests for cross-session prompts and supervisor-typed lines.
- [x] ✅ **Task 2.2**: TDD `auto_continue_stop` writing the registry, one-time legacy marker import, suppressor
  reading the policy. Ruling 07 (post-compact `continue` under BLOCKED) is NOT part of this task: it is implemented
  in Task 5.1. Withholding the `.compacting` signal would stop the `continue`, but it would also leave the
  supervisor's wait after a `/compact` it typed to run to its timeout, and each timed-out wait counts towards the
  injection fuse, so the daemon does not use that lever. The only daemon-side part is writing BLOCKED to the
  session-modes file, which Task 2.2 does.
- [x] ✅ **Task 2.3**: TDD the unattended stop-block interceptor standing down while BLOCKED or usage-paused.

### Phase 3: Focus

- [x] ✅ **Task 3.1**: TDD the UserPromptSubmit trigger (spellings, `off` aliases, start-anchored, one context line),
  reusing the Task 1.2 prompt classifier.
- [x] ✅ **Task 3.2**: TDD focus tick-drop through the suppressor (declared ticks dropped, watchdog delivered,
  failsafe tick delivered with the prepended "focus mode: the active task is <task>; other plans are out of scope"
  line), the focus reminder replacing the goal-ledger challenge, the once-only goal clear on entry, no
  `.goal-intent` while focused, and the context-line wording about the supervisor clearing at next idle.
- [x] ✅ **Task 3.3**: TDD the `/mode focus` verbs, a session-mode CLI and the IPC actions.

### Phase 4: Visibility

- [x] ✅ **Task 4.1**: TDD the status-line segment and its explanation entry.
- [x] ✅ **Task 4.2**: Restart re-statement of surviving modes (one context line on the next prompt), unconditional.
- [x] ✅ **Task 4.3**: Transition log and a CLI printing active modes and recent transitions with evidence.

### Phase 5: Supervisor

- [x] ✅ **Task 5.1**: TDD the supervisor reader for the session-modes file (field-pin test) and the gate skipping
  goal, session-action and standing-auth prompts, plus the post-compact `continue` (`WOULD_CONTINUE`) under BLOCKED,
  logged as a named noop reason. An unreadable file closes the gate (documented in `CcySupervisor.md`).
- [x] ✅ **Task 5.2**: TDD goal-clear outranking goal-intent under BLOCKED, and a BLOCKED clear not refused by the
  5-per-process clear cap (spike 0.3: the cap has been hit); no busy-session rule is needed, the clear already types
  into a running turn. The live hot-reload check is the coordinator's after merge; its recipe is in
  `subagent-reports/261022-phase5-impl-opus.md`.

### Phase 6: Goal-loop detector

- [x] ✅ **Task 6.1**: TDD transcript extraction from scrubbed fixture records, including a reworded-stops run.
- [x] ✅ **Task 6.2**: TDD the cycle ring, repo fingerprint (conditional, `git status --porcelain -uno` plus HEAD),
  thresholds (a declared `[awaiting-human]` stop counts toward the 2-cycle threshold), `observe` mode, near-miss
  logging. Similarity is logged but not a fire condition.
- [x] ✅ **Task 6.3**: TDD `act` mode: enter BLOCKED(goal-loop), clear the goal signal (the lever spike 0.3
  supports: the supervisor's `/goal clear` lands mid-turn), one-time context line. No `continue:false` halt unless
  a later live test proves it. Document that without ccy the only backstop is Claude Code's built-in cap of 8
  consecutive stop-hook continuations (reset by each tool call, raised by `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), after
  which it pauses the goal until the next message, including a tick; a loop that makes tool calls between stops
  never reaches the cap.
- [x] ✅ **Task 6.4**: TDD exits: human prompt, repo change, timer, explicit clear.

### Phase 7: Docs and acceptance

- [x] ✅ **Task 7.1**: Handler guidance, a "Session modes" section in the autonomy docs (no autonomy doc exists yet;
  choose its home when this task starts), release note in the UNRELEASED holding area. Home chosen: the
  daemon-owned core document `CLAUDE/core/SessionModes.core.md` (deployed to every install, so the handler guidance
  that names `CLAUDE/SessionModes.md` resolves in a client); release notes 020-024 already cover the behaviour. The session-modes docs carry
  the Goals' focus sentence on what the supervisor does and does not type (adviser Q2,
  `subagent-reports/261022-phase5-merge-advice-fable.md`), and `status-line-explained` names the modes-file WARNING
  text so an operator knows the fix is to let the daemon load its registry / check the `.corrupt` file, not a
  restart (adviser Q3).
- [ ] 🚫 **Task 7.2** (blocked on the owner: needs a human-driven session with a live goal; see the 2026-10-23
  `012659Z` finding): Acceptance: focus on (with a live goal), a declared tick dropped, a rewritten failsafe tick
  delivered, focus off; awaiting-human in one session not cleared by another; a live goal loop caught in observe
  mode, then in act mode, observing the supervisor's `/goal clear` landing during the stop loop itself (spike 0.3
  saw it only in tool-calling turns).
- [ ] 🚫 **Task 7.3** (blocked on organic evidence or a human-gated release: three true positives or two releases; the count began 2026-10-23): Tune thresholds from the observe log and flip the default to `act` after three true positives
  and no false positive, or after two releases, whichever is first.

### Phase 8: Manual goals (#106)

- [x] ✅ **Task 8.1**: Spike: does `UserPromptSubmit` fire for a typed `/goal clear` and its aliases? If not,
  detection moves to the next Stop's transcript read. It does not: see section 2 of
  [the spike report](subagent-reports/261023-phase7-8-feasibility-advice-fable.md).
- [x] ✅ **Task 8.2**: TDD the supervisor's side-channel record before a clearing `/goal`, and the daemon's
  attribution (fresh matching record = supervisor, none = human, unreadable = supervisor, logged at WARNING with one
  context line telling the human to repeat the clear if it was theirs).
  [Report](subagent-reports/261023-phase8-2-impl.md).
- [x] ✅ **Task 8.3**: TDD the `manual-goals` mode: only `.goal-intent` writing is suppressed (not `continue`), added
  to the precedence list, status-line label, stated once on entry; exit by explicit switch-back (`hooks-daemon goals on`, `/mode goals auto`, CLI) or a new session, no TTL, a typed `/goal <condition>` does not exit it.
  The first mod section is a read-only display (Plan 00497 Task 3.5 scoped to it).
  Design and questions: [MANUAL-GOALS.md](MANUAL-GOALS.md). The control-panel mod section is Plan 00497's.

## Success Criteria

- [ ] A focused session receives no declared cron tick, no goal-ledger plan list and no work-driving advisory or
  supervisor prompt, and its failsafe tick names the focus task; `focus off`, a new session or the TTL restores
  normal behaviour, and expiry and restart survival are stated to the agent.
- [ ] An awaiting-human declaration in one session is not cleared by a prompt in another or by a supervisor line
  (ledger N378 closed).
- [ ] A goal tight loop is detected, logged with its evidence, broken and not re-armed; every unblock condition
  exits the mode.
- [x] ✅ The status line shows the active mode(s) and `status-line-explained` documents them (the
  `session_mode_indicator` segment: top mode by precedence plus `+N`, all six modes listed).
- [x] ✅ Guards behave identically in every mode; no config change is needed:
  `tests/integration/test_guards_identical_in_every_mode.py` dispatches guard-denied calls through the real
  controller with the default config under every mode and matches the no-mode decisions (usage-paused only adds its
  own deny in front); `tests/unit/handlers/test_session_mode_readers.py` pins which handlers may read mode state
  ([report](subagent-reports/261023-guards-every-mode.md)).
- [x] ✅ Full QA gate passes: the v3.71.0 `Release gate` run 40010977887 (whole gate, Python 3.11 to 3.13) passed
  on a tree carrying every merged task of this plan.

## Delivery & Milestones

- Plan filed; GitHub issue #91 opened from the owner's request.
- Owner approved the session modes concept and the rename; this revision folds in the design report.
