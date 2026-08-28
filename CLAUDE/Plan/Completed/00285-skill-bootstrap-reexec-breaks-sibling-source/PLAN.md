# Plan 00285: skill bootstrap reexec breaks sibling source

**Status**: Complete
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

- [x] ✅ **Task 3.1**: Add a QA check (shell-audit family) that flags a
  script containing the `# === SELF-BOOTSTRAP BEGIN` marker and, after it,
  a `$(dirname "$0")`/`$0`-relative `source` — proves RED against the
  unfixed scripts before the fix lands, GREEN after.

### Phase 4: Secondary finding — restart exit 143

- [x] ✅ **Task 4.1**: Investigated why `restart` reports exit 143 despite a
  successful restart — **not reproduced**; recorded findings + follow-up
  below.

### Phase 5: Verification

- [x] ✅ **Task 5.1**: `scripts/dummy-client-repo.sh create`, verified the
  fixed `daemon-cli.sh`/`health-check.sh` inside it, `destroy`.
- [x] ✅ **Task 5.2**: Full QA green, daemon restart RUNNING.

## Success Criteria

- [x] All three scripts resolve their venv correctly when invoked as a
  relocated copy (simulating post-bootstrap-re-exec `$0`).
- [x] New DBF guard is RED against the pre-fix scripts and GREEN after.
- [x] Full QA passes for every file touched by this plan (`black`, `ruff`,
  `mypy`, `pytest` all green on the changed set; the one whole-suite
  `llm_qa.py all` run during this plan reported 2 failures, both confirmed
  to be a concurrent sibling agent's untracked, unrelated
  `docs_qa/quotes.py`/`test_quotes.py` — not this plan's files).
- [x] Verified in a real client-mode install, not just self-install mode.

## Follow-up: `restart` exit-143 (not reproduced)

The field report's secondary finding — `restart` completes successfully but
returns exit 143 (128+SIGTERM) — was investigated but **could not be
reproduced**, either in self-install mode or against a real client-mode
install (`scripts/dummy-client-repo.sh`), across repeated `daemon-cli.sh restart` invocations with and without the bootstrap stanza active.

Ruled out by reading `cmd_stop`/`cmd_restart`/`cmd_start` in
`src/claude_code_hooks_daemon/daemon/cli.py`:

- `cmd_stop` sends `os.kill(pid, signal.SIGTERM)` to the **daemon's own PID**
  only — never `os.killpg`, never the calling shell's PID or process group.
- The daemon double-forks and calls `os.setsid()` before doing any work,
  detaching it into its own session — a signal delivered to it cannot reach
  its original parent's process group.
- No code path in the stop/start/restart flow ever sends `SIGKILL` or any
  signal to itself.

Since the report's own console log shows the full success output printed
*before* the 143 status was observed, a genuine signal-terminated process
would not have completed printing — which points at something outside this
script's own control (e.g. the reporter's Bash-tool harness or shell
imposing a timeout/signal on the whole invocation once the backgrounding
daemon triggers its own process-group heuristics). This is a plausible
environment-specific interaction, not a defect visible in this codebase.

**Recorded as a follow-up, not fixed here**: if this recurs, capture
`bash -x` output plus the exact invocation context (interactive terminal vs.
agent tool harness) so the reproduction conditions are pinned down.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00285-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed + field report imported/sanitised: 73fe4e37
- Fix landed (all three scripts + dependent tests): 1ffb5e4a
- PLAN.md/journal update (Phase 1/2): e249ee49
- DBF guard (`audit_shell.py` bootstrap-reexec-dollar0-source rule): 798a5bc2
- Format-autofix follow-up on venv resolution test: 37ca44e0
- Phase 4/5 investigation + client-mode verification recorded: f3f9f561
