# Plan 00103: v3.9.1 — venv resolution fail-fast & SSOT/DRY consolidation

**Status**: Not Started — awaiting review #3 sign-off (two FATAL reviews preceded this version)
**Created**: 2026-04-30
**Owner**: Claude (Opus 4.7) + downstream Opus reviewer
**Priority**: High (regression patch)
**Recommended Executor**: Sonnet 4.5 (Sub-Agent Orchestration), Opus 4.6 review gate
**Execution Strategy**: Sub-Agent Orchestration with mandatory Opus review before implementation

## Overview

A field bug report (`context/2026-04-30-field-report.md`) surfaced a v3.9.0 regression that breaks every diagnostic helper script (`health-check.sh`, `daemon-cli.sh status`, etc.) on hosts where the system default `python3` is older than 3.11 — even when a compatible Python (3.11/3.12/3.13) exists at a versioned path and the daemon process itself is running healthily on it.

Root cause: `_resolve-venv.sh` invokes the Python SSOT (`paths.py resolve-venv`) using a bare `python3` from PATH. On older-stable distros (RHEL/CentOS/Debian-stable/cPanel) `python3` resolves to 3.9.x, so `paths.py:22 import tomllib` fails at module load. The `&&` short-circuit *plus* the `2>/dev/null` redirection silently swallows the crash and falls through to the legacy `untracked/venv/bin/python` path that was retired in v3.7.0. Every diagnostic then reports a false-positive "Daemon installation may be corrupted" message.

Two consecutive FATAL hostile reviews (`context/2026-04-30-review-1-opus.md`, `context/2026-04-30-review-2-opus-dry.md`) revealed the original plan addressed only **one of five** equivalently-broken sites:

1. `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` — original target
2. `scripts/venv-include.bash::_resolve_venv_dir` — same `${HOOKS_DAEMON_PYTHON:-python3}` + `2>/dev/null` + legacy fallback
3. `scripts/install/venv_resolver.sh::resolve_existing_venv_python` — sourced by `upgrade_version.sh` at Layer-2 boundary, same pattern
4. `init.sh::_resolve_python_cmd` — sourced by every hook wrapper on every event fire (hot path)
5. `scripts/install/venv.sh:261` (`venv_lock_hash_matches`) — hardcodes literal `python3`, ignores even an exported `HOOKS_DAEMON_PYTHON`. This is the actual root cause of the field-report "rebuilding venv on every upgrade" loop.

The user has set two non-negotiable design principles:

> *"if we don't have python 3.11 available we need to fail fast and clear. We absolutely need to be using a single python version all the time — there should be a single source of truth for the correct python version."*

> *"we should never be doing `:-python3` fallback which is total diceroll."*

This plan implements those principles via a single canonical bash library (`scripts/lib/resolve_venv.sh`) sourced by all four shell sites, fixes the hardcoded-`python3` site, defers `tomllib` import in `paths.py` to remove the underlying time-bomb, and **eliminates `${VAR:-python3}` patterns everywhere** (bootstrap explicit-probes versioned interpreters and fail-fasts; post-bootstrap uses the venv exclusively).

## Goals

1. **Single Python source of truth.** Once the daemon venv exists at `$DAEMON_DIR/untracked/venv-py*/bin/python`, every shell wrapper, every CLI invocation, every diagnostic uses *that* interpreter. Period. No bare `python3` calls anywhere downstream of bootstrap.
2. **Single bash library for venv resolution.** All four resolver call sites (`_resolve-venv.sh`, `venv-include.bash`, `venv_resolver.sh`, `init.sh::_resolve_python_cmd`) become 3–8-line shims that source `scripts/lib/resolve_venv.sh`. ONE place to fix bugs, not five.
3. **No `${VAR:-python3}` fallback anywhere.** Bootstrap explicitly probes `python3.13` → `python3.12` → `python3.11`, fail-fasts on miss. Post-bootstrap uses the venv-resident `bin/python` exclusively.
4. **Fail fast when no compatible Python is available.** Bootstrap path keeps its existing FAIL-FAST. Post-bootstrap path (`_resolve-venv.sh` and equivalents) currently does not — fix it via the canonical library.
5. **No silent stderr suppression.** When the SSOT crashes, operators must see the actual error, not a generic "venv not found".
6. **No legacy fallbacks that mask real problems.** The retired pre-v3.7.0 path `untracked/venv/bin/python` (without fingerprint suffix) must not appear as a silent fallback. The canonical resolver REFUSES to emit it.
7. **Defense-in-depth: defer `tomllib` import in `paths.py`.** Even if a future caller invokes `paths.py` with the wrong Python, it must not crash at import time — only when the TOML-parsing function is actually called. Includes the `tomllib.TOMLDecodeError` reference at `paths.py:407`.
8. **Upgrade UX bug from the field report:** `upgrade.sh` doesn't preflight tracked-vs-untracked file collisions (`uv.lock` blocked checkout). Folded in.

## Non-Goals

- **Idle-window daemon death** (field report items #4 and #5). These are pre-existing v3.8.2 issues, not v3.9.0 regressions, and lack log evidence (logs were in-RAM and lost when the process died). Investigation belongs in a separate plan.
- **Compact-event correlation.** Same — separate investigation, no v3.9.x bearing.
- **Auto-detection of `HOOKS_DAEMON_PYTHON` in shell profiles.** Configuration belongs to the operator; we ship a clear error message that tells them what to do.
- **Backward compatibility shim for the legacy path.** The path was retired in v3.7.0; we are explicitly removing the silent fallback to it. Anyone still running pre-v3.7.0 will get a clear error directing them to `/hooks-daemon install`.
- **The "ensure_venv → verify_venv rebuild noise" race that was originally in Phase 4.** Review #1 F6 + Review #2 F11 established that there is no race; the symptom is a side-effect of F8 (the hardcoded-`python3` in `venv_lock_hash_matches`). Once F8 is fixed via the canonical library, the symptom disappears. Phase 4 is **dropped**.

## Context & Background

- Field report: `context/2026-04-30-field-report.md`.
- Review #1 (FATAL): `context/2026-04-30-review-1-opus.md` — F1–F6, A1–A10.
- Review #2 (FATAL, DRY focus): `context/2026-04-30-review-2-opus-dry.md` — F7–F11, A11–A18, Option A architecture.
- Five resolver sites enumerated in Overview above.
- Bootstrap entry points (Layer 1, allowed to PATH-probe): `skills/hooks-daemon/scripts/install.sh:40-89`, `skills/hooks-daemon/scripts/upgrade.sh:86-110`. These ALONE may probe versioned interpreters; everything else uses the canonical post-bootstrap library.
- Already correct (no change to algorithm): `paths.py::resolve_existing_venv_python_with_diagnostics` 5-step precedence — bug is upstream of it (the wrappers call it with the wrong Python).
- Multi-host NFS-shared `untracked/`: hostname is the third dimension of the venv directory (`venv-py{MM}-{fingerprint}-{hostname}` when `HOSTNAME` is set). Documented behaviour, not a corner case.

## Design Decisions

### Decision 1: SSOT = the existing daemon venv

**Context**: Two distinct phases — bootstrap (no venv exists) and post-bootstrap (venv exists). Each has different Python-discovery needs.

**Decision**: Bootstrap (`install.sh`/`upgrade.sh`) keeps its existing FAIL-FAST python-version check against pyproject `requires-python`. Post-bootstrap (every other site) ONLY uses the existing venv — no probing, no fallback.

**Date**: 2026-04-30

### Decision 2: Glob-based venv discovery, with all three dimensions composed first

**Context**: A daemon installation MAY have multiple `venv-py*-{fingerprint}` directories: different Python builds (concurrent containers + host), different hostnames (multi-host NFS-shared `untracked/`).

**Decision** (revised after Review #2 F9): The canonical resolver composes the EXPECTED venv directory from all three dimensions inline (Python version, fingerprint, optional hostname suffix). If the expected dir contains a valid `bin/python`, return it directly — no glob, no Python invocation. Only when the expected dir is missing or broken does the resolver fall back to globbing, and even then it filters by hostname suffix when `HOSTNAME` is set. Two+ matches after filtering trigger SSOT shellout via the FIRST candidate's `bin/python` (after `-x` and `--version` succeed).

**Date**: 2026-04-30 (revised post-Review #2)

### Decision 3: No silent stderr suppression in shell wrappers

**Context**: The current `_resolve-venv.sh` does `... 2>/dev/null` around the SSOT invocation. This single redirection caused the v3.9.0 regression to ship.

**Decision**: Remove the redirect from every site. Diagnostics already capture stderr in their helper output. Operators see the real error.

**Date**: 2026-04-30

### Decision 4: `HOOKS_DAEMON_PYTHON` is bootstrap-only

**Context**: Today the env var is read by every resolver via `${HOOKS_DAEMON_PYTHON:-python3}`. This is wrong on two counts: (a) post-bootstrap there is no need for it (the venv is canonical), (b) it composes with the `:-python3` fallback to create the diceroll Decision 6 forbids.

**Decision**:
- Bootstrap entry points (`skills/hooks-daemon/scripts/install.sh`, `skills/hooks-daemon/scripts/upgrade.sh`) MAY honour `HOOKS_DAEMON_PYTHON` as an explicit operator override — and only when the override interpreter passes `--version` and is `>= 3.11`. Failure = abort with directive.
- Post-bootstrap sites (canonical library + all four shims) IGNORE `HOOKS_DAEMON_PYTHON` entirely. Existence of a venv is sufficient.
- Enforced by static-check QA script (`scripts/qa/check_canonical_callers.sh`, see A14).

**Date**: 2026-04-30

### Decision 5: Canonical bash library at `scripts/lib/resolve_venv.sh`

**Context**: Five duplicated implementations. DRY violation. Bugs only fixable in five places.

**Decision**: One canonical library sourced by all four shell resolver sites and (new) by the bootstrap layer's "is the venv I just built actually usable?" check.

**Public API (sourced):**

```
resolve_venv_python <daemon_dir>
  stdout: absolute path to <daemon_dir>/untracked/venv-*/bin/python
  exit:   0 success
          5 no venv (caller emits install directive)
          6 corrupt source (paths.py missing — caller emits reinstall directive)
          7 ambiguous (>1 match after hostname filter, but tiebreak shellout failed)

resolve_venv_dir <daemon_dir>
  stdout: absolute path to <daemon_dir>/untracked/venv-*
  exits: same as resolve_venv_python
```

**Constraints**:
- NEVER returns the legacy unversioned path `<daemon_dir>/untracked/venv` — function refuses to emit it even if the directory exists.
- Sources `scripts/lib/python_fingerprint.sh` from a stable path that works in both deploy locations (repo source + skill bundle).
- Preserves the fingerprint cache `untracked/.python-cmd-cache` that `init.sh::_resolve_python_cmd` writes today.
- Source-path resolution is robust under `set -euo pipefail` and works whether the file is in `${PROJECT_ROOT}/scripts/lib/` (repo source) or `${DAEMON_DIR}/scripts/lib/` (skill bundle).

**Algorithm (post-bootstrap fast path):**

```
1. Compose expected_dir = "${DAEMON_DIR}/untracked/venv-py${PY_VERSION}-${FINGERPRINT}${HOSTNAME_SUFFIX}"
2. If "${expected_dir}/bin/python" exists, is executable, and `--version` succeeds → return it.
3. Glob "${DAEMON_DIR}/untracked/venv-py*/bin/python", filter by hostname suffix if HOSTNAME set.
4. Exactly one match + executable + --version succeeds → return it.
5. Two+ matches → use FIRST candidate's bin/python (after -x and --version verified) to invoke
   `paths.py resolve-venv` for canonical disambiguation.
6. Zero matches → exit 5.
```

**Date**: 2026-04-30 (introduced post-Review #2)

### Decision 6: Never `${VAR:-python3}`. Explicit version probe in bootstrap, venv-only post-bootstrap.

**Context**: User instruction: *"we shoudl never be doing :- fallback to python3 which is total diceroll"*. The `${HOOKS_DAEMON_PYTHON:-python3}` pattern is the disease — every fallback to bare `python3` is a diceroll on whatever the OS package manager happens to install. On RHEL/CentOS/Debian-stable that's Python 3.9. On macOS it can be Python 3.7. None of these can run the daemon.

**Decision**:

| Context | Rule |
|---|---|
| Bootstrap (no venv yet) | Explicitly probe in order: `python3.13`, `python3.12`, `python3.11`. Honour `HOOKS_DAEMON_PYTHON` if set AND `>= 3.11` (Decision 4). None found = FAIL FAST with directive listing the three versioned commands. **No bare `python3` invocation.** |
| Post-bootstrap (venv exists) | Use venv `bin/python` exclusively, via the canonical library. **No env-var fallback.** **No bare `python3`.** |

**Implications**:
- `skills/hooks-daemon/scripts/install.sh:40-89` (FAIL-FAST template) currently includes a `python3` step in its probe list. This step is REMOVED — replaced with a hard-fail when none of `3.13/3.12/3.11` is present.
- Same change in `skills/hooks-daemon/scripts/upgrade.sh:86-110` (`find_compatible_python`).
- Static-check `scripts/qa/check_canonical_callers.sh` greps the entire repo for `${[A-Z_]*:-python3}` patterns and fails CI if any are found outside the explicitly-allowed bootstrap probe block.

**Date**: 2026-04-30 (per user instruction)

## Tasks

### Phase 1: Opus review gate (BLOCKING — no implementation until cleared)

- [ ] ⬜ **Task 1.1**: Spawn Opus 4.6 sub-agent (review #3) with: this PLAN.md (post-amendment), both prior reviews, the field report, the five affected files. Brief: "find every way this plan, as amended, still adds problems".
- [ ] ⬜ **Task 1.2**: Address all FATAL/RISKY findings from review #3 before any code is written. Update PLAN.md with rationale for any rejected suggestions.
- [ ] ⬜ **Task 1.3**: Mark Phase 1 complete only when reviewer explicitly signs off in writing. Two prior FATAL verdicts; this third pass is the contract.

### Phase 2: Defense-in-depth FIRST — `paths.py` deferred imports (was old Phase 5, promoted)

Reviewer Review #1 F2 established that the `tomllib` import-time crash is load-bearing for the multi-venv branch of Decision 2. Promote this from defense-in-depth to primary, and land it BEFORE the resolver rewrite so the canonical library can rely on `paths.py` being import-safe under any 3.11+ interpreter (and silently functional even if mistakenly invoked under 3.10).

- [ ] ⬜ **Task 2.1**: Failing test — `tests/unit/daemon/test_paths_import_under_310.py::test_paths_imports_under_python_310`. Mechanism: `subprocess` spawn with a controlled `PYTHONPATH` and a stub `tomllib` set to `None` via `unittest.mock.patch.dict(sys.modules, {'tomllib': None}); importlib.reload(paths)`. Skip-if-unavailable falls back to a Docker `python:3.10-slim` integration test in Phase 5.
- [ ] ⬜ **Task 2.2**: Move `import tomllib` from `paths.py:22` (module top) into the function(s) that consume it. Defer `tomllib.TOMLDecodeError` reference at `paths.py:407` accordingly (use a runtime-imported alias or guard the except clause).
- [ ] ⬜ **Task 2.3**: Failing test — `paths.py resolve-venv` subcommand still works under Python 3.11/3.12/3.13 (CI default). Regression-guard the deferral.
- [ ] ⬜ **Task 2.4**: Confirm full `pytest tests/unit/daemon/` passes. No other paths.py tests should regress.

### Phase 3: TDD — failing tests for the canonical contract and all five sites

- [ ] ⬜ **Task 3.1a**: Replace `TestLegacyFallback::test_no_venv_returns_legacy_path` with `test_no_venv_exits_nonzero_with_install_directive` — non-zero exit, stderr contains directive ("No daemon venv found … Run /hooks-daemon install").
- [ ] ⬜ **Task 3.1b**: Replace `TestLegacyFallback::test_missing_paths_py_returns_legacy_path` with `test_missing_paths_py_exits_nonzero_with_reinstall_directive` — DIFFERENT error class than no-venv. Stderr: "daemon source corrupt: paths.py missing at $DAEMON_DIR/... — Run /hooks-daemon upgrade --force".
- [ ] ⬜ **Task 3.2**: `test_resolver_never_falls_back_to_retired_legacy_path` — explicit guard that `<daemon_dir>/untracked/venv/bin/python` (without fingerprint suffix) NEVER appears as resolver output, even if that directory exists.
- [ ] ⬜ **Task 3.3**: `test_resolver_does_not_silence_python_errors` — when SSOT crashes (inject a `paths.py` that raises at import), stderr surfaces the underlying error verbatim.
- [ ] ⬜ **Task 3.4**: `test_resolver_uses_existing_venv_python_for_ssot_invocation` — when multiple venvs exist, the SSOT is invoked using one of THEIR `bin/python` interpreters, never with PATH-discovered `python3`.
- [ ] ⬜ **Task 3.5**: `test_resolver_fails_fast_when_glob_matches_zero_venvs` — non-zero exit immediately, no Python invoked at all.
- [ ] ⬜ **Task 3.6**: `test_resolver_handles_broken_venv_symlink` — venv exists, `bin/python` is a broken symlink (interpreter removed). Resolver must verify with `-x` AND `--version` before using a candidate as SSOT shellout interpreter; falls back to next candidate or exits 5.
- [ ] ⬜ **Task 3.7**: `test_resolver_silent_on_stderr_when_resolution_succeeds` — happy-path invocation produces no stderr noise (so `health-check.sh` and `daemon-cli.sh status` stay quiet).
- [ ] ⬜ **Task 3.8**: `test_resolver_silent_on_stdout_when_resolution_succeeds` — single line of output (the path), nothing else.
- [ ] ⬜ **Task 3.9**: `test_resolver_under_set_euo_pipefail` — sourcing the canonical library under `set -euo pipefail` does not abort the parent shell on a benign no-match condition; only `exit` paths terminate, and they emit a clear stderr message first.
- [ ] ⬜ **Task 3.10**: `test_resolver_composes_expected_dir_from_all_three_dimensions` — multi-host NFS fixture with two venvs (different hostnames). With `HOSTNAME=A`, resolver returns A's venv. Without `HOSTNAME`, the no-suffix form is used.
- [ ] ⬜ **Task 3.11**: Parity-matrix integration test `tests/integration/test_venv_resolver_parity.py` — invokes resolution from all four shell sites against the same fixture; asserts identical stdout. Fails today (since they all have separate copies); after Phase 4 they all delegate to the canonical library and outputs match by construction.
- [ ] ⬜ **Task 3.12**: Bootstrap probe test `tests/integration/test_bootstrap_explicit_probe.py` — `install.sh`/`upgrade.sh` find `python3.13`/`python3.12`/`python3.11` when present, fail-fast with directive when ALL absent (even if `python3` resolves to 3.9 on PATH). Specifically asserts: a host with only `/usr/bin/python3 → 3.9` and no versioned interpreters exits non-zero with stderr listing all three versioned commands.
- [ ] ⬜ **Task 3.13**: Static-check failing test `tests/unit/qa/test_check_canonical_callers.py` — runs `scripts/qa/check_canonical_callers.sh` against the current tree, expects FAIL (because the four sites still contain `${HOOKS_DAEMON_PYTHON:-python3}`). After Phase 4 it expects PASS.
- [ ] ⬜ **Task 3.14**: Run all Phase 3 tests — verify all expected failures fire.

### Phase 4: Implementation — canonical library + four shims + hardcoded-`python3` fix

- [ ] ⬜ **Task 4.1**: Create `scripts/lib/resolve_venv.sh` per Decision 5. Public API as specified, algorithm as specified. Source-path resolution robust under both deploy locations.
- [ ] ⬜ **Task 4.2**: Reduce `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` to a 3–8-line shim that sources the canonical and calls `resolve_venv_python`. Remove `2>/dev/null`. Remove every `${HOOKS_DAEMON_PYTHON:-python3}`.
- [ ] ⬜ **Task 4.3**: Reduce `scripts/venv-include.bash::_resolve_venv_dir` to a shim. Same removals.
- [ ] ⬜ **Task 4.4**: DELETE `scripts/install/venv_resolver.sh` entirely. Update its callers (`upgrade_version.sh:44, 86`) to source `scripts/lib/resolve_venv.sh` directly.
- [ ] ⬜ **Task 4.5**: Reduce `init.sh::_resolve_python_cmd` (`init.sh:244-292`) to a shim that sources the canonical. Preserve the `untracked/.python-cmd-cache` write at the canonical level (move the cache logic into the canonical so all callers benefit).
- [ ] ⬜ **Task 4.6**: Fix `scripts/install/venv.sh:261` (`venv_lock_hash_matches`) — replace literal `python3` with `$(resolve_venv_python "$DAEMON_DIR")`. Adds the dependency on Phase 2 (deferred tomllib) being landed first, since this caller is on the upgrade path.
- [ ] ⬜ **Task 4.7**: Replace `${HOOKS_DAEMON_PYTHON:-python3}` in bootstrap layers (`skills/hooks-daemon/scripts/install.sh:40-89`, `skills/hooks-daemon/scripts/upgrade.sh:86-110`) with the explicit `python3.13` → `python3.12` → `python3.11` probe per Decision 6. Honour `HOOKS_DAEMON_PYTHON` only when it points to a `>= 3.11` interpreter (verified via `--version`).
- [ ] ⬜ **Task 4.8**: Ship `scripts/lib/resolve_venv.sh` AND `scripts/lib/python_fingerprint.sh` in the skill bundle. Verify `install.py` deploys them BEFORE making wrappers executable (Review #2 F10 — install-deploy ordering).
- [ ] ⬜ **Task 4.9**: Add `scripts/qa/check_canonical_callers.sh`:
  - Greps the entire repo for `${[A-Z_]*:-python3}` and fails if any match outside the bootstrap probe block.
  - Greps for raw `python3 .*paths\.py` and fails if any match outside Layer-1 entry points.
  - Greps the canonical library for `legacy` / `untracked/venv/` and fails if it can ever emit the unversioned legacy path.
  - Greps post-bootstrap sources for `HOOKS_DAEMON_PYTHON` (allowed only in `install.sh`/`upgrade.sh` bootstrap blocks).
- [ ] ⬜ **Task 4.10**: Wire `check_canonical_callers.sh` into `scripts/qa/run_all.sh` (becomes the 11th QA check).
- [ ] ⬜ **Task 4.11**: Verify all Phase 3 tests now pass. Run full `pytest tests/` — verify no regressions.

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Full QA suite — `./scripts/qa/run_all.sh` — all 11 checks pass (10 existing + new canonical-callers check).
- [ ] ⬜ **Task 5.2**: Daemon restart — verify RUNNING after all changes.
- [ ] ⬜ **Task 5.3**: Live diagnostic test — invoke `health-check.sh` and `daemon-cli.sh status` from project root, verify clean output (zero stderr noise on the happy path; clear actionable errors on the fail-fast paths).
- [ ] ⬜ **Task 5.4**: Reproduce the field bug deterministically. Choose one mechanism and lock it: (a) Docker `python:3.9-slim` container with the daemon mounted in (preferred — most realistic), or (b) `/tmp/fake-python3` shim that pretends to be 3.9 and is first on PATH. Verify (i) bootstrap fails-fast with the explicit-probe directive; (ii) post-bootstrap diagnostics succeed via the venv with no Python-version awareness needed at the wrapper layer.
- [ ] ⬜ **Task 5.5**: `upgrade.sh` UX preflight (folded in from old Phase 4): when an untracked file would be clobbered by `git checkout v<target>`, surface a clear error before running checkout. Failing test + implementation using `git ls-files --others --exclude-standard` filtered against target ref's tracked files.

### Phase 6: Release — `/release patch` for v3.9.1

- [ ] ⬜ **Task 6.1**: Run `/release patch` skill end-to-end. All 15 release pipeline steps must pass.
- [ ] ⬜ **Task 6.2**: Acceptance gate covers diagnostic-script invocation paths in particular (the v3.9.0 regression escaped because acceptance focused on hook dispatch). At minimum: `health-check.sh`, `daemon-cli.sh status`, `init-handlers.sh`, `validate_worktrees.sh`, `setup_worktree.sh`, `debug_hooks.sh` — all of which source the canonical via `init.sh` or `venv-include.bash`.
- [ ] ⬜ **Task 6.3**: Acceptance test on a Python-3.9 host (or simulated equivalent from Phase 5 Task 5.4). Bootstrap MUST fail-fast with the explicit-probe directive; if a venv already exists, post-bootstrap diagnostics MUST succeed.
- [ ] ⬜ **Task 6.4**: Release notes — explicit transparency about the v3.9.0 regression and the acceptance-test blind spot it revealed. Document the new acceptance-test coverage requirement: every release must include a Python-version-mismatch case for diagnostic scripts.
- [ ] ⬜ **Task 6.5**: Verify release published, tag pushed, GitHub release marked latest.

## Dependencies

- **Depends on**: v3.9.0 already released (yes, complete).
- **Blocks**: Any work that touches `_resolve-venv.sh`, `venv-include.bash`, `venv_resolver.sh`, `init.sh::_resolve_python_cmd`, `scripts/install/venv.sh`, `paths.py`, or the bootstrap path.
- **Related**: Plan 00100 (venv SSOT — this plan refines its shell-wrapper layer with the DRY library). Plan 00101 (single-process daemon enforcement — orthogonal).

## Success Criteria

- [ ] On a host with default `python3` = 3.9 BUT `python3.11`/`3.12`/`3.13` available: bootstrap (`install.sh`/`upgrade.sh`) succeeds via explicit probe.
- [ ] On a host with default `python3` = 3.9 AND no versioned `python3.11+` available: bootstrap exits non-zero with directive listing the three versioned commands. No silent `:-python3` fallback occurs.
- [ ] On a host where the daemon venv exists: every diagnostic script (`health-check.sh`, `daemon-cli.sh status`, `init-handlers.sh`, etc.) succeeds regardless of the system `python3` version. The wrapper layer never needs to invoke a system Python.
- [ ] On a host with no daemon venv at all: every diagnostic script exits non-zero with a clear stderr message directing the operator to `/hooks-daemon install`.
- [ ] No `2>/dev/null` redirections around SSOT invocations remain in any shell wrapper.
- [ ] No `${[A-Z_]*:-python3}` patterns remain anywhere in the repository (verified by `check_canonical_callers.sh`).
- [ ] Single canonical library `scripts/lib/resolve_venv.sh` exists; the four shell sites are 3–8-line shims; `scripts/install/venv_resolver.sh` is deleted.
- [ ] `paths.py` imports cleanly under Python 3.10 (deferred-tomllib regression test).
- [ ] All existing tests pass; the 2 broken-behaviour-asserting tests are split into 4 (no-venv vs missing-paths.py); 14 new tests cover the fail-fast / DRY / parity contracts.
- [ ] `upgrade.sh` produces a clear error before checkout when untracked files would collide with target ref.
- [ ] `scripts/qa/check_canonical_callers.sh` is wired into `run_all.sh` and passes.
- [ ] v3.9.1 released via `/release patch` with all 15 gates green.

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
| --- | --- | --- | --- |
| Removing the silent legacy fallback breaks pre-v3.7.0 installs | Medium | Low | v3.7.0 retired the legacy path; Plan 00100 added eager cleanup. No supported install can still be on it. Release notes for v3.9.1 explicitly call this out. |
| Glob-based discovery picks the "wrong" venv when multiple exist on a multi-Python host | Medium | Low | Decision 2 composes expected dir from all three dimensions inline; glob is fallback only; tiebreak via venv-resident Python invocation of `paths.py`. Test 3.10 covers the multi-host hostname case explicitly. |
| Phase 5.5 `upgrade.sh` preflight has subtle false-positives | Medium | Medium | Scope to *tracked-in-target-ref AND untracked-in-current-state* — the precise collision class. Tests include false-positive negatives (e.g. local `untracked/.gitignore` modification carrying over). |
| Test for "deferred tomllib import" is hard to write portably (CI runs 3.13) | High | High | **Promoted from Low/High after Review #1 F2.** Two-mechanism approach: `unittest.mock.patch.dict(sys.modules, {'tomllib': None}) + importlib.reload` for unit; Docker `python:3.10-slim` for integration in Phase 5.4. The "skip if neither works" mitigation is REJECTED — the test must pass. |
| Stripping `${HOOKS_DAEMON_PYTHON:-python3}` from bootstrap removes a documented operator override | Medium | Low | Decision 4: bootstrap STILL honours `HOOKS_DAEMON_PYTHON` when it points to a `>= 3.11` interpreter. We only strip the silent `python3` fallback, not the explicit override. |
| Skill-bundle deploy ordering: canonical library not present when wrappers fire | High | Medium | Review #2 F10. Phase 4 Task 4.8 verifies install order; Task 5.3 contract test simulates partial-deploy failure mode and asserts wrappers fail LOUDLY (exit 6, "daemon source corrupt"). |
| Static-check `check_canonical_callers.sh` produces false-positives in vendored code | Low | Medium | Scope to repo source paths; exclude `vendor/`, `node_modules/`, `untracked/`, and the test fixture directory. Allowlist the bootstrap probe block by exact line-anchor match. |
| Self-install dogfooding: developer's own venv breaks while applying this plan | High | Medium | This repo IS a self-install. Document recovery in PR body: keep the existing venv working until Phase 4 Task 4.5 lands, validate `init.sh` shim against the live daemon before commit. Revert plan: `git revert` any commit that breaks `daemon-cli.sh status`. |
| Opus review #3 surfaces a fundamental design objection | High | Low | Two reviews already amended this plan; the contract is now explicit. If review #3 returns FATAL, the plan needs structural rewrite, not patches — escalate to user. |

## Notes & Updates

### 2026-04-30 — Plan created

- Field report received from downstream user during their session at /srv/example-app/checkout (snapshot in `context/2026-04-30-field-report.md`).
- User explicit direction: "if we don't have python 3.11 available we need to fail fast and clear. We absolutely need to be using a single python version all the time — there should be a single source of truth for the correct python version."
- User reaction to silent `2>/dev/null` redirect: "fuck me i hate shit like this." Endorses removal.

### 2026-04-30 — Review #1 FATAL (Opus 4.6 hostile)

- F1–F6 fatal, R1–R10 risky, A1–A10 amendments. Three bug-equivalent files identified beyond the original target. Phase 4 misdiagnoses the field report (no race condition).

### 2026-04-30 — User feedback on Review #1: DRY?

- User: *"F1 - so SSOT is failing by not having a single source of truth for how to load python? seems like we need DRY?"* Triggered review #2 with explicit DRY focus.

### 2026-04-30 — Review #2 FATAL (Opus 4.6, DRY focus)

- F7–F11, R11–R16, A11–A18. Two more sites identified (`init.sh::_resolve_python_cmd` hot path, `venv.sh:261` hardcoded `python3`). Option A architecture: single canonical bash library at `scripts/lib/resolve_venv.sh`, all five sites collapse to shims.

### 2026-04-30 — User feedback on Review #2: never `:-python3`

- User: *"we shoudl never be doing :- fallback to python3 which is total diceroll."* Triggered Decision 6: explicit `python3.13`/`python3.12`/`python3.11` probe in bootstrap, venv-only post-bootstrap, static-check enforcement.

### 2026-04-30 — Plan amended (this version)

- Phase order rearranged: Phase 2 (deferred tomllib) now lands BEFORE Phase 3 (TDD) and Phase 4 (resolver rewrite), per Review #1 A2.
- Old Phase 4 (`upgrade.sh` race) DROPPED per Review #2 A17. Its surviving Task 4.1/4.2 (preflight collision) folded into Phase 5 Task 5.5.
- Decisions 4, 5, 6 added.
- Phase 1 task 1.1 now references review #3 (post-amendment validation).
