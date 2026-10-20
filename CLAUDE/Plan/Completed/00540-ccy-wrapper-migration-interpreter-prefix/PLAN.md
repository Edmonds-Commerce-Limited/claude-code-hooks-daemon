# Plan 00540: ccy wrapper migration interpreter prefix

**Status**: Complete (2026-10-20)
**Created**: 2026-10-20
**Owner**: dev
**Priority**: High
**GitHub Issue**: #126
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #126. Since 3.69.0, `.claude/ccy/claude-supervise` is a POSIX `sh`
launcher that picks a Python (`CCY_PYTHON`, else the newest supported
`python3.x`) and execs its sibling `claude-supervise.py`. On upgrade,
`_migrate_wrapper_to_launcher`
(`src/claude_code_hooks_daemon/install/ccy_supervisor.py`) replaces the script
name with the launcher name in every active `CCY_CLAUDE_WRAPPER` export naming
the deployed script, and keeps every other byte.

A wrapper written as `python3 .claude/ccy/claude-supervise.py --arm --` therefore
becomes `python3 .claude/ccy/claude-supervise --arm --`. That is Python parsing a
shell script, and every ccy launch dies with a SyntaxError. The
`ccy_supervisor_integrity` handler does not inspect the word before the launcher
path, so the broken line passes silently.

## Goals

- **The migration rewrites an interpreter prefix.** A Python interpreter word
  immediately before the deployed script path becomes `sh`, giving
  `sh <dir>/claude-supervise`. Running it through `sh` keeps the "no exec bit
  needed" property the prefix existed for. "Interpreter word" covers
  `python`, `python3`, `python3.N`, an absolute path to one, and an
  `env python3` form.
- **A pinned interpreter is reported.** When the replaced word pinned a specific
  Python (a path or a version), the upgrade says so, and suggests
  `CCY_PYTHON=<that interpreter>` so the pin is not silently lost.
- **Already-broken lines are repaired.** A line broken by a 3.69.0 or 3.70.0
  upgrade (`<python> <dir>/claude-supervise`) is repaired the same way on the
  next upgrade.
- **The integrity check warns.** `ccy_supervisor_integrity` warns about a Python
  interpreter word in front of the launcher.

## Non-Goals

- Changing the launcher, or wrappers that name a script outside the deployed
  directory (those stay left alone and reported, as today).

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: Red tests, then the migration rewrite. Each of these is
  rewritten to `sh <dir>/claude-supervise`, with every other byte (quotes,
  `${…:-…}`, arguments) preserved:

  - `python3 X.py`
  - `python3.12 X.py`
  - `/usr/bin/python3 X.py`
  - `env python3 X.py`

  A bare `X.py` behaves as before, and a comment line is untouched.

- [x] ✅ **Task 1.2**: Red tests, then the repair of an already-broken
  `<python> <dir>/claude-supervise` line, and the pinned-interpreter report.

- [x] ✅ **Task 1.3**: Red tests, then the `ccy_supervisor_integrity` warning.

### Phase 2: Close out

- [x] ✅ **Task 2.1**: Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. It says that an upgrade repairs
  the broken line, and that 3.69.0 and 3.70.0 broke it.

## Success Criteria

- [x] Each change has a test that failed before it.
- [x] The reporter's reproduction gives a working `sh …/claude-supervise` line.
- [x] The release note is in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`005-ccy-wrapper-interpreter-prefix-repaired.md`).
- [x] Targeted QA is green on the merged head, and CI is green (run 39453689073 on `6e349af66`).

## Delivery & Milestones

- Merged to main in `6e349af66`. The fix is c8186ede1/f5ba6fbc4, the review fixes are 8b7faec53, the
  bare-script repoint promise is f2220c282, and the re-review fixes are d0ba739de.
- Targeted QA was 40/40 on `6e349af66`, with 2744 changed tests passing. The first run errored only
  because the daemon was stale. Reports are in `subagent-reports/`.
