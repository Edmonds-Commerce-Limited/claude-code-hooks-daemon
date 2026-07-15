# Plan 00165: Install Permission Bug Fixes

**Status**: Complete
**Created**: 2026-07-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Two install-path bugs were surfaced by a field bug report captured while
installing the daemon into a consumer project (php-qa-ci). Both lived in the
upstream daemon source (this repo, which dogfoods itself in self-install mode),
so both were fixed here directly following the bug-fix lifecycle
(failing test → fix → QA → daemon restart).

The original field report is preserved alongside this plan as
[`hooks-daemon-install-perm-sloppy.md`](hooks-daemon-install-perm-sloppy.md)
for reference — it contains the full root-cause analysis for each issue.

The report also listed two lower-severity issues (#1 dead URL / wrong GitHub
org, #2 hardcoded stale version) that live in a *consumer* repo's
`scripts/deploy-skills.bash`, not upstream; those were fixed in that repo in a
prior session and are out of scope here.

## Goals

- Fix the `install.py` nested-install false positive that blocked the
  documented manual-install flow for every consumer (Issue #3).
- Stop the installer force-marking non-hook files (docs) as executable in
  `.claude/hooks/` (Issue #4).
- Cover both with regression tests so they cannot silently return.

## Non-Goals

- Consumer-repo issues #1/#2 (already fixed elsewhere).
- Reworking the recommended `install.sh` two-layer bootstrap path (unaffected).

## Tasks

### Phase 1: Issue #3 — nested-check false positive

- [x] ✅ **Task 1.1**: Reproduce — `.claude/hooks-daemon/src` marker is the
  documented manual-install layout, so `validate_not_nested` blocked every
  legitimate consumer install.
- [x] ✅ **Task 1.2**: Write failing regression tests (daemon + `install.py`
  copies): consumer clone allowed; daemon repo itself still gated on
  `self_install_mode`; helper edge cases.
- [x] ✅ **Task 1.3**: Replace the marker-path check with
  `project_root_is_daemon_repo()` — offline detection via
  `pyproject.toml [project].name`. Applied to both `daemon/validation.py` and
  standalone `install.py`.

### Phase 2: Issue #4 — installer force-chmods non-hook files

- [x] ✅ **Task 2.1**: Reproduce — `find $hooks_dir -type f ! -name .*` chmod'd
  every file in `.claude/hooks/`, including pre-existing docs, producing
  content-free git mode-bit noise on every reinstall.
- [x] ✅ **Task 2.2**: Write failing regression tests: docs stay `0o644` on disk
  and `100644` in the git index while real hooks are still forced `100755`.
- [x] ✅ **Task 2.3**: Introduce a single canonical `_DAEMON_HOOK_BASENAMES`
  list + `list_deployed_hook_paths` helper; scope `set_hook_permissions` and
  `git_force_executable` to installer-owned entrypoints only.

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Full QA green (13/13; 10114 tests pass, 95.3% coverage).
- [x] ✅ **Task 3.2**: Daemon restart verified RUNNING with new code.
- [x] ✅ **Task 3.3**: Commits pushed to `origin/main`.

## Success Criteria

- [x] Consumer manual install no longer blocked by the nested-install check.
- [x] Installer leaves non-hook files' permissions untouched.
- [x] Regression tests in place for both issues.
- [x] All QA checks pass; daemon loads.

## Delivery & Milestones

- Issue #3 fix (both copies + regression tests): `81337862`
- `install.py` black-normalisation: `ad31e4e2`
- Issue #4 fix (`hooks_deploy.sh` + regression tests): `a88d9969`
- Issue #3 test black-collapse: `dcb6553c`
