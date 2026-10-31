# Plan 00555: self install venv python version lockout

**Status**: In Progress
**Created**: 2026-10-29
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The system Python changed from 3.11 to 3.13 underneath the self-install
workspace. The daemon venv (`untracked/venv-workspace-py311-2a519198`) kept
its 3.11 site-packages, but its `bin/python` began running 3.13. That
interpreter never sees those site-packages, so every daemon start failed with
`ModuleNotFoundError: claude_code_hooks_daemon`.

The session then locked itself out for hours:

- The fail-closed guard denied every diagnostic call.
- `restart` and `repair` ran through the same broken interpreter.
- No self-heal build ran during the drift, because the resolver still treated
  the drifted venv as usable. The "build running" message reported a lock held
  by some other process.
- The hook-side resolver and the wrapper disagreed about which venv exists.
- The stop hook blocked every stop indefinitely.

Only the owner, running `!` commands by hand, could diagnose and fix it.

The full evidence, including the commands, outputs and agent misdiagnoses, is
in [INCIDENT.md](INCIDENT.md). This plan makes interpreter drift a
self-healing, self-diagnosing event. A daemon that guards the session must
never be the reason the session cannot repair the daemon.

## Goals

- A venv whose recorded Python version differs from the interpreter it now
  runs is detected as stale. It is rebuilt automatically, or by `repair`,
  without a human.
- The wrapper, the hook-side health check and the background builder resolve
  the SAME venv from a single SSoT.
- A failed daemon start prints the interpreter version, the venv's
  `version_info` and the exact one-line fix.
- While the daemon is unreachable, read-only diagnostics stay allowed: Read,
  `ls`, `cat`, `git log`/`status`, and a `hooks-daemon diagnose` verb.
- The stop hook cannot block endlessly while the daemon is down. It is bounded,
  and it honours an `[awaiting-human]` stop.
- The background venv build records its log where the session can read it, and
  reports failure instead of looping.

## Non-Goals

- Supporting interpreters older than the project's minimum Python.
- Changing self-install mode semantics or client-install layout beyond venv
  resolution.

## Tasks

### Phase 1: Reproduce and diagnose

- [x] ✅ **Task 1.1**: Failing test. Build a venv whose `pyvenv.cfg`
  `version_info` differs from the running interpreter. Assert that the
  resolver reports it stale, not live and not missing. See
  [DBF-REPORT.md](DBF-REPORT.md), "The original defect".
- [x] ✅ **Task 1.2**: Trace the background build during the drift. No hook
  build ran. A venv that resolves but will not start was reported as "missing"
  whenever any process held the build lock (`init.sh:2901-2911`). Even a build
  that did run would have accepted py311 in its success check
  (`venv_bootstrap.sh:279`). See the
  [Phase 1 report](subagent-reports/261029-phase1-investigation.md).
- [x] ✅ **Task 1.3**: Map every venv resolver: the wrapper
  `.claude/hooks-daemon/bin/hooks-daemon`, the hook-side health check, the
  builder and `repair`. Name the divergence.

### Phase 2: Fix

- [ ] ⬜ **Task 2.1**: One venv-resolution SSoT, used by the wrapper, the
  hooks, the builder and `repair` (folds into 00100's scope where it overlaps).
- [x] ✅ **Task 2.2**: Interpreter-drift detection: a `pyvenv.cfg` version that
  differs from the runtime version means a stale venv. Rebuild it with the
  current interpreter, editable-install the repo plus the dev extras on a
  self-install, and re-key the directory name to the real version. A drifted
  venv no longer resolves, so self-heal rebuilds under a fingerprint keyed to
  the running version. The class is defended by `venv_interpreter_trust`
  ([DBF-REPORT.md](DBF-REPORT.md)). The dev extras are Task 3.1.
- [ ] ⬜ **Task 2.3**: `repair` must not need a working venv to rebuild one
  (extends 00456).
- [ ] ⬜ **Task 2.4**: On a start failure, print the diagnosis: interpreter
  version, venv `version_info`, whether site-packages is on `sys.path`, and
  the fix command.
- [ ] ⬜ **Task 2.5**: Fail-closed allow-list: read-only diagnostics plus a new
  `hooks-daemon diagnose` verb are permitted while the daemon is unreachable.
- [ ] ⬜ **Task 2.6**: Bound the daemon-down stop block. After N identical
  blocks, or on an `[awaiting-human]` prefix, allow the stop and say why.
- [ ] ⬜ **Task 2.7**: The background build writes its log to a known path,
  and the stop/status message names that path and the build's last result.

### Phase 3: Clean up and document

- [ ] ⬜ **Task 3.1**: Prune the orphaned `venv-workspace-py311-2a519198`; the
  live daemon venv is `venv-workspace-py313-0d6d49c6`. Make the self-install
  bootstrap install the `dev` extras, which were installed by hand after the
  incident.
- [ ] ⬜ **Task 3.2**: Add an "interpreter changed under the venv" entry to
  SELF_INSTALL.md and TROUBLESHOOTING, with the `sys.path` probe as the first
  diagnostic.
- [ ] ⬜ **Task 3.3**: Release note in the pending-release holding area.

## Success Criteria

- [x] A test reproduces the drift and passes after the fix.
- [ ] Simulated drift on a scratch self-install self-heals with no human
  command.
- [ ] With the daemon down, Read and `git log` succeed and
  `hooks-daemon diagnose` names the drift.
- [ ] A daemon-down stop loop ends after a bounded number of blocks.
- [ ] A release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the
  pending-release holding area).

## Delivery & Milestones

- Incident recorded: this plan and [INCIDENT.md](INCIDENT.md).
