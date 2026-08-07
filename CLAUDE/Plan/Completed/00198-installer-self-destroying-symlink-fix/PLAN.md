# Plan 00198: Installer Self-Destroying Symlink Fix

**Status**: Complete
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A presentation-quality audit (`untracked/resume-readiness/MAIN-THREAD-FINDINGS.md`
MT-1/MT-1a) found two git-tracked symlinks with absolute, author-local targets
(`/workspace/...`), one of them self-referential and dangling right now in this
repo. Root cause: the deprecated `install.py`'s self-install deploy helpers had
no `source == dest` guard, so `copy_slash_commands()` unlinked the real
`.claude/commands/hooks-daemon-update.md` and replaced it with a symlink
pointing at itself, and `copy_init_script()` stored an absolute symlink target.

While tracing the root cause, the SAME defect class was found live in the
CURRENT (non-deprecated) `scripts/install/slash_commands.sh` —
`deploy_slash_commands()` and `deploy_single_slash_command()` collapse
`source_file`/`target_file` to the identical path in self-install mode with no
guard. Neither real orchestrator (`install_version.sh`, `upgrade_version.sh`)
currently calls these in self-install mode (both refuse to run in self-install
mode at all), so this instance is latent rather than observed in production —
but it is tested, documented library code, so it is fixed here too rather than
left as a landmine.

## Goals

- Delete the self-referential `.claude/commands/hooks-daemon-update.md`
  symlink and the dead `copy_slash_commands()` deploy helper (and its call
  site) from the deprecated `install.py`.
- Fix `.claude/init.sh` to a repo-relative symlink target, and fix the
  generator (`copy_init_script()`) so it never emits an absolute target again.
- Fix the same `source == dest` hazard in `scripts/install/slash_commands.sh`
  (`deploy_slash_commands`, `deploy_single_slash_command`) with a guard
  mirroring the one already proven in `deploy_init_script`.
- Add a durable regression test that walks every git-tracked symlink and
  fails if any stores an absolute target or fails to resolve within the repo.
- Verify a real client-mode install (`scripts/dummy-client-repo.sh`) still
  deploys cleanly after the removal.

## Non-Goals

- Not resurrecting the `/hooks-daemon-update` slash command — its recovered
  content is stale against this repo's own handlers (`curl_pipe_shell`,
  `daemon_location_guard`, legacy venv path) and the packaged skill
  (`src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md`) already
  owns upgrades. Resurrecting it would be a second source of truth.
- Not touching CHANGELOG.md/RELEASES/\*.md historical entries that mention the
  now-removed command — those are an accurate historical record of what
  shipped in past releases and are not release-workflow material for this fix.
- Not addressing the other MT-\* findings from the audit (CI, coverage.json,
  stray test scripts, exec bits, README structure) — out of scope for this
  plan.

## Tasks

### Phase 1: TDD regression coverage

- [x] ✅ **Task 1.1**: Write `tests/integration/test_repo_symlink_hygiene.py`
  — walks `git ls-files -s`, asserts every tracked symlink target is
  non-absolute and resolves; confirmed RED against the two live bugs.
- [x] ✅ **Task 1.2**: Write
  `tests/unit/install/test_slash_commands_self_install_safety.py` — exercises
  `deploy_slash_commands`/`deploy_single_slash_command` in a synthetic
  self-install layout; confirmed RED (source content destroyed, absolute
  self-referential symlink created).

### Phase 2: Fix the defects

- [x] ✅ **Task 2.1**: `git rm .claude/commands/hooks-daemon-update.md`;
  remove `copy_slash_commands()` + its call site from `install.py`.
- [x] ✅ **Task 2.2**: Fix `copy_init_script()` to emit a repo-relative
  symlink target (`os.path.relpath`); re-create the tracked `.claude/init.sh`
  symlink as `../init.sh`.
- [x] ✅ **Task 2.3**: Add the `source == dest` guard (bash `-ef`) to both
  `deploy_slash_commands()` and `deploy_single_slash_command()` in
  `scripts/install/slash_commands.sh`.
- [x] ✅ **Task 2.4**: Confirm both regression suites are GREEN.

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Full unit + integration suite green (10,838 tests).
- [x] ✅ **Task 3.2**: `./scripts/qa/llm_qa.py all` — 14/14 PASSED.
- [x] ✅ **Task 3.3**: `./bin/hooks-daemon restart` -> RUNNING, clean logs.
- [x] ✅ **Task 3.4**: `scripts/dummy-client-repo.sh create` against the
  committed fix, verify a clean client-mode install, `destroy` the fixture.

## Success Criteria

- [x] No tracked symlink stores an absolute target or is self-referential.
- [x] `install.py`'s dead/dangerous slash-command deploy helper is gone.
- [x] The same hazard class is closed in the live `scripts/install/*.sh`.
- [x] New regression tests fail against the pre-fix code and pass after.
- [x] A real client-mode install still deploys cleanly.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00198-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivered at `9afd566d` (symlink fixes, both deploy helpers, two new
  regression suites). Client-mode verified post-delivery via
  `scripts/dummy-client-repo.sh create`/`destroy`: clean install, daemon
  RUNNING, `.claude/commands/` correctly absent (no source files to
  deploy), `.claude/init.sh` deployed as a real file (normal-mode copy,
  unaffected by the self-install symlink fix).
