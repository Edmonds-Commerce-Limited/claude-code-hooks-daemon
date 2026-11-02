# Plan 00555: self install venv python version lockout

**Status**: Complete
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

- [x] ✅ **Task 2.1**: One venv-resolution SSoT, used by the wrapper, the
  hooks, the builder and `repair` (folds into 00100's scope where it overlaps).
  Python has one precedence. The bootstrap build and `cmd_repair` succeed only
  when the venv that resolves is the one they built, and a resolver failure
  fails the build. The DBF guards caught that last case on the first attempt.
  Turning the bash ranked scan into a pure interpreter-finder stays with
  Plan 00100 ([report](subagent-reports/261031-task-2.1-venv-ssot.md)).

- [x] ✅ **Task 2.2**: Interpreter-drift detection: a `pyvenv.cfg` version that
  differs from the runtime version means a stale venv. Rebuild it with the
  current interpreter, editable-install the repo plus the dev extras on a
  self-install, and re-key the directory name to the real version. A drifted
  venv no longer resolves, so self-heal rebuilds under a fingerprint keyed to
  the running version. The class is defended by `venv_interpreter_trust`
  ([DBF-REPORT.md](DBF-REPORT.md)). The dev extras are Task 3.1.

- [x] ✅ **Task 2.3**: `repair` must not need a working venv to rebuild one
  (extends 00456). A drifted venv does not resolve, so `repair` takes the
  venv-free path. A venv that resolves but cannot import the package is
  caught by a bounded import probe in the wrapper and rebuilt with
  `venv_bootstrap.sh repair --rebuild`
  ([report](subagent-reports/261031-task-2.3-repair-without-venv.md)).

- [x] ✅ **Task 2.4**: On a start failure, print the diagnosis: interpreter
  version, venv `version_info`, whether site-packages is on `sys.path`, and
  the fix command. `paths.py diagnose-venv` (stdlib-only), wired into
  `init.sh` `validate_venv` and the `start_daemon` timeout path
  ([report](subagent-reports/261031-task-2.4-start-diagnosis.md)).

- [x] ✅ **Task 2.5**: Fail-closed allow-list: read-only diagnostics plus a new
  `hooks-daemon diagnose` verb are permitted while the daemon is unreachable.
  The `diagnose` verb is on main (`27fd1725f`). The allow-list follows the
  **stand-in's ruling, not the owner's** (option b,
  [ruling](subagent-reports/261031-stand-in-ruling-fable.md)). It permits
  exact-shape Read, `ls`, `cat`, `head -n`, `tail -n`, `git log` and
  `diagnose` only when the daemon was never reached. `git status` was
  removed in Task 2.8 S4. Protected paths,
  quarantine DETAIL artefacts and the self-install capture logs stay denied
  ([build report](subagent-reports/261031-task-2.5-2.6-build.md),
  [review](subagent-reports/261031-task-2.5-2.6-review.md),
  [re-review](subagent-reports/261031-task-2.5-2.6-re-review.md)). The owner
  may overturn it.

- [x] ✅ **Task 2.6**: Bound the daemon-down stop block. After N identical
  blocks, or on an `[awaiting-human]` prefix, allow the stop and say why.
  **Stand-in ruling**, option a, N = 3. The count is kept per session and per
  event (`Stop` or `SubagentStop`), and per agent id for a SubagentStop that
  carries one (Task 2.8 S2). Every counted reason shares it, so alternating
  reasons still count. It resets only when the daemon answers,
  and an error in the counter keeps the block. CI-enforced, invalid-input,
  needs-provision, unconfigured-repo and version-mismatch blocks stay
  unbounded.

- [x] ✅ **Task 2.7**: The background build writes its log to a known path,
  and the stop/status message names that path and the build's last result.
  Every build path writes `untracked/.venv-bootstrap.result` and a holder
  record. `status`, `probe` and the daemon-down stop message name the last
  result and log. The first merge broke main because the build log needed
  `tee`; it was fixed forward at `00f9d734d`
  ([report](subagent-reports/261031-task-2.7-build-log.md)).

- [x] ✅ **Task 2.8**: Close the findings left open by the Task 2.5/2.6 security reviews
  ([review](subagent-reports/261031-task-2.5-2.6-review.md); the re-review's verdict was SHIP):

  - **N1, fixed**: a Read could follow a planted symlink, then `..`, to a file outside the project.
    The lexically normalised path must now stay inside a root as well
    ([report](subagent-reports/261031-task-2.8-build.md)).
  - **N2, fixed**: while the daemon is down, configured extra quarantine globs and a relocated
    `payload_capture.dir` were not covered. The snapshot now carries both.
  - S1, S2, S4 and S5 are fixed under a **second stand-in ruling, not the owner's**
    ([ruling](subagent-reports/261031-stand-in-ruling-2-fable.md);
    [S4/S1 report](subagent-reports/261031-task-2.8-s4-s1-build.md),
    [S2/S5 report](subagent-reports/261031-task-2.8-s2-s5-build.md)):
    - **S1, fixed**: a config file newer than the snapshot keeps the old globs and adds the
      `.claude/` lockdown.
    - **S2, fixed**: a SubagentStop that carries an agent id gets its own counter.
    - **S4, fixed**: `git status` is no longer on the daemon-down allow-list.
    - **S5, fixed**: a daemon that accepts a connection but then fails is counted under the
      same N = 3.
  - **Owner question, not a task**: whether a client install may read the daemon's own logs
    (the daemon log and the venv build log under `.claude/hooks-daemon/`) while the daemon is
    down. Today the whole `.claude/hooks-daemon/` tree is denied in a client install (review I4),
    which is the safe default. In self-install, only the hook-verdict, stop-event and
    payload-capture logs are denied.

### Phase 3: Clean up and document

- [x] ✅ **Task 3.1**: Prune the orphaned `venv-workspace-py311-2a519198`; the
  live daemon venv is `venv-workspace-py313-0d6d49c6`. Make the self-install
  bootstrap install the `dev` extras, which were installed by hand after the
  incident. The orphan had already been reaped. `create_venv_at_path` and
  `_repair_venv_locked` add `--extra dev` for a self-install only
  ([report](subagent-reports/261031-task-3.1-dev-extras.md)). An existing
  venv gains the extras at its next rebuild or `repair`.
- [x] ✅ **Task 3.2**: Add an "interpreter changed under the venv" entry to
  SELF_INSTALL.md and TROUBLESHOOTING, with the `sys.path` probe as the first
  diagnostic.
- [x] ✅ **Task 3.3**: Release note in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/release-notes/010-venv-python-version-drift.md`).

### Phase 4: Owner decisions

The owner delegated this phase: "pick clear winners using sub agent, raise
with me if its really not clear". The sub-agent found a clear winner for every
decision, so none went back to the owner
([report](subagent-reports/261102-phase4-winners.md)).

- [x] ✅ **Task 4.1**: [DBF-REPORT.md](DBF-REPORT.md) decisions 1–3:

  - **Accept the partial defence.**
  - **Do not build the wider data-flow rule now.** The only escape so far
    ran no interpreter, and most instances are in shell, which CodeQL cannot
    read. Revisit if a hand-built venv path escapes, or when Plan 00100 lands.
  - **Confirm the calibrations:** `tests/` excluded, workflow YAML uncovered
    (CI builds a fresh venv in every job), and "cannot tell" passes.

- [x] ✅ **Task 4.2**: Both stand-in rulings are **confirmed**: Tasks 2.5/2.6,
  and Task 2.8 S1/S2/S4/S5. A client install **may not** read the daemon's
  logs while the daemon is down. The daemon's own process log is not written
  to disk: its output goes to `/dev/null` and its logs are kept in memory
  (`cli.py:939-948`). A failed build is already
  fail-open, so the build log is readable when it matters. The same directory
  also holds payload captures and the hook-verdict log.

- [x] ✅ **Task 4.3**: Close the follow-ups the decisions surfaced. Each one
  starts with a failing test. Merged in ed18bf779, and release note 010 is
  extended to cover it. Report:
  [261102-task-4.3-build.md](subagent-reports/261102-task-4.3-build.md).
  `diagnose` reads only the last finished build's result record, not the
  holder record that exists only during a live build.

  - `status` (or SessionStart) reports `.daemon-down-stops.log`, as stand-in
    ruling 1 intended. Today it is written and nothing reads it.
  - The self-install daemon-down read rule must also deny
    `untracked/hook-errors.log`. It is a gap today: `_is_protected`
    (`init.sh:463-499`) has no entry for it. `log_error_to_file`
    (`core/front_controller.py:256`) writes the file whenever a hook crashes,
    so it can hold hook input.
  - `diagnose` prints the tail of the venv build log.

## Success Criteria

- [x] A test reproduces the drift and passes after the fix.
- [x] Simulated drift on a scratch self-install self-heals with no human
  command. The demo reproduced the incident shape, and the drift-at-current-key
  lockout it found is fixed
  ([demo](subagent-reports/261031-drift-self-heal-demo.md)).
- [x] With the daemon down, Read and `git log` succeed and
  `hooks-daemon diagnose` names the drift. Proven by
  `tests/integration/test_init_sh_daemon_down_read_only.py` and
  `test_bin_hooks_daemon_diagnose_without_venv.py`.
- [x] A daemon-down stop loop ends after a bounded number of blocks
  (`tests/integration/test_init_sh_daemon_down_stop_bound.py`).
- [x] A release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the
  pending-release holding area).

## Delivery & Milestones

- Incident recorded: this plan and [INCIDENT.md](INCIDENT.md).
