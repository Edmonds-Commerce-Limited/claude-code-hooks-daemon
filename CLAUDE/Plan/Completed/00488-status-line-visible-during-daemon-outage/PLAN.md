# Plan 00488: status line visible during daemon outage

**Status**: Complete
**Created**: 2026-10-03
**Owner**: joseph
**Priority**: High
**GitHub Issue**: #72
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Whenever `ensure_daemon` fails, the generated status-line forwarder
(`.claude/hooks/status-line`, rendered by
`src/claude_code_hooks_daemon/install/forwarder_generator.py`
`_render_raw_stdout_daemon_down_block`) prints its down marker and then
`exit 1`. Claude Code v2.1.288 renders NOTHING for a status line command that
exits non-zero. We checked this directly with two scratch instances: identical
`echo MARK` commands, and only the `exit 0` one is shown. So the bar is blank
for the whole outage, which defeats the generator's own stated intent ("This
stdout is a DISPLAY line, so the outage stays visible").

It surfaced on the first host session of this repository: its only venv had
been built inside the ccy container, so the Plan 00456 self-heal built a host
venv in the background, and the status line stayed blank until the daemon came
up. Nothing about self-install mode caused it. Any project opened from a new
path view hits the same window.

A second defect sits behind the first: `init.sh` sets
`_HOOKS_DAEMON_STATUS_DOWN_TEXT` only for the not-provisioned state (Plan
00477). Once the line is visible, a venv-missing or venv-building state would
read `⚠️ DAEMON FAILED`, which misdescribes a normal, self-healing state.

## Goals

- The status-line forwarder exits 0 on the daemon-down path, so its marker is rendered
- Every daemon-down state init.sh can name gets its own status text: venv building, venv missing (no self-heal), not provisioned, version mismatch, genuine failure
- The test suite fails on a status-line forwarder that exits non-zero when the daemon is down

## Non-Goals

- Changing the exit contract of the other raw_stdout event, `WorktreeCreate`: its stdout is parsed as a value, and non-zero there correctly means "not handled" (Plan 00189)
- Making the venv build faster
- Changing the status line's content while the daemon is up

## Tasks

### Phase 1: Exit contract per raw_stdout event

- [x] ✅ **Task 1.1**: RED — change `tests/unit/install/test_forwarder_generator_raw_stdout.py` so the STATUS_LINE forwarder must end its daemon-down branch with `exit 0` (it currently asserts `exit 1`, pinning the defect), and WORKTREE_CREATE keeps `exit 1`
- [x] ✅ **Task 1.2**: GREEN — make the exit code a per-event catalogue property (alongside `daemon_down_stdout`) instead of hard-coding `exit 1` in `_render_raw_stdout_daemon_down_block`; a display event exits 0, a value event exits 1
- [x] ✅ **Task 1.3**: Regenerate the deployed forwarders and confirm `.claude/hooks/status-line` changed

### Phase 2: Name the outage

- [x] ✅ **Task 2.1**: RED — tests for `init.sh` setting `_HOOKS_DAEMON_STATUS_DOWN_TEXT` in the venv-missing branch: a "venv building" text while the Plan 00456 self-heal build is running, a distinct text when no self-heal is possible (damaged clone, orphan venv), and one for version mismatch
- [x] ✅ **Task 2.2**: GREEN — set those texts in `init.sh` where `_HOOKS_DAEMON_VENV_MISSING` / `_HOOKS_DAEMON_VERSION_MISMATCH` / the bootstrap state are decided; keep each line short enough for a status bar
- [x] ✅ **Task 2.3**: Check `status-line-explained` (Plan 00369) and `CLAUDE/Architecture/StatusLine.md` describe the down texts; update the one canonical home

### Phase 3: Fresh clone recovers with no human step

The owner's requirement: cloning to a new laptop with no venv must be detected
and resolved automatically. Here it was: the Plan 00456 self-heal built the
venv and the next hook started the daemon. But for that window (about 2
minutes) every safety handler was inactive, and nothing showed the owner it
was happening.

- [x] ✅ **Task 3.1**: Acceptance test from a genuinely fresh clone, in BOTH install modes (self-install and a client project with `.claude/hooks-daemon/`): no venv anywhere, open a session, take no manual step. Assert the venv builds, the daemon starts, and the status line goes from "venv building" to normal. Record gaps found. Run 2026-10-11 ([report](subagent-reports/261011-fresh-clone-e2e-sonnet.md)): the client mode reaches a running daemon with every status line exiting 0. A fresh client clone needs the by-design `provision.sh`, and when provisioned from main's config it came up DEGRADED (gap G4: main names a handler the fetched v3.69.0 release lacks), an artefact of testing from main. The self-install mode fails on a raw clone (Task 3.4), and a sub-second race was found (Task 3.5)
- [x] ✅ **Task 3.4**: A raw self-install clone has no `.claude/hooks-daemon.env` (gitignored), so `init.sh` never reaches the venv self-heal. The status line reads `DAEMON FAILED`, and SessionStart advises "install", which is wrong for this mode. Detect a self-install clone (this repository's own source tree) and bootstrap it with no human step, the way `scripts/bootstrap-self-install.sh` does. Or, if that cannot be automatic, name that script exactly
- [x] ✅ **Task 3.5**: In 2 of 3 self-install runs, a sub-second window right after the self-heal build started read `DAEMON FAILED` on the status line, and PreToolUse denied every tool call ("could not connect at all"). This contradicts the Task 3.2 ruling (fail open during the build). Find the state misclassification and make the window read and behave as "building"
- [x] ✅ **Task 3.2**: Decide how to treat the unprotected build window (wait on the lock, deny, or keep failing open and announce). Implemented per RULING-3.2 (coordinator ruling, Fable-assisted): option C, PreToolUse keeps failing open, and the started/running remedy gains a behavioural line. See [RULING-3.2-build-window.md](RULING-3.2-build-window.md)
- [x] ✅ **Task 3.3**: Plan counter drift on a new checkout. `hooksdaemon.latestPlanNumber` read 414 against 487 plans on disk, and `mkplan.bash` refused until it was reconciled by hand. The counter lives in `.git/config`, so a fresh clone or a second view drifts. When the on-disk maximum is ahead, reconcile it automatically (the counter can only move forward) instead of refusing

### Phase 4: Verify live

- [x] ✅ **Task 4.1**: Live check that the status bar shows the specific down text rather than going blank. The evidence has two halves:

  - The Task 3.1 run drove the real forwarders in fresh clones of both install modes. It captured the status-line stdout ("VENV BUILDING", then loading, then normal) with exit 0 throughout.
  - The Overview's direct Claude Code test shows that an exit-0 status line is rendered and an exit-1 one is not.

  Nobody has yet watched an interactive session's status bar during an outage.

- [x] ✅ **Task 4.2**: Targeted QA per `CLAUDE/QA.md` over the plan's merges (`02b4be6db..9517a3c7f`): 3983 passed, 0 failed, and every check except `plan_qa` passed. The two red items are the designed `too-broad` unmapped files and `plan_qa`'s advisory-only journal-freshness finding for Plan 00495. Because that detector failed, `project_handlers` is marked NOT MEANINGFUL, though its 238 tests passed. The daemon was restarted after the Phase 1 merge, which changed the event catalogue; the later merges changed only `init.sh`, which each hook reads afresh. The work is committed and pushed. #72 is commented on and closed in the archiving step.

## Success Criteria

- [x] With the daemon down, the status line is non-blank and names the outage. This is shown by captured forwarder output and Claude Code's exit-0 rendering (Task 4.1).
- [x] During a first-session venv build the line says the venv is building, including the moment between uv creating the interpreter and installing the package (Task 3.5).
- [x] The WorktreeCreate forwarder's daemon-down exit code is unchanged (still 1).
- [x] A fresh clone with no venv reaches a running daemon with no manual step in both install modes. The client mode was shown end to end (Task 3.1). The self-install raw clone was fixed by Task 3.4 and is covered by its sandbox tests, though not re-run end to end.
- [x] The build window is not silently unprotected. It is handled per RULING-3.2, a coordinator ruling made with Fable's help, not an owner decision: it fails open, announced on every call and on the status line, with guidance to avoid commits and pushes.
- [x] `mkplan.bash` works first time on a fresh clone; it was already fixed, and regression tests were added (Task 3.3).
- [x] Targeted QA green (Task 4.2).
- [x] The release-bound consequences are in the pending-release holding area: release notes 023, 024 and 025 in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. There is no config change.

## Delivery & Milestones

- Issue filed: #72
- Phases 1-2: `2790de8eb`. Task 3.2: `7e8e71e5b`. Tasks 3.4-3.5: `a468e29c7`. QA fixes: `9517a3c7f`.
