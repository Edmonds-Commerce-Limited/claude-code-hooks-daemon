# Plan 00501 Task 7.1: session modes documentation

Branch `worktree-501-phase7-docs`, base `9282f441d`.

## Where the doc lives, and why

The canonical home is a **daemon-owned core document**:
`src/claude_code_hooks_daemon/install/templates/core/SessionModes.core.md`. It is deployed to
`CLAUDE/core/SessionModes.core.md`, and it seeds the client-owned `CLAUDE/SessionModes.md`. A new
`CoreDoc("SessionModes", lambda _config: True)` entry in `install/core_docs.py` deploys it in every
install.

Why:

- DocumentationStrategy says the agent tree owns the depth (R2). A plain `CLAUDE/SessionModes.md`
  would also have satisfied that.
- But focus, awaiting-human and the status-line segment are on by default in every CLIENT. Their
  guidance and segment explanation therefore had to name a path the client actually holds.
- Plan 00334 found that a hand-written client path in guidance resolved to nothing in clients, and
  the core-doc mechanism is the established fix for that. Worktree is the precedent for an
  unconditional core doc.
- `test_core_doc_deployment.py` now records both naming surfaces in `_GUIDANCE_NAMED_DOCS` and adds a
  test that a stock install gets the document.

This repository's `CLAUDE/SessionModes.md` is the override:

- it links the core document (that link is tested);
- it routes to where the depth lives here: `development/CcySupervisor.md` for the supervisor gate,
  `Architecture/StatusLine.md` for the segment, `HANDLER_REFERENCE.md` for options, and Plan 00501.

The human-facing guides point at it rather than restating it.

## What the core document covers

- The modes table: label, entry and exit for each of `usage-paused`, `goal-blocked`,
  `awaiting-human`, `focus` and `unattended`.
- Precedence.
- The BLOCKED family:
  - A declared block ends only on a genuine human prompt in the same session, or at its 24-hour cap.
  - `unblock` refuses a declared block.
- The suppression matrix:
  - declared ticks;
  - the failsafe tick, which is dropped while BLOCKED and delivered with the task line under focus;
  - the watchdog tick;
  - goal injection;
  - the ledger challenge;
  - the supervisor prompts;
  - the stop-block interceptor.
- The adviser Q2 sentence: under focus the supervisor types no goal or session-actions directive,
  because the daemon writes neither signal. The post-compact `continue` and standing-auth are
  unaffected.
- Adviser Q3: the WARNING text and its fix (let the daemon load its registry and inspect the
  `.corrupt` file; a restart is not the fix).
- The goal-loop detector:
  - `observe` is the default and `act` is opt-in;
  - the no-ccy backstop is Claude Code's cap of 8.
- The restart `SESSION MODE:` line, and the `FOCUS MODE NOT CHANGED`/`NOT RENEWED` lines.
- The status-line segment and its red error badges.
- The `session-mode` verbs (`get`, `focus`, `focus off`, `unblock`), `mode-history` flags, and the
  IPC actions.
- The transition log and how its corruption is handled.

## Files changed

- `src/claude_code_hooks_daemon/install/core_docs.py`: the new `CoreDoc` entry.
- `src/claude_code_hooks_daemon/install/templates/core/SessionModes.core.md`: new; the canonical home.
- `CLAUDE/core/SessionModes.core.md`: new; the deployed copy, byte-identical to the template.
- `CLAUDE/SessionModes.md`: new; the override and routing.
- `CLAUDE/CLAUDE.md`: a routing-table row.
- `src/.../handlers/status_line/session_mode_indicator.py`:
  - `explain_segment` names the supervisor WARNING (`supervisor: session-modes file unreadable`) and
    its fix (`.corrupt`, not a restart), and points at the doc;
  - the constant `_SUPERVISOR_WARNING` was added.
- `tests/unit/handlers/status_line/test_session_mode_indicator.py`: the TDD test for the line above,
  red first.
- `tests/unit/install/test_core_doc_deployment.py`:
  - two `_GUIDANCE_NAMED_DOCS` rows;
  - a stock-install test, red first.
- Handler guidance now points at `CLAUDE/SessionModes.md` instead of growing:
  - `focus_mode_trigger.py`;
  - `failsafe_cron_blockage_suppressor.py`;
  - `auto_continue_stop.py`, whose awaiting-human paragraph also says the marker is the session mode.
- `goal_loop_detector` is unchanged. It deliberately has no guidance (see its docstring), so it keeps
  its coverage exemption.
- One-line pointers to the doc were added in:
  - `docs/guides/HANDLER_REFERENCE.md`: the focus_mode_trigger, goal_loop_detector and
    session_mode_indicator entries;
  - `CLAUDE/Architecture/StatusLine.md`;
  - `CLAUDE/development/CcySupervisor.md`.
- `CLAUDE/Plan/00501-session-modes/PLAN.md`: Task 7.1 ticked, with the chosen home.

No new release note was written: 020-024 cover the behaviour. The new deployed core document might
merit a mention at release; the coordinator can judge that.

## QA

- Docs QA `--lint`: 0 findings on every touched doc.
- Plan QA: 0 findings.
- Touched tests pass: the install suite, the indicator tests, the auto_continue_stop, focus and
  failsafe tests, and the guidance coverage test.
- Targeted QA, `llm_qa.py changed --range 9282f441d..HEAD --allow-unmapped`, run on a clean committed
  tree at `81fd4441b`: **`QA: 41/41 PASSED`**.

Head sha: the commit that adds this report, on top of `81fd4441b`.

## Notes for the coordinator

- The root `CLAUDE.md` hooksdaemon block is regenerated on daemon restart. It will pick up the three
  guidance pointers then; nothing was restarted here.
- A daemon restart or upgrade will also deploy `CLAUDE/core/SessionModes.core.md`. It is already
  committed byte-identical, so that deploy changes nothing.
