# Plan 00537: supervisor holds sends off main focus

**Status**: In Progress
**Created**: 2026-10-20
**Owner**: dev
**Priority**: High
**GitHub Issue**: #125
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #125: the ccy supervisor (`.claude/ccy/claude-supervise.py`) writes every
injection straight to the PTY master. It cannot tell which Claude Code thread has
focus. Two states put focus somewhere other than the main prompt:

- **A panel row is selected.** The supervisor's Enter opens that sub-agent's
  transcript, and its Esc deselects instead of interrupting.
- **A sub-agent's transcript is open.** Plain-text payloads go to that sub-agent:
  the continue line, notices and every dry-run marker.

The triage is in
[subagent-reports/261020-issue125-triage-opus.md](subagent-reports/261020-issue125-triage-opus.md).
Scope is the stand-in engineering ruling in
[RULING-fable.md](RULING-fable.md), not an owner ruling.

Related plans (dedupe scout, not duplicates):

- **[Plan 00160](../00160-supervisor-foreground-identity-and-reaping/PLAN.md)**
  (Dormant) wants an explicit foreground signal across Agent View sessions.
  This plan is narrower: it holds sends inside one session when focus may have
  left the main prompt. It does not replace that signal.
- **[Plan 00158](../00158-agent-thread-navigation-statusline/PLAN.md)** (Dormant)
  documents that the status-line payload carries no focus field.
- **[Plan 00328](../Completed/00328-human-model-choice-cannot-be-read-from-keystrokes/PLAN.md)**
  found that text chosen in Claude Code's own UI never crosses the PTY input
  tap. Arrow keys do cross, as bare CSI finals, which is the only signal this
  plan reads.

## Goals

- **Track focus from the human's own keys.** A focus model fed by the same stdin
  tap as `HumanInputLine` latches on navigation that could leave the prompt: a
  bare Up/Down, or an Enter while latched. A bare Esc from the human clears the
  latch.
- **Gate every send path.** `main_focus_confirmed` is a host-side `TickFacts`
  field, ANDed into `can_inject`. That covers the ESC interrupt and resubmit
  payloads, which are produced only when `idle` (`_evaluate_await`). Every send
  that does not pass through `can_inject` is gated explicitly as well:
  - the model switch, whose gate is `input_line_empty` only;
  - the abandoned-box Enter flush, taken when `not idle`. The gate sits ahead
    of the one-shot `_abandoned_box_handled` latch, so a held flush is not
    spent.
  - the restart coordinator's `/exit`;
  - the usage-pause send (`_usage_pause_outcome`), which runs before the
    machine's `evaluate` and the families. It applies its own copy of the
    `can_inject` condition, so the focus gate is added inside it. Typed into a
    sub-agent, it would not pause the main thread anyway.
  - the dry-run marker, which uses the same send path.
- **A held send is deferred and retried, never dropped or queued.** A held
  `/exit` creates no pending restart, adds no abandon count and starts no
  cooldown.
- **A hold is visible.** It writes a rate-limited `deferred` line to
  decision.log and posts a status-line banner telling the user to press Esc.
  The banner is posted at WARNING level, because an INFO message is dropped
  while a WARNING is live.
  The banner escalates after configurable bounds (default 300 s and 900 s).
  Escalation never resumes sending.

## Non-Goals

- Auto-refocus or a host-side screen model, meaning any key the human did not
  press. That is an owner decision and is filed as a follow-up.
- The mods `$.prompt.submit` route, which contradicts Plan 00497's standing
  ruling.
- An off switch. "Off" is the defect.
- Changing how `HumanInputLine._finish_csi` treats Up/Down, or weakening
  `_is_idle`, `load_foreground_sidecar` or the usage-pause send's own gate.

## Tasks

### Phase 1: Hold

- [x] ✅ **Task 1.1**: Red tests from stdin byte fixtures, then the focus model.
  Fixtures:
  - no navigation: nothing held;
  - Up then Esc: held, then released;
  - Up, Enter, text, Enter: held throughout;
  - Up with no Esc: held and escalating, never typing.
- [x] ✅ **Task 1.2**: Red tests, then `main_focus_confirmed` in `TickFacts`,
  computed host-side and ANDed into `can_inject`.
- [x] ✅ **Task 1.3**: Red tests, then gate each bypass family. One test
  enumerates the `_perform_injection(` call sites and asserts each one defers
  while latched. Include the restart `/exit` (no pending restart, no abandon
  count) and the dry-run marker.
- [x] ✅ **Task 1.4**: Red tests, then the rate-limited `deferred` log line, the
  status-line banner, and the two escalation bounds as one supervisor option.

### Phase 2: Fewer false holds

- [x] ✅ **Task 2.1**: A history-recall Up in a session with no panel holds
  until Esc. Find out whether a reading can show positively that no other thread
  exists, for example a live sub-agent count fresher than the latch event. Use
  it as a second way to clear the latch only if the count cannot under-report:
  an agent that has started must count until it stops. If it can under-report,
  record why and file a follow-up rather than ship it.

### Phase 3: Close out

- [x] ✅ **Task 3.1**:
  - Record the edit-to-live reload check (`CLAUDE/development/CcySupervisor.md`).
  - Add a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
  - Document the new option.
- [ ] ⬜ **Task 3.2**: File the follow-up plan. It covers auto-refocus and the
  screen model (agent-needs-human, cross-referencing Plans 00160 and 00453), and
  a spike for a non-screen focus signal. Note for #127: its restart request
  persists only when `/exit` was actually sent.

## Success Criteria

- [ ] Each change has a test that failed before it.
- [ ] No `_perform_injection` call site sends while the latch is set.
- [ ] The release note is in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Targeted QA is green on the merged head, and CI is green.

## Delivery & Milestones

- <!-- delivery commit hashes -->
