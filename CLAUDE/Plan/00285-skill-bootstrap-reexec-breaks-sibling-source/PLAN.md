# Plan 00285: skill bootstrap reexec breaks sibling source

**Status**: In Progress
**Created**: 2026-08-28
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A field report (see `FIELD-REPORT.md` in this folder) found that `daemon-cli.sh`,
`health-check.sh` and `init-handlers.sh` are unusable on any installation whose
skill scripts differ from the latest GitHub release. Each opens with a
self-bootstrap stanza that, on a sha256 mismatch against the release manifest,
downloads the current body to a `mktemp` file and `exec`s it. After that `exec`,
`$0` is the temp path — but ~95 lines later each script does
`source "$(dirname "$0")/_resolve-venv.sh"`, which now looks for the sibling
shim in `/tmp` and dies. Because the mismatch branch fires on every stale
install, this is not an edge case: it is the default path for anyone not on the
newest release, which is exactly when they most need `/hooks-daemon health`.

`PROJECT_ROOT` (and therefore `DAEMON_DIR`) is computed independently by
walking up from `$(pwd)`, so it survives the re-exec intact — only the
`$0`-relative lookup does not. The fix anchors venv resolution to `DAEMON_DIR`
(which is a full checkout of the daemon repo in a real client install, so
`$DAEMON_DIR/scripts/lib/resolve_venv.sh` exists there) instead of to the
script's own directory. This is the report's "preferred" fix. The report's
"alternative" (keep `_resolve-venv.sh`, anchor it via `DAEMON_DIR`) does not
actually work: `_resolve-venv.sh` is a skill-only file that ships alongside
the wrappers under `.claude/skills/hooks-daemon/scripts/`, not inside
`DAEMON_DIR` (`.claude/hooks-daemon/`) — those are two different deployed
directories, so there is no `DAEMON_DIR`-relative path to it either. Going
direct to the canonical library is the only sound fix.

## Goals

- Fix `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` so venv
  resolution survives the self-bootstrap re-exec, by sourcing
  `$DAEMON_DIR/scripts/lib/resolve_venv.sh` directly instead of
  `$(dirname "$0")/_resolve-venv.sh"`.
- Add a regression test that reproduces the relocated-`$0` failure mode
  (RED before the fix, GREEN after).
- Add a DBF guard (QA check) that rejects `$0`-relative sibling `source`
  after the bootstrap stanza, so this class cannot silently recur.
- Investigate the secondary `restart` exit-143 observation from the report.
- Verify in client-mode (`scripts/dummy-client-repo.sh`), since this is
  client-install surface that self-install mode does not exercise.

## Non-Goals

- Deleting the now-unused `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh`
  shim. It stays correct and independently tested; only the three wrapper
  scripts stop routing through it. Removing it entirely touches a wide,
  unrelated set of tests (`test_skill_scripts_venv_resolution.py`,
  `test_venv_resolver_parity_matrix.py`, `test_install_venv_resolver.py`,
  docs/PLAN history) for no behavioural gain — tracked as a follow-up, not
  done here.
- Consolidating `install.sh`/`upgrade.sh` further — the report confirms
  neither is affected by this bug class (no bootstrap+sibling-source pairing).

## Tasks

### Phase 1: Import report + reproduce

- [x] ✅ **Task 1.1**: Import and sanitise the field report into this folder
  as `FIELD-REPORT.md`.
- [x] ✅ **Task 1.2**: Write a failing acceptance test that runs
  `daemon-cli.sh`/`health-check.sh`/`init-handlers.sh` from a relocated
  copy (simulating post-re-exec `$0`) and asserts venv resolution still
  succeeds.

### Phase 2: Fix

- [x] ✅ **Task 2.1**: Change all three scripts to anchor `RESOLVE_LIB` at
  `$DAEMON_DIR/scripts/lib/resolve_venv.sh` and call `resolve_venv_python`
  directly, mirroring `install/templates/hooks-daemon`'s existing pattern.
- [x] ✅ **Task 2.2**: Update `test_skill_scripts_venv_resolution.py`'s
  `test_wrapper_sources_resolver` (now asserts the canonical lib is
  sourced) and `test_health_check_honest_failure.py`'s stub location
  (now `scripts/lib/resolve_venv.sh` under the fixture's `DAEMON_DIR`).
- [x] ✅ **Task 2.3**: Confirm the new acceptance test from Task 1.2 is GREEN.

### Phase 3: DBF guard

- [ ] ⬜ **Task 3.1**: Add a QA check (shell-audit family) that flags a
  script containing the `# === SELF-BOOTSTRAP BEGIN` marker and, after it,
  a `$(dirname "$0")`/`$0`-relative `source` — proves RED against the
  unfixed scripts before the fix lands, GREEN after.

### Phase 4: Secondary finding — restart exit 143

- [ ] ⬜ **Task 4.1**: Investigate why `restart` reports exit 143 despite a
  successful restart. Fix with a test if cheap/safe, else record findings
  as a follow-up task.

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: `scripts/dummy-client-repo.sh create`, verify fixed
  `daemon-cli.sh` inside it, `destroy`.
- [ ] ⬜ **Task 5.2**: Full QA green, daemon restart RUNNING.

## Success Criteria

- [ ] All three scripts resolve their venv correctly when invoked as a
  relocated copy (simulating post-bootstrap-re-exec `$0`).
- [ ] New DBF guard is RED against the pre-fix scripts and GREEN after.
- [ ] Full `./scripts/qa/llm_qa.py all` passes.
- [ ] Verified in a real client-mode install, not just self-install mode.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00285-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
