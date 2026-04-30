# Plan 00103: v3.9.1 — venv resolution fail-fast (narrow hotfix)

**Status**: Not Started — narrowed scope after three FATAL reviews of the ambitious version (`PLAN-v1-ambitious-superseded.md`)
**Created**: 2026-04-30
**Owner**: Claude (Opus 4.7)
**Priority**: High (regression patch — ships in days, not weeks)
**Recommended Executor**: Sonnet 4.5 (Sub-Agent Orchestration)
**Execution Strategy**: Sequential commits per Phase, daemon-restart verification between commits

## Why this plan was narrowed

The v1 plan attempted to combine the v3.9.1 patch fix with a DRY consolidation (single canonical bash library). Three consecutive FATAL Opus reviews demonstrated that bundling "patch release" with "structural refactor" is the proximate cause of every fatal finding (deletion-undercount, wrong-file-path, bracketing of `python3` semantics, no commit-ordering, low-fidelity acceptance fixture, etc.).

This plan is **strictly the patch**. The DRY consolidation is in Plan 00104 (`v3.10.0-venv-resolver-dry-consolidation`) and ships separately on a slower cadence.

The narrowed scope eliminates the FATAL findings as follows:

- F12 (9 callers, not 2) → N/A: we don't delete `venv_resolver.sh`.
- F13 (`init.sh` location) → corrected: file is at repo root `/workspace/init.sh`.
- F14 (probe-list vs `:-python3`) → split into two distinct rules; open-ended probe via `compgen` (no Python-version ceiling).
- F15 (commit ordering) → explicit commit-by-commit sequence in Phase 6.
- F16 (acceptance fidelity) → two distinct fixtures: bootstrap-fail and post-bootstrap-regression.
- F17 (exit vs return) → N/A: per-site fixes use the existing per-site exit-code conventions.
- F18 (static-check allowlist) → static check moved to Plan 00104.
- R20 (TOMLDecodeError deferral) → local-import helper function.

## Overview

A field bug report (`context/2026-04-30-field-report.md`) surfaced a v3.9.0 regression that breaks every diagnostic helper script (`health-check.sh`, `daemon-cli.sh status`, etc.) on hosts where the system default `python3` is older than 3.11 — even when a compatible Python (3.11/3.12/3.13) exists at a versioned path and the daemon process itself is running healthily on it.

Root cause: `paths.py:22 import tomllib` is at module top. On hosts where `python3 → 3.9`, every wrapper that invokes `python3 paths.py resolve-venv ...` crashes at module load. The `2>/dev/null` redirect plus a silent fallback to the retired-in-v3.7.0 `untracked/venv/bin/python` path hides the crash and produces a generic "venv not found" error.

The bug exists at five sites: `_resolve-venv.sh` (skill bundle), `venv-include.bash`, `scripts/install/venv_resolver.sh`, `init.sh::_resolve_python_cmd`, and `scripts/install/venv.sh:261::venv_lock_hash_matches`.

## Goals

1. **Make `paths.py resolve-venv` work under any Python 3.x.** The subcommand only needs filesystem glob — it does not need `tomllib`. Defer the import so module-load succeeds on 3.9/3.10. Subcommands that genuinely need `tomllib` (e.g. `check-venv-fresh`) raise a clear error instead of silent module-load crash.
2. **Fail loudly when resolution actually fails.** Remove `2>/dev/null` redirects around SSOT invocations at all five sites. Remove silent fallback to the retired legacy `untracked/venv/bin/python` path.
3. **Bootstrap probes versioned interpreters explicitly.** Per user instruction (*"we should never be doing :- fallback to python3 which is total diceroll"*), `install.sh` and `upgrade.sh` no longer accept bare `python3` as a candidate. They probe explicit versioned commands (`python3.13`, `python3.12`, `python3.11`) AND any future `python3.NN` discovered via `compgen` for `NN >= 11`. Operator override `HOOKS_DAEMON_PYTHON` is honoured only when the override interpreter passes `--version` and is `>= 3.11`.
4. **Acceptance fidelity.** Reproduce the field bug deterministically with a fixture that has BOTH `python3 → 3.9` AND `python3.13` co-resident, with a venv pre-built against 3.13. Verify diagnostic scripts succeed via the venv on the post-bootstrap path.

## Non-Goals

- **DRY consolidation into a single canonical bash library.** That is Plan 00104. Each site retains its own resolution logic; this patch fixes each in place.
- **`init.sh::_resolve_python_cmd` hot-path optimisation.** Touched only enough to remove the `:-python3` diceroll and the `2>/dev/null` redirect. Source-cost optimisation moves to 00104.
- **Static-check QA gate (`check_canonical_callers.sh`).** Plan 00104.
- **Multi-host NFS hostname dimension fail-fast.** Plan 00104 (R22 from review #3).
- **`requires-python` cross-check on probed interpreters.** Plan 00104 (R23).
- **Idle-window daemon death** (field report items #4 and #5). Pre-existing v3.8.2 issue, separate plan.
- **Compact-event correlation.** Same — separate investigation.

## Context & Background

- Field report: `context/2026-04-30-field-report.md`.
- Three prior reviews of v1 (ambitious) plan: `context/2026-04-30-review-1-opus.md`, `context/2026-04-30-review-2-opus-dry.md`, `context/2026-04-30-review-3-opus.md`. Review #3 verdict triggered this narrowed rewrite.
- Five resolver sites:
  - `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` (lines ~36-44)
  - `scripts/venv-include.bash` (lines ~35-54)
  - `scripts/install/venv_resolver.sh` (lines ~26-43)
  - `/workspace/init.sh` lines 244-292 (`_resolve_python_cmd`) — repo root, NOT skill bundle
  - `scripts/install/venv.sh` line 261 (`venv_lock_hash_matches`)
- Bootstrap entry points: `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh` lines 40-89, `.../upgrade.sh` lines 86-110.
- Affected paths.py module: `src/claude_code_hooks_daemon/daemon/paths.py` (line 22 `import tomllib`, lines 406-407 `tomllib.loads`/`tomllib.TOMLDecodeError`, lines 1233-1263 `_cli_resolve_venv`).

## Design Decisions

### Decision 1: Defer `tomllib` import in `paths.py`

**Context**: `import tomllib` at module top crashes on Python \<3.11. The `resolve-venv` subcommand does not need `tomllib`; only TOML-parsing functions do.

**Decision**: Move the import inside the function(s) that consume it. Use a local-import helper for the `except` clause to keep narrow exception-typing without leaking `tomllib` into the module namespace.

```python
# Before: paths.py:22
import tomllib  # noqa
...
# Before: paths.py:406-407
except tomllib.TOMLDecodeError as e:
    ...

# After:
def _load_toml_or_raise(path: Path) -> dict:
    import tomllib
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML in {path}: {e}") from e
```

**Result**: `paths.py resolve-venv` runs under any Python 3.x. `paths.py check-venv-fresh` raises a clear `ValueError` (or fails-fast with stderr message) when called under \<3.11 — no silent module-load crash.

**Date**: 2026-04-30

### Decision 2: Remove silent stderr suppression and silent legacy fallback at the 5 sites

**Context**: Each of the 5 sites uses `... 2>/dev/null && ... || legacy_path`. When the SSOT crashes, the crash is hidden and resolution silently falls through to a path that no longer exists. Operators see "venv not found" instead of the real `ModuleNotFoundError`.

**Decision**: At each site:

1. Remove `2>/dev/null`. Stderr passes through.
2. Remove the legacy `untracked/venv/bin/python` (no fingerprint suffix) fallback. If glob+SSOT both fail, exit non-zero with a clear directive.
3. Keep each site's existing function/exit-code convention (this is per-site fix, not unification — that is Plan 00104).

**Date**: 2026-04-30

### Decision 3: `HOOKS_DAEMON_PYTHON` is bootstrap-only override; bootstrap probes versioned commands explicitly with no `python3` candidate

**Context**: User: *"we should never be doing `:-python3` fallback which is total diceroll."* The pattern `${HOOKS_DAEMON_PYTHON:-python3}` substitutes literal `python3` when the var is unset; on RHEL/CentOS that's 3.9.

**Decision**: Two distinct rules, applied separately:

| Rule                           | Applies to                                  | Spec                                                                              |
| ------------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------- |
| **A: parameter-expansion ban** | All 5 resolver sites + bootstrap            | No `${[A-Z_]*:-python3}` patterns. Substitute fail-fast logic when env var unset. |
| **B: probe-list ban**          | Bootstrap only (`install.sh`, `upgrade.sh`) | No bare `python3` in candidate-command lists. Probe explicit versioned commands.  |

**Probe sequence** (open-ended, no Python-version ceiling — addresses F14 from review #3):

```bash
# Honour HOOKS_DAEMON_PYTHON override first, validate >= 3.11.
if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
    if ! _is_python_at_least_311 "$HOOKS_DAEMON_PYTHON"; then
        echo "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON is not Python 3.11+ — abort." >&2
        exit 1
    fi
    PYTHON_CMD="$HOOKS_DAEMON_PYTHON"
else
    # Probe explicit versioned commands first, then any python3.NN >= 11
    candidates=("python3.13" "python3.12" "python3.11")
    while read -r extra; do
        case "$extra" in
            python3.[0-9]*) candidates+=("$extra") ;;
        esac
    done < <(compgen -c python3. | sort -u)
    PYTHON_CMD=""
    for cand in "${candidates[@]}"; do
        if command -v "$cand" > /dev/null 2>&1 && _is_python_at_least_311 "$cand"; then
            PYTHON_CMD="$cand"
            break
        fi
    done
    if [ -z "$PYTHON_CMD" ]; then
        echo "No compatible Python (>=3.11) found. Tried: ${candidates[*]}" >&2
        echo "Install python3.11+ or set HOOKS_DAEMON_PYTHON to an absolute path." >&2
        exit 1
    fi
fi
```

`_is_python_at_least_311` parses `--version` output and asserts MAJOR=3 AND MINOR>=11.

**Date**: 2026-04-30

## Tasks

### Phase 1: TDD — failing tests for the patch contract

- [ ] ⬜ **Task 1.1**: `tests/unit/daemon/test_paths_import_under_310.py::test_paths_imports_when_tomllib_unavailable`. Mechanism: `unittest.mock.patch.dict(sys.modules, {'tomllib': None}); importlib.reload(paths)`. Asserts no ImportError at module load, `_cli_resolve_venv` callable. Skip-if-mechanism-unavailable falls back to subprocess invocation under `python3.10` if installed in CI; otherwise xfail with reason captured.
- [ ] ⬜ **Task 1.2**: `tests/unit/daemon/test_paths_resolve_venv_under_any_python.py::test_resolve_venv_works_without_tomllib`. Subprocess-invokes `paths.py resolve-venv $tmpdir` with a fixture daemon_dir containing one venv. Asserts stdout=path-to-bin/python, exit=0, even when tomllib is monkeypatched out.
- [ ] ⬜ **Task 1.3**: `tests/unit/daemon/test_paths_check_venv_fresh_under_310.py::test_check_venv_fresh_raises_clear_error_under_310`. Asserts `paths.py check-venv-fresh` exits non-zero with stderr message "Python 3.11+ required for lockfile parsing" (or similar) — NOT a silent ModuleNotFoundError.
- [ ] ⬜ **Task 1.4**: `tests/integration/test_skill_scripts_venv_resolution.py` — flip the two `TestLegacyFallback` assertions and split into 4 tests:
  - `test_no_venv_exits_nonzero_with_install_directive` (was: returns legacy)
  - `test_missing_paths_py_exits_nonzero_with_reinstall_directive` (was: returns legacy; different stderr message)
  - `test_resolver_does_not_silence_python_errors` (new — stderr surfaces underlying crash)
  - `test_resolver_never_emits_unversioned_legacy_path` (new — explicit guard)
- [ ] ⬜ **Task 1.5**: `tests/integration/test_bootstrap_explicit_probe.py`:
  - `test_bootstrap_probes_versioned_commands_first` — fixture host with `python3 → 3.9`, `python3.13` → bootstrap picks `python3.13`.
  - `test_bootstrap_probes_open_ended_for_future_versions` — fixture host with only `python3.14` (no `3.13/3.12/3.11`) → bootstrap picks `python3.14` via `compgen` discovery.
  - `test_bootstrap_fails_fast_when_no_compatible_python` — fixture with only `python3 → 3.9` → exits non-zero with directive listing tried commands.
  - `test_bootstrap_honours_explicit_override` — `HOOKS_DAEMON_PYTHON=/abs/python3.12` → bootstrap uses it without probing.
  - `test_bootstrap_rejects_invalid_override` — `HOOKS_DAEMON_PYTHON` pointing at `python3.9` → exits non-zero before any probe runs.
- [ ] ⬜ **Task 1.6**: Run all Phase 1 tests — verify all expected failures fire.

### Phase 2: `paths.py` — defer `tomllib`

- [ ] ⬜ **Task 2.1**: Move `import tomllib` from `paths.py:22` into helper function(s).
- [ ] ⬜ **Task 2.2**: Refactor the `except tomllib.TOMLDecodeError` clause at `paths.py:407` via the local-import helper pattern (Decision 1). Narrow exception type preserved.
- [ ] ⬜ **Task 2.3**: `_cli_resolve_venv` (paths.py:1233-1263) verified to not require tomllib at import or call time.
- [ ] ⬜ **Task 2.4**: Verify Phase 1 Tasks 1.1, 1.2, 1.3 now pass.
- [ ] ⬜ **Task 2.5**: Full `pytest tests/unit/daemon/` passes — no other paths.py tests regress.

### Phase 3: 5-site cleanup — remove `2>/dev/null` and silent legacy fallback

Each site is a small independent edit. No common library — that is Plan 00104.

- [ ] ⬜ **Task 3.1**: `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` (lines ~36-44):
  - Remove `2>/dev/null`.
  - Replace `${HOOKS_DAEMON_PYTHON:-python3}` with logic that: prefers a venv-resident `bin/python` discovered via glob; if zero matches, exits 5 with stderr directive; if multiple, uses the FIRST match's `bin/python` to invoke `paths.py resolve-venv`.
  - Remove silent fallback to `${PROJECT_ROOT}/untracked/venv/bin/python`.
  - Verify `-x` and `--version` succeed before using a candidate (handles broken symlink).
- [ ] ⬜ **Task 3.2**: `scripts/venv-include.bash::_resolve_venv_dir`: same pattern as 3.1.
- [ ] ⬜ **Task 3.3**: `scripts/install/venv_resolver.sh::resolve_existing_venv_python`: same pattern as 3.1.
- [ ] ⬜ **Task 3.4**: `/workspace/init.sh::_resolve_python_cmd` (lines 244-292):
  - Same `2>/dev/null` removal and `:-python3` replacement.
  - Preserve the existing `untracked/.python-cmd-cache` write at the same call site (no behaviour change to caching).
  - Source `python_fingerprint.sh` from its current location (`scripts/install/python_fingerprint.sh`); do not relocate.
- [ ] ⬜ **Task 3.5**: `scripts/install/venv.sh:261` (`venv_lock_hash_matches`):
  - Replace literal `python3` with the venv's own `bin/python` (resolved by reusing the existing local resolver in `venv_resolver.sh`).
  - This caller runs on the upgrade path with a venv already present; reuse — don't probe.
- [ ] ⬜ **Task 3.6**: Verify Phase 1 Task 1.4 (4 split assertions) now passes.

### Phase 4: Bootstrap explicit probe — `install.sh` and `upgrade.sh`

- [ ] ⬜ **Task 4.1**: Add helper `_is_python_at_least_311` (parses `--version` output, asserts `MAJOR == 3 && MINOR >= 11`) to both `install.sh` and `upgrade.sh`. Acceptable to duplicate — DRY in Plan 00104.
- [ ] ⬜ **Task 4.2**: Replace `${HOOKS_DAEMON_PYTHON:-python3}` and the `python3` candidate in `install.sh:40-89` with the Decision 3 probe block.
- [ ] ⬜ **Task 4.3**: Same in `upgrade.sh:86-110` (`find_compatible_python`).
- [ ] ⬜ **Task 4.4**: Verify Phase 1 Task 1.5 (5 bootstrap-probe assertions) now passes.

### Phase 5: Acceptance fidelity — multi-Python fixture

- [ ] ⬜ **Task 5.1**: Author Docker fixture `tests/integration/fixtures/multi-python.Dockerfile`. Base: `python:3.13-slim`. Add `apt-get install python3.9` (or use Fedora multi-Python image). Result: `python3 → 3.9` on PATH AND `python3.13` available as a versioned command.
- [ ] ⬜ **Task 5.2**: Author `tests/acceptance/test_v391_field_regression.py`:
  - **Bootstrap-fail fixture**: `python:3.9-slim` (single-Python) → bootstrap exits non-zero with directive.
  - **Post-bootstrap-regression fixture**: multi-python container, daemon pre-bootstrapped against 3.13, venv exists. Run `health-check.sh`, `daemon-cli.sh status`, `init-handlers.sh` from project root. Assert exit 0, no stderr noise, no fallthrough to legacy path. This is the actual field-bug regression test (per F16 from review #3).
- [ ] ⬜ **Task 5.3**: Both fixtures run in CI as `pytest tests/acceptance/test_v391_field_regression.py`.

### Phase 6: Verification + commit ordering

Commits land in this order. Each commit must pass `./scripts/qa/run_all.sh` AND daemon-restart RUNNING before the next commit lands. This is non-negotiable per F15 from review #3.

| #   | Commit                                             | Verifies                                                                                                                      |
| --- | -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 6.A | Phase 1 tests added (RED).                         | All Phase 1 tests fail; QA still passes (failing tests in their own file, marked `xfail` if needed to keep CI green pre-fix). |
| 6.B | Phase 2 paths.py deferred-tomllib + tests pass.    | Tasks 1.1–1.3 turn green. Daemon restart RUNNING.                                                                             |
| 6.C | Phase 3 Task 3.1 (`_resolve-venv.sh`).             | Task 1.4 partially turns green. Daemon restart RUNNING.                                                                       |
| 6.D | Phase 3 Task 3.2 (`venv-include.bash`).            | Daemon restart RUNNING.                                                                                                       |
| 6.E | Phase 3 Task 3.3 (`venv_resolver.sh`).             | Daemon restart RUNNING.                                                                                                       |
| 6.F | Phase 3 Task 3.4 (`init.sh::_resolve_python_cmd`). | Hot path verified — daemon restart RUNNING + 5 sample hook fires succeed via `nc` probe.                                      |
| 6.G | Phase 3 Task 3.5 (`venv.sh:261`).                  | Upgrade path tested — `daemon-cli.sh upgrade --dry-run` (or equivalent) succeeds.                                             |
| 6.H | Phase 4 (bootstrap probe).                         | Task 1.5 turns green.                                                                                                         |
| 6.I | Phase 5 acceptance fixtures + tests.               | All acceptance tests pass.                                                                                                    |
| 6.J | Release prep (Phase 7).                            | `/release patch` gates all green.                                                                                             |

- [ ] ⬜ **Task 6.1**: Execute commit sequence 6.A through 6.I.
- [ ] ⬜ **Task 6.2**: Final full `./scripts/qa/run_all.sh` after 6.I — all 10 checks pass.
- [ ] ⬜ **Task 6.3**: Final daemon restart — RUNNING.
- [ ] ⬜ **Task 6.4**: Live diagnostic test from project root: `health-check.sh`, `daemon-cli.sh status`, `init-handlers.sh` — all clean.

### Phase 7: Release — `/release patch` for v3.9.1

- [ ] ⬜ **Task 7.1**: Run `/release patch` skill end-to-end. All 15 release pipeline steps must pass.
- [ ] ⬜ **Task 7.2**: Acceptance gate covers diagnostic-script invocation paths (the v3.9.0 regression escaped because acceptance focused on hook dispatch).
- [ ] ⬜ **Task 7.3**: Release notes: explicit transparency about v3.9.0 regression. New acceptance-test coverage requirement: every release must include the multi-Python diagnostic-script fixture.
- [ ] ⬜ **Task 7.4**: Verify release published, tag pushed, GitHub release marked latest.

## Dependencies

- **Depends on**: v3.9.0 already released (yes, complete).
- **Blocks**: Plan 00104 (DRY consolidation depends on the per-site fixes landing first).
- **Related**: Plan 00100 (venv SSOT — this is a regression patch; 00104 is the structural follow-up).

## Success Criteria

- [ ] On a multi-Python host (`python3 → 3.9` AND `python3.13` co-resident, daemon previously bootstrapped against 3.13): every diagnostic script (`health-check.sh`, `daemon-cli.sh status`, `init-handlers.sh`) succeeds. **This is the field bug, fixed.**
- [ ] On a single-Python host (`python3 → 3.9` only): bootstrap exits non-zero with directive listing tried commands. No silent fallback to `python3` occurs.
- [ ] On a host with only future `python3.14` (no `3.11/3.12/3.13`): bootstrap discovers it via `compgen` and uses it. No hardcoded ceiling.
- [ ] On a host with no daemon venv at all: every diagnostic script exits non-zero with stderr directive to `/hooks-daemon install`.
- [ ] No `2>/dev/null` redirections around SSOT invocations remain at the 5 sites.
- [ ] No `${[A-Z_]*:-python3}` patterns remain in shell scripts under `scripts/`, `init.sh`, or the skill bundle.
- [ ] No bare `python3` candidate in bootstrap probe lists.
- [ ] `paths.py` imports under Python 3.10 (deferred-tomllib regression test passes).
- [ ] All existing tests pass; 4 new TestLegacyFallback assertions pass; 5 new bootstrap-probe assertions pass; 3 new paths-import assertions pass.
- [ ] Acceptance fixture `multi-python.Dockerfile` exists and the regression test passes.
- [ ] Each commit in the Phase 6 sequence leaves the daemon RUNNING and `run_all.sh` green.
- [ ] v3.9.1 released via `/release patch` with all 15 gates green.

## Risks & Mitigations

| Risk                                                                                                          | Impact | Probability | Mitigation                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Removing the silent legacy fallback breaks pre-v3.7.0 installs that still have `untracked/venv/`              | Medium | Low         | v3.7.0 retired the path; Plan 00100 added eager cleanup. No supported install can still be on it. Release notes call this out.                                                                                                                             |
| Phase 6 commit ordering executed wrong by Sonnet sub-agent                                                    | High   | Medium      | Phase 6 spec is explicit commit-by-commit. Each commit has a verification step that MUST pass before proceeding. Daemon-restart-RUNNING is the load-bearing check.                                                                                         |
| Acceptance fixture `multi-python.Dockerfile` is harder to author than expected                                | Medium | Medium      | Two backup options: (a) Fedora multi-Python image, (b) `pyenv` setup script. Plan accepts whichever ships first.                                                                                                                                           |
| Deferred-tomllib test mechanism (`patch.dict(sys.modules, {'tomllib': None})` + reload) doesn't work portably | Medium | Medium      | Per Review #1 R1 — fall back to subprocess invocation under `python3.10` if installed in CI; otherwise document as xfail with explicit reason. The integration-level paths.py-resolve-venv-under-any-Python test (Task 1.2) is the load-bearing assertion. |
| Self-install dogfooding: developer's own venv breaks while applying this plan                                 | High   | Low         | This repo IS a self-install. Each commit's daemon-restart-RUNNING check catches it. Revert plan: `git revert` any commit that breaks `daemon-cli.sh status`.                                                                                               |
| `compgen -c python3.` returns `python3.0` or other invalid candidates                                         | Low    | Low         | Filter via `case` pattern `python3.[0-9]*`; further filter via `_is_python_at_least_311`. Test 1.5 covers this.                                                                                                                                            |

## Notes & Updates

### 2026-04-30 — v1 plan superseded after three FATAL reviews

- v1 (`PLAN-v1-ambitious-superseded.md`) attempted to combine the patch fix with a DRY consolidation. Three Opus 4.6 hostile reviews returned FATAL (see `context/2026-04-30-review-{1,2,3}-opus*.md`).
- Review #3 root cause: bundling "patch release" with "structural refactor" introduces irreversibly-coupled implementation bugs that no incremental amendment can patch out. Reviewer recommended split.
- User confirmation: "fuck me just design a plan that will work, we need to get these fixes live. Split is fine then I guess if that is the only way."
- This plan is the patch (v3.9.1, ships in days). Plan 00104 is the structural successor (v3.10.0, ships separately).

### 2026-04-30 — v3.9.1 narrow plan ready for review

- Phase 1 (TDD) → Phase 2 (defer tomllib) → Phase 3 (5-site cleanup) → Phase 4 (bootstrap probe) → Phase 5 (acceptance fidelity) → Phase 6 (commit sequence) → Phase 7 (release).
- Total LOC change estimate: \<300 across 5 sites + paths.py deferred-import + bootstrap probe block in 2 files. Each commit \<60 LOC.
