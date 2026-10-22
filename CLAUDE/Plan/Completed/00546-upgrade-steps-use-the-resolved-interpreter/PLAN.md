# Plan 00546: upgrade steps use the resolved interpreter

**Status**: Complete
**Created**: 2026-10-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #130

## Overview

#130 reports a silent failure during upgrade. Each item below was verified by triage:

- **The crash.** `eager_cleanup_stale_venvs` in `scripts/install/venv.sh` (around lines 1664-1672) probes
  `command -v python3` and runs `python3 <paths.py> list-stale-venvs`. `daemon/paths.py` uses 3.10+ syntax (`str | Path`
  with no `from __future__ import annotations`), so on a host whose `python3` is 3.9 the import fails.
- **The silence.** The failure is printed as a routine "kept venv-\* entries" line, `return 0` follows, and the upgrade
  reports success.
- **The ignored interpreter.** `HOOKS_DAEMON_PYTHON`, which the upgrade has already resolved and exported, is not read.

The wider class is a repeated version floor that is never checked at the entry points: `_MIN_PYTHON = (3, 8)` in
`signal_standalone.py` against 3.10+ code, and `install.py` on 3.11+. Shell steps take `python3` from PATH instead of
the resolved interpreter.

## Goals

- Phase 1, the reported defect: the stale-venv cleanup runs on the venv's own interpreter or `HOOKS_DAEMON_PYTHON`,
  never a bare `python3`. When neither is usable, the upgrade output says so loudly, as a warning naming the reason, and
  not as a routine line.
- Phase 2: one declared minimum Python, taken from `requires-python`, checked by a small guard written in old syntax at
  each entry point that an arbitrary interpreter can start. A too-old interpreter gets a one-line message and a non-zero
  exit, never a traceback.
- Phase 3, Defence Before Fix: a QA rule over shipped shell scripts that flags a command-position `python3`/`python`,
  with a reasoned allowlist for bootstrap probes.

## Non-Goals

- Supporting Python below the declared minimum.

## Tasks

### Phase 1: The reported defect (TDD)

- [x] ✅ **Task 1.1**: A shell test sources `venv.sh` with a fake 3.9 `python3` first on PATH and a working venv
  interpreter, and asserts that the cleanup works. A second case, with no usable interpreter, asserts a loud warning.
  Red first.
- [x] ✅ **Task 1.2**: Use `"$venv"/bin/python`, else `HOOKS_DAEMON_PYTHON`; never fall back to `python3`. Release note.

### Phase 2: One minimum, checked at the entry points

- [x] ✅ **Task 2.1**: Guard `paths.py`, `signal_standalone.py`, `install.py` and `bin/hooks-daemon` (with its template)
  against an interpreter below `requires-python`; fix `_MIN_PYTHON`.

### Phase 3: Defence Before Fix

- [x] ✅ **Task 3.1**: Run the `dbf` skill for the class "a shipped script runs a bare python3/python". The detector
  rule comes first, then the sweep.
  - Q1 to Q3 ruled by the delegated adviser ([OWNER-QUESTIONS.md](OWNER-QUESTIONS.md)); `scripts/debug_info.py` guarded.
- [x] ✅ **Task 3.2**: Merge to main, then flip to Complete and archive into `Completed/` in one commit (coordinator).

## Success Criteria

- [x] A stale-venv cleanup on a host whose `python3` is too old either works on the resolved interpreter or warns loudly
  (tested).
- [x] No entry point raises a traceback under an interpreter below the minimum (tested).
- [x] A QA rule finds the class, and every remaining instance is fixed or allowlisted with the owner's approval
  ([OWNER-QUESTIONS.md](OWNER-QUESTIONS.md) Q1).
- [x] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the pending-release holding area).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/ — see CLAUDE/PlanJournalling.md. -->

- Release note 014: `CLAUDE/UPGRADES/UNRELEASED/release-notes/014-upgrade-stale-venv-cleanup-uses-the-resolved-interpreter.md`.
- Release note 017: `CLAUDE/UPGRADES/UNRELEASED/release-notes/017-install-and-upgrade-scripts-run-the-resolved-interpreter.md`.
