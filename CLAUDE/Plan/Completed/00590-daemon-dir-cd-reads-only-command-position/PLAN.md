# Plan 00590: daemon dir cd reads only command position

**Status**: Complete (2026-11-10)
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #194

## Overview

`daemon_location_guard` (R-DAEMON-DIR-CD) denies a command that changes no
directory: `cd <root> && grep -c "cd " .claude/hooks-daemon/CLAUDE.md`, and
`grep -n -E "def |cd " .claude/hooks-daemon/src/x.py | wc -l` (both reproduced
on `main` with `hooks-daemon probe --only daemon_location_guard`; the control
`"xx "` is allowed). `_path_text` removes every quote before
`_CD_INTO_DAEMON_DIR` runs, so a quoted search pattern's `cd` joins grep's file
argument. A lone bare `grep` is already exempt (`is_plain_data_command`).

The handler deliberately does not blank quoted literals, because
`bash -c "cd .claude/hooks-daemon && ls"` executes its argument (denied today,
and must stay denied). The fix is to judge `cd`/`pushd` only where it can be a
command.

## Goals

- A `cd`/`pushd` counts only in command position: top level, or inside text a
  shell will execute (`bash -c`/`sh -c`, `eval`, `$(…)`, backticks, an executing
  heredoc), via the shared command-position tokeniser rather than a new regex.
- Every executing twin of a newly allowed shape keeps its deny, with a test each.

## Non-Goals

- Changing what counts as the daemon directory, or the deny message.

## Tasks

### Phase 1: Command-position matching

- [x] ✅ **Task 1.1**: RED tests in both directions (the issue's shapes allowed; every
  existing deny plus each executing twin still denied). GREEN: match `cd`/`pushd`
  in command position only, reusing `utils/command_position.py`. Release note.
  Delivered as an opt-in `data_heads=SEARCH_HEADS` on `command_position_view`
  (grep/egrep/fgrep/rg only; `echo`/`printf` stay judged, the shared default unchanged).

## Success Criteria

- [x] The issue's reproduction is allowed on `main`; `bash -c "cd .claude/hooks-daemon && ls"` still denies.
- [x] Release-bound consequence recorded as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (`024-daemon-dir-cd-reads-only-command-position.md`).

## Delivery & Milestones

- `fee5dc457` (merge `46cf5c71a`), main CI run 42724555662 green; GitHub #194 closed.
