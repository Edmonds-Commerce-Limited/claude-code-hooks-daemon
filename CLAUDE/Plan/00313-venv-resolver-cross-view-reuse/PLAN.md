# Plan 00313: venv resolver cross-view reuse

**Status**: In Progress
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: High (pre-release, v3.59.0)
**Recommended Executor**: Sonnet
**Execution Strategy**: Single python-developer agent, TDD

## Overview

Owner field report: launching a HOST-level Claude Code in this repo folder
(the same directory the ccy container mounts as `/workspace`) leaves the
hooks daemon unable to start — the resolver picks the container-built venv
`untracked/venv-workspace-py311-81c29529/`, whose editable-install `.pth`
points at `/workspace/src`, a path that does not exist on the host, so
`claude_code_hooks_daemon` is unimportable.

The venv naming design (Plan 00100/00104) already anticipated exactly this:
`project_path_slug()` prepends the project-root slug so host and container
views of the same interpreter get DISTINCT venvs. The defect is that the
resolver's fallback steps defeat the slug:

- **Metadata step**: matches on `lock_hash` alone, which is identical for
  host and container views of the same repo (same `pyproject.toml` +
  `uv.lock`). It only falls through today because the recorded
  `python_path` happens not to exist on the host.
- **Scan fallback**: takes the FIRST executable `venv-*/bin/python`. The
  container venv's `bin/python` symlinks to `/usr/bin/python3.11`, which
  exists on the host too — so the scan "succeeds" and hands back a venv
  whose site-packages are wired for a different root view.

## Goals

- A slug-carrying venv (`venv-<slug>-py{MM}-{hex}[-host]`) is eligible for
  resolution ONLY when its slug matches `project_path_slug()` of the
  current root — in the fingerprint step, the metadata step, and the scan
  fallback, in BOTH the Python SSOT
  (`src/claude_code_hooks_daemon/daemon/paths.py`) and any bash resolver
  with independent scan logic.
- Legacy un-slugged names (`venv-py311-...`, bare `venv`) keep their
  current behaviour (no slug to check).
- A host invocation therefore misses, and `ensure_venv` builds a fresh,
  correctly-slugged host venv alongside the container one — neither view
  ever corrupts the other.

## Non-Goals

- Rebuilding or migrating existing venvs (creation logic already slugs
  correctly; only resolution reuse is broken).
- Making the container venv importable from the host (wrong direction —
  separation, not sharing, is the design).

## Tasks

### Phase 1: TDD fix

- [x] ✅ **Task 1.1**: RED — unit tests (extend
  `tests/unit/daemon/test_paths_resolve_existing_venv.py` and
  `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py`) proving a
  slug-mismatched venv is skipped by (a) the scan fallback in
  `resolve_existing_venv_python`, (b) the metadata and scan steps in
  `resolve_existing_venv_python_with_diagnostics`, with a slug-MATCHED and
  a legacy un-slugged venv still resolved. Include the field shape: venv
  dir named for slug `workspace` while `daemon_dir` resolves elsewhere.
- [x] ✅ **Task 1.2**: GREEN — implement a shared slug-eligibility helper in
  `daemon/paths.py`; apply at every resolution step that touches a
  `venv-*` candidate. Add a diagnostics step line naming the skip reason.
- [x] ✅ **Task 1.3**: Bash parity — apply the same slug check to
  `scripts/lib/resolve_venv.sh` and
  `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh`
  if their scan logic is independent of the Python SSOT; if they shell out
  to the SSOT, verify and document that no separate fix is needed.
- [x] ✅ **Task 1.4**: Full QA green; fold into the v3.59.0 release
  (CHANGELOG entry + release notes line).

## Success Criteria

- [ ] Host-level invocation in a repo carrying a container-built venv
  refuses the mismatched venv and (via ensure_venv) builds its own.
- [ ] Container behaviour unchanged (fingerprint match still first hit).
- [ ] QA 25/25.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. Activity log lives
     in JOURNAL/. -->

- <!-- delivery commit hash -->
