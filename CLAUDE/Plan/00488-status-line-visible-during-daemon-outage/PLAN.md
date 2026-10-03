# Plan 00488: status line visible during daemon outage

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: RED — change `tests/unit/install/test_forwarder_generator_raw_stdout.py` so the STATUS_LINE forwarder must end its daemon-down branch with `exit 0` (it currently asserts `exit 1`, pinning the defect), and WORKTREE_CREATE keeps `exit 1`
- [ ] ⬜ **Task 1.2**: GREEN — make the exit code a per-event catalogue property (alongside `daemon_down_stdout`) instead of hard-coding `exit 1` in `_render_raw_stdout_daemon_down_block`; a display event exits 0, a value event exits 1
- [ ] ⬜ **Task 1.3**: Regenerate the deployed forwarders and confirm `.claude/hooks/status-line` changed

### Phase 2: Name the outage

- [ ] ⬜ **Task 2.1**: RED — tests for `init.sh` setting `_HOOKS_DAEMON_STATUS_DOWN_TEXT` in the venv-missing branch: a "venv building" text while the Plan 00456 self-heal build is running, a distinct text when no self-heal is possible (damaged clone, orphan venv), and one for version mismatch
- [ ] ⬜ **Task 2.2**: GREEN — set those texts in `init.sh` where `_HOOKS_DAEMON_VENV_MISSING` / `_HOOKS_DAEMON_VERSION_MISMATCH` / the bootstrap state are decided; keep each line short enough for a status bar
- [ ] ⬜ **Task 2.3**: Check `status-line-explained` (Plan 00369) and `CLAUDE/Architecture/StatusLine.md` describe the down texts; update the one canonical home

### Phase 3: Verify live

- [ ] ⬜ **Task 3.1**: Live check in a real Claude Code session: stop the daemon and make it unstartable (or move the venv aside in a scratch checkout), then confirm the status bar shows the specific down text rather than going blank
- [ ] ⬜ **Task 3.2**: Targeted QA per `CLAUDE/QA.md`, daemon restart, commit and push; comment the implementation summary on #72 and close it

## Success Criteria

- [ ] With the daemon down, a live Claude Code session shows a non-blank status line naming the outage
- [ ] During a first-session venv build the line says the venv is building
- [ ] The WorktreeCreate forwarder's daemon-down exit code is unchanged
- [ ] Targeted QA green

## Delivery & Milestones

- Issue filed: #72
