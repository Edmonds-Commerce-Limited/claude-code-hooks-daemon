# Plan 00523: supervisor answers the rate limit menu

**Status**: Not Started
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

When the account hits its five-hour or weekly limit, Claude Code shows an
interactive menu. One of its options waits until the limit resets. An
unattended session stays on that menu until somebody answers it. The owner
asked that the ccy supervisor answer it by pressing Enter, so the session
waits for the reset by default.

The supervisor cannot see the menu today. `OutputActivity.record` in
`.claude/ccy/claude-supervise.py` keeps only a byte count and the time of the
last output from the child. It uses those to tell busy from settled, and never
reads what the child prints. Its only handling of limits is the daemon's usage
pause (Plan 00479 Task 4.5), which is a separate trigger. So this plan adds a
new capability: a bounded tail of recent child output, and a recogniser for
the menu in it.

Read Plan 00487 (the supervisor plugin API) before choosing where the
recogniser lives. Read Plan 00339 (payload-then-`\r` submit timing) before
writing the keystroke.

## Goals

- When Claude Code's rate-limit menu appears, the supervisor presses Enter
  exactly once and the session waits for the reset.
- The key it sends is proven, against a captured real menu, to select the
  wait option.

## Non-Goals

- Choosing any option other than waiting (extra usage, switching model).
- Changing the daemon's usage pause (Plan 00479) or its `/compact`.
- Editing the live supervisor in place. The change ships through the
  installer-managed template and reaches `.claude/ccy/` like any other
  supervisor change.

## Tasks

### Phase 1: Evidence

- [ ] ⬜ **Task 1.1**: Capture the real menu as raw PTY bytes (ANSI included),
  for both the five-hour and the weekly limit if they differ, with the
  highlighted default recorded. Commit the capture as a test fixture. If
  Enter does not select waiting, record the key sequence that does.

### Phase 2: Recogniser (TDD)

- [ ] ⬜ **Task 2.1**: RED: tests on the captured bytes. The menu is
  recognised. Ordinary output that quotes the menu's wording is not
  recognised. Output split across chunks is handled.
- [ ] ⬜ **Task 2.2**: GREEN: a bounded tail of child output, kept as a ring
  buffer like `RawInputTap`, plus the recogniser. Put it in a plugin if Plan
  00487's API fits; otherwise say why it does not.
- [ ] ⬜ **Task 2.3**: The keystroke is sent once per menu occurrence. A latch
  clears only when the menu leaves the screen. Each press is logged to the
  decision log, and dry-run mode logs it without sending.

### Phase 3: Verify and ship

- [ ] ⬜ **Task 3.1**: Verify on a real session that hits a limit. The menu is
  answered, the session waits, and work resumes at the reset.
- [ ] ⬜ **Task 3.2**: Add a release note for the new supervisor behaviour.

## Success Criteria

- [ ] On a real limit hit, the menu is answered once and the session waits for
  the reset, proven by tests that failed first and by one live observation.
- [ ] Release-bound consequences are recorded in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00523-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed at the owner's request; the dedupe scout found no overlapping plan
  (55 live plans checked).
