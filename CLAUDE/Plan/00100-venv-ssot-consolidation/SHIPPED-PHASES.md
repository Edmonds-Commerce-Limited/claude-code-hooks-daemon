# Plan 00100 — Shipped Phase Detail

Completed-phase task detail extracted from `PLAN.md` (Plan 00100-shrink):
the full task/sub-bullet breakdown for phases confirmed shipped (Plan 00107
Wave 4 audit — Phases 0–3.9 fully shipped in v3.9.0 / v3.10.0 / v3.11.0; Task
3.5.1 and Phase 4 landed separately, the latter via Plan 00362). Moved
verbatim; see [PLAN.md](PLAN.md) for current status and the task list.

---

### Phase 0: Field-Pain Fixes (LAND FIRST)

**Why first**: three field-proven bugs. Every user upgrading today can hit them.

- [x] ✅ **Task 0.1**: Fix `uv sync` file-visibility race at the source (NOT via retry loop)
  - [x] ✅ Write failing test: `tests/integration/test_verify_venv_file_visibility.py` — 5 tests, 3 RED → GREEN after fix
  - [x] ✅ Update `scripts/install/venv.sh:create_venv_at_path()`: after `uv sync` exits 0, call `sync -f "$venv_path" 2>/dev/null || sync` to force metadata flush
  - [x] ✅ Switch `UV_LINK_MODE` default from `copy` to `hardlink`. Detect "Failed to hardlink" stderr warning and retry once with `UV_LINK_MODE=copy`
  - [x] ✅ Confirmed no retry loop in `verify_venv()` — fix is at the correct layer
  - [x] ✅ Inline comment references Plan 00100 Task 0.1
- [x] ✅ **Task 0.2**: Fix `restart_daemon_verified` false-negative at its root cause
  - [x] ✅ Write failing test: `tests/integration/test_restart_verified_slow_startup.py` — 6 static-analysis tests, 5 RED → GREEN
  - [x] ✅ Replace `cli.py` fixed `time.sleep(0.5)` with polling loop (`Timeout.DAEMON_PID_POLL_INTERVAL_SEC` × `DAEMON_PID_POLL_MAX_ITERATIONS` = 5s ceiling, early-exit on PID appearance)
  - [x] ✅ `daemon_control.sh:restart_daemon_verified()` extended to 15s with `get_daemon_status` polling
  - [x] ✅ Progress logging every 1s: "waiting for daemon (N/15s)"
  - [x] ✅ pgrep fallback: if timeout expires but process exists, retry status for 5 more seconds before aborting
- [x] ✅ **Task 0.3**: Skill-wrapper Python version pre-check (single source of truth)
  - [x] ✅ Write failing test: `tests/integration/test_skill_python_version_precheck.py` — 6 tests, 6 RED → GREEN
  - [x] ✅ `scripts/install/parse_min_python.sh` — parses `pyproject.toml:requires-python` → MAJOR.MINOR on stdout, no hardcoded version
  - [x] ✅ `upgrade.sh`: inline pre-check BEFORE daemon mutation (uses installed pyproject.toml + parse_min_python.sh)
  - [x] ✅ `install.sh`: fetch remote pyproject.toml, inline pre-check BEFORE downloading installer
  - [x] ✅ Actionable `HOOKS_DAEMON_PYTHON=python3.X` hint surfaced on mismatch; daemon state unchanged on failure
- [x] ✅ **Task 0.4**: Clear error surfacing across all three fixes
  - [x] ✅ Task 0.1: `uv` stderr captured via temp file (`/tmp/uv_sync_output.*`), preserved on failure
  - [x] ✅ Task 0.2: polling stderr captured (`/tmp/hooks-daemon-restart-poll.*.err`), dumped on failure with full status output
  - [x] ✅ Task 0.3: version-mismatch errors include active version, required version, and `HOOKS_DAEMON_PYTHON=...` retry command
- [x] ✅ **Task 0.5**: Full QA + daemon restart — three new test files are auto-discovered by `tests/integration/`; `run_all.sh` picks them up without further config

**Success gate**: The three field-reported scenarios are covered by passing tests. The user's original `/hooks-daemon upgrade` command, re-run against HEAD on a host with `python3`=3.9 and `python3.13`=3.13.11, either succeeds cleanly OR fails with actionable messaging and leaves the daemon state unchanged.

---

### Phase 1: Delete Dead Code

**Why**: every future phase is easier once the legacy path is impossible to reach.

- [x] ✅ **Task 1.1**: Grep for all callers of `create_venv`, `recreate_venv`, and hardcoded `untracked/venv/` strings across `src/`, `scripts/`, `tests/`, `docs/`
  - [x] ✅ Classification (2026-04-23):
    - **`create_venv` / `recreate_venv` — zero production callers** (confirms plan diagnosis).
      Definition: `scripts/install/venv.sh:39,110` (DEAD — delete Task 1.2).
      Intra-function calls: `scripts/install/venv.sh:128` (inside `recreate_venv` — deleted with it).
      Tests: `scripts/install/test_venv_manual.sh:40,105` (DELETE — Task 1.2).
      Docs: `scripts/install/README.md:77,78,214` (UPDATE — Task 1.2).
      NOTE: `create_venv_at_path()` is the live function and stays.
    - **Hardcoded `untracked/venv/` outside the dead functions — all are Layer-4 legacy fallbacks**:
      - `scripts/install/venv_resolver.sh:14,82` (Resolver #1 — Task 1.3 TODO)
      - `scripts/venv-include.bash:21,51,61` (Resolver #2, 5th branch — Tasks 1.3 + 1.4)
      - `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh:17,71` (Resolver #3 — Task 1.3)
      - `src/.../daemon/paths.py:117` (Resolver #4 — docstring; Task 1.3)
      - Other hits are in cleanup/migration code (post-upgrade deletion, repair, validator) — those are intentional and stay.
- [x] ✅ **Task 1.2**: Delete `create_venv()` and `recreate_venv()` from `scripts/install/venv.sh`
  - [x] ✅ Delete `scripts/install/test_venv_manual.sh` (tested dead functions)
  - [x] ✅ Update `scripts/install/README.md` (replaced the dead-function docs with the live `ensure_venv`/`create_venv_at_path` table; updated the example call)
  - [x] ✅ TDD RED-GREEN-REFACTOR via `tests/integration/test_venv_sh_dead_code_removed.py` (5 tests, all passing)
- [x] ✅ **Task 1.3**: Mark the legacy-fallback step in all four resolvers with `# TODO Plan 00100 Phase 2: remove`
  - `scripts/install/venv_resolver.sh:82` ✅
  - `scripts/venv-include.bash:61` ✅
  - `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh:71` ✅
  - `src/claude_code_hooks_daemon/daemon/paths.py:158` ✅
- [x] ✅ **Task 1.4 (DEFERRED)**: The "5th branch" in `venv-include.bash` is load-bearing
  after all — it preserves fingerprint-keyed creation on fresh dev machines
  (see `test_fingerprint_keyed_preferred_for_creation_when_no_legacy`).
  Deletion deferred to Phase 2, where the resolver is replaced wholesale by a
  thin shell-out to the Python SSOT. Added an explanatory comment citing the
  guarding test so the intent survives.
- [x] ✅ **Task 1.5**: Full QA (10/10) + daemon restart (RUNNING @ PID 61411) verified 2026-04-23

**Note (v2)**: The `ensure_venv()` legacy-path guard that was Task 1.5 in v1 moved to Task 2.7 (end of Phase 2) per CRITIQUE RISKY-7. Guarding before the bootstrap is redesigned creates a conflict with the Phase 2 bootstrap simplification.

**Success gate**: `./scripts/qa/run_all.sh` green. Daemon status → RUNNING. Grep for `untracked/venv"` (bare legacy path string) returns zero hits outside cleanup/migration logic.

---

### Phase 2: Collapse Four Resolvers Into One Python SSOT

**Why**: drift is inevitable with four parallel implementations.

- [x] ✅ **Task 2.1**: Design a single Python entry point: `python -m claude_code_hooks_daemon.daemon.paths resolve-venv [--daemon-dir DIR]`
  - [x] ✅ Output: single line, the venv python path, exit 0 on success
  - [x] ✅ On failure: stderr cites every precedence step tried and why each failed; exit 1
- [x] ✅ **Task 2.2**: Wrote failing unit tests covering every precedence and every failure mode (`tests/integration/test_paths_resolve_venv_cli.py`, 8 tests)
- [x] ✅ **Task 2.3**: Implemented the entry point in `src/claude_code_hooks_daemon/daemon/paths.py`
  - [ ] ⬜ Reads `.daemon-metadata.json` (written in phase 3) via strict schema validation — deferred to Phase 3
  - [x] ✅ Current implementation preserves 4-step precedence (override → fingerprint → scan → legacy) while Phase 3 persistence work is outstanding. Diagnostic helper `resolve_existing_venv_python_with_diagnostics()` is the new structured backend.
- [x] ✅ **Task 2.4**: Replace each bash resolver with a thin wrapper that shells out to the Python SSOT
  - [x] ✅ `scripts/install/venv_resolver.sh` → shells out to `paths.py resolve-venv` (direct-script, bypasses `__init__.py` pydantic import); 7/7 integration tests pass
  - [x] ✅ `scripts/venv-include.bash` → shells out with `--fallback-target` so pre-creation bootstrap gets the keyed target path; 5/5 integration tests pass
  - [x] ✅ `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh` → shells out to `$DAEMON_DIR` copy of paths.py; 17/17 integration tests pass
  - [x] ✅ Each wrapper is under the 20-line target (venv_resolver 53 total incl. help docs, venv-include `_resolve_venv_dir` 20 lines, \_resolve-venv 50 total incl. docs — all ~5–15 lines of executable bash)
  - [x] ✅ paths.py extended with `--fallback-target` flag and dual-interpreter acceptance (`bin/python` OR `bin/python3`) so the three wrappers share identical semantics; 21/21 unit tests pass
- [x] ✅ **Task 2.5** (REWRITTEN from v1): Simplify the bootstrap case
  - [x] ✅ `upgrade.sh` now defines `_stop_running_daemons()` which iterates `untracked/daemon-*.pid`, reads each PID, `kill -0` checks, `kill -TERM`, sleep 1. Zero venv resolution, zero Python invocation.
  - [x] ✅ Refactor pinned by `tests/integration/test_upgrade_sh_stop_bootstrap.py` (9 tests): function defined, no venv refs in body, SIGTERMs the sleeper, handles multiple daemons, and silently skips missing/empty/stale/non-numeric PID files.
  - [x] ✅ After this refactor, there is zero duplication of resolver logic outside the Python SSOT.
- [x] ✅ **Task 2.6**: Full QA + daemon restart + re-run phase 0 and 1 tests (10/10 QA, daemon RUNNING, all suites green)
- [x] ✅ **Task 2.7** (MOVED from v1 Task 1.5): Add a guard in `ensure_venv()` that refuses to create at the legacy path
  - [x] ✅ Failing tests written FIRST: `tests/integration/test_legacy_path_refused.py` — 4 tests (refuse-create, accept-existing, fingerprint-allowed, suffix-exact)
  - [x] ✅ `ensure_venv()` checks `VENV_DIR == */untracked/venv` and FAILS FAST with loud multi-line error naming the SSOT as the cause; pre-existing legacy venvs still accepted (guard fires only on creation)

**Success gate**: Grep for resolver precedence logic returns exactly one definition (Python). Bash wrappers each < 20 lines. All Phase 0 + 1 tests still pass. `ensure_venv` rejects legacy path.

---

### Phase 3: Persist Installer Choices (Eliminate Recompute Disagreement)

**Why**: the fingerprint mismatch that v3.8.1 papered over becomes impossible if the resolver *reads* the installer's choice.

- [x] ✅ **Task 3.0** (NEW in v2): Establish `uv.lock` as a first-class repo artefact
  - [x] ✅ Generate `uv.lock` at HEAD via `uv lock` (at project root) — 377K lockfile committed
  - [x] ✅ Commit the lockfile (commit `ed02c72`)
  - [x] ✅ Add a CI step: `uv lock --check` runs in `scripts/qa/run_dependency_check.sh` before deptry (fails if pyproject.toml diverges from uv.lock)
  - [x] ✅ Verified `.gitignore`: `uv.lock` is NOT ignored (Pipfile.lock / venv/ / .venv / untracked/ are the only lock/venv patterns); no change needed
  - [x] ✅ Update CONTRIBUTING.md with the lockfile workflow (regenerate via `uv lock`, commit alongside dep changes)
- [x] ✅ **Task 3.0.5** (NEW in v3): Add human-readable path slug to venv dir name — committed `37df4cd`
  - [x] ✅ Failing test first: `tests/unit/daemon/test_paths_venv_slug.py` — host vs container distinct slugs, truncation + 4-hex at >40 chars, filesystem-safe chars only
  - [x] ✅ Implement `project_path_slug(root: str) -> str` in `src/claude_code_hooks_daemon/daemon/paths.py` (strip `/`, safe chars, truncate at 40 with 4-hex suffix)
  - [x] ✅ `python_venv_fingerprint(root=None)` returns `{pathslug}-py{MM}-{pyhash}` when root given, legacy `py{MM}-{pyhash}` when None (back-compat)
  - [x] ✅ All three cli.py callers (`_enumerate_venvs`, `cmd_list_venvs`, `cmd_prune_venvs`) + both `resolve_existing_venv_python*` pass project_root
  - [x] ✅ Bash SSOT `scripts/install/python_fingerprint.sh` accepts `$2` positional root and `HOOKS_DAEMON_ROOT_DIR` env; mirrors slug logic inline
  - [x] ✅ Bash↔Python parity tests in `test_fingerprint_parity.py` (6 new, 11 total) — byte-identical slug + hash
  - [x] ✅ 656 daemon unit tests + 11 parity tests pass; migration deferred to Task 3.5 below
- [x] ✅ **Task 3.1** (REVISED from v1): Design single atomic metadata file inside venv dir
  - [x] ✅ `.daemon-metadata.json`: `{"python_path": "...", "fingerprint": "py313-956ed987", "lock_hash": "sha256:...", "daemon_version": "v3.9.0", "written_at": "ISO8601"}`
  - [x] ✅ Schema: pydantic model in `daemon/metadata.py` (extracted from `paths.py` so install-time stdlib-only invocation survives — see Phase 3 notes in `daemon/metadata.py` docstring)
- [x] ✅ **Task 3.2**: Write failing tests for metadata write and read (`tests/unit/daemon/test_metadata.py` + `test_project_lock_hash.py`)
- [x] ✅ **Task 3.3** (REVISED from v1): Atomic write via Python SSOT CLI, invoked from bash `ensure_venv()`
  - [x] ✅ New `write-venv-metadata` subcommand (`src/claude_code_hooks_daemon/daemon/cli.py`) writes the metadata through the Pydantic schema
  - [x] ✅ `scripts/install/venv.sh::ensure_venv` shells out to it after `uv sync` completes
  - [x] ✅ Write to `{venv}/.daemon-metadata.json.tmp` → `os.replace` → `.daemon-metadata.json` (single atomic rename in `write_daemon_metadata`)
  - [x] ✅ Interruption mid-write leaves the venv without metadata → resolver treats as stale → rebuild. Safe.
  - [x] ✅ `tests/unit/daemon/test_cli_write_venv_metadata.py` covers the CLI entry point end-to-end
- [x] ✅ **Task 3.4**: Update the Python SSOT resolver to:
  - [x] ✅ Read `.daemon-metadata.json` and use `python_path` as authoritative interpreter — new step 2 in `resolve_existing_venv_python_with_diagnostics` (`src/claude_code_hooks_daemon/daemon/paths.py`)
  - [x] ✅ Compare `lock_hash` against `sha256(current pyproject.toml + uv.lock)`; mismatch → diagnostic stale report, fall through to step 3 (Task 3.5 tightens this to unconditional skip)
  - [x] ✅ Never recompute fingerprint for lookup — metadata discovery is by JSON read, fingerprint is only used in step 3 (legacy naming convenience)
  - [x] ✅ Stdlib-only helpers `_read_venv_metadata_stdlib` + `_compute_project_lock_hash_stdlib` mirror `metadata.py` byte-for-byte so `paths.py` stays Pydantic-free at install time
  - [x] ✅ 8 new tests in `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestMetadataDrivenResolution`; existing diagnostic tests renumbered 2→3, 3→4, 4→5; integration CLI precedence docstring updated to 5 steps
- [x] ✅ **Task 3.5**: Migration — if a venv has `.daemon-version` file but no `.daemon-metadata.json`, treat as stale → rebuild. Log clearly.
  - [x] ✅ 6 RED tests added in `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestLegacyStampMigration` covering: fingerprint-keyed/scan/legacy-bare skip paths; pristine pre-stamp venv still accepted; fingerprint-keyed without any markers still accepted; co-existence with metadata-bearing sibling
  - [x] ✅ New constant `_LEGACY_DAEMON_VERSION_STAMP = ".daemon-version"` + helper `_is_legacy_stamp_only(venv_dir)` in `paths.py` — returns True iff `.daemon-version` present AND `.daemon-metadata.json` absent
  - [x] ✅ Steps 3/4/5 of `resolve_existing_venv_python_with_diagnostics` each wrap candidate checks with `_is_legacy_stamp_only` — legacy-stamp-only venvs emit a clear migration diagnostic (`"skipping legacy-stamped venv … — needs rebuild via ensure_venv"`) and fall through
  - [x] ✅ Docstring precedence list refreshed to reflect Task 3.5 migration behaviour
  - [x] ✅ All 6 new tests GREEN; 43/43 tests across `test_paths_resolve_venv_diagnostics.py` + `test_paths_resolve_venv_cli.py` pass
  - [x] ✅ 1358 daemon + integration tests pass with zero regressions; QA 10/10; daemon restart RUNNING
- [x] ✅ **Task 3.6** (REVISED from v1): Missing-persisted-Python recovery (Decision 3 change)
  - [x] ✅ 4 RED tests added in `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestMissingPersistedPythonRecovery` covering: alternative-found branch, no-alternative branch, diagnostic names lost path, `_find_compatible_python_on_path` returns None on empty PATH
  - [x] ✅ New constants `_COMPATIBLE_PYTHON_CANDIDATES = ("python3", "python3.13", "python3.12", "python3.11")`, `_MIN_COMPATIBLE_PYTHON = (3, 11)`, `_COMPATIBLE_PYTHON_PROBE_TIMEOUT_SECS = 3.0` + helper `_find_compatible_python_on_path()` in `paths.py` — mirrors `scripts/upgrade.sh::find_compatible_python` byte-for-byte, runs a tiny `sys.version_info >= (3,11)` probe on each candidate resolvable through `shutil.which`
  - [x] ✅ Step 2 of `resolve_existing_venv_python_with_diagnostics` extended: when `.daemon-metadata.json` has a matching `lock_hash` but `python_path` no longer exists or is not executable, the resolver now appends a `"step 2 recovery: …"` diagnostic naming the alternative (or "no compatible alternative — install Python 3.11+") so ensure_venv/upgrade can act on it
  - [x] ✅ Function-level exclusion added to `scripts/qa/error_hiding_exclusions.json` for `_find_compatible_python_on_path` — the `except (OSError, subprocess.SubprocessError): continue` is the documented candidate-skip recovery path, same pattern as `scripts/upgrade.sh`
  - [x] ✅ All 4 new tests GREEN; 1362 daemon + integration tests pass with zero regressions
  - [x] ✅ QA 10/10 PASSED; daemon restart RUNNING (PID 90731)
- [x] ✅ **Task 3.7**: Downgrade safety — if `lock_hash` matches current state, do NOT rebuild on daemon version change
  - [x] ✅ 2 RED integration tests added in `tests/integration/test_ensure_venv.py::TestEnsureVenvDowngradeSafety`: `test_noop_when_lock_hash_matches_even_if_stamp_differs` (venv with current lock_hash + stale `v1.0.0` stamp must survive `ensure_venv ... v99.0.0`) and `test_rebuilds_when_metadata_absent_and_stamp_differs` (backward-compat: legacy pre-Phase-3 venv still rebuilds on stamp mismatch)
  - [x] ✅ New CLI subcommand `check-venv-fresh` in `src/claude_code_hooks_daemon/daemon/paths.py` (`_cli_check_venv_fresh`) — stdlib-only (invokable under host python3 at install time), exits 0 when `.daemon-metadata.json::lock_hash` matches `_compute_project_lock_hash_stdlib(daemon_dir)`, else 1 (including missing venv dir, missing/malformed metadata, missing pyproject)
  - [x] ✅ New bash helper `venv_lock_hash_matches` in `scripts/install/venv.sh` — invokes `paths.py` as a direct script file (avoids pydantic import), routes stderr through `print_verbose` instead of `>/dev/null 2>&1` (error_hiding hook compliant)
  - [x] ✅ `ensure_venv` fast path rewired: lock_hash check runs BEFORE legacy `venv_version_matches` stamp check; stamp retained as fallback for venvs lacking `.daemon-metadata.json`
  - [x] ✅ 6 RED unit tests added in `tests/unit/daemon/test_paths_check_venv_fresh.py` exercising all branches of `_cli_check_venv_fresh` (match, mismatch, missing venv, missing metadata, no-pyproject, cwd-default)
  - [x] ✅ All 8 new tests GREEN; 1364 integration + daemon unit tests pass with zero regressions; QA 10/10 (coverage 95.0%); daemon restart RUNNING (PID 107285)
- [x] ✅ **Task 3.8**: Full QA + daemon restart + all prior phase tests
  - [x] ✅ Full QA 10/10 PASSED (magic_values, format, lint, type_check, tests, security, dependencies, error_hiding, skill_refs, smoke_test); shell_check passes with 0 errors / 0 warnings (58 info-level only)
  - [x] ✅ 7979 tests pass, coverage 95.0% (meets 95% gate)
  - [x] ✅ Phase-specific regression: all 140 Plan 00100 tests pass (`test_paths_resolve_existing_venv`, `test_paths_resolve_venv_diagnostics`, `test_paths_venv_fingerprint`, `test_paths_venv_slug`, `test_paths_stale_cleanup`, `test_paths_check_venv_fresh`, `test_paths_resolve_venv_cli`, `test_ensure_venv`)
  - [x] ✅ Daemon restart verified RUNNING (PID 107285)
- [x] ✅ **Task 3.9** (NEW in v3): Eager upgrade cleanup — `hooks-daemon upgrade` leaves zero stale venvs
  - [x] ✅ Failing test (RED): `tests/integration/test_upgrade_eager_cleanup.py` — 6 tests across 6 classes (function-exists preflight, removes-stale-keeping-current, per-deletion log lines, no-op when only current, missing-untracked silent no-op, non-venv entries preserved)
  - [x] ✅ Implemented in `scripts/install/venv.sh` as `eager_cleanup_stale_venvs(daemon_dir, current_venv)` — enumerates `untracked/venv` + `untracked/venv-*`, skips the current path, `rm -rf` the rest
  - [x] ✅ Wired into `scripts/upgrade_version.sh` AFTER `restart_daemon_verified` confirms RUNNING on `$VENV_PATH` (rollback safety — failed upgrade leaves prior state intact)
  - [x] ✅ Per-deletion log line emitted: `"Removed stale venv: <abs-path> (reason: <legacy-name|fingerprint-mismatch>)"`
  - [x] ✅ Plain daemon start (non-upgrade) path UNCHANGED — still uses lazy-rebuild-via-stamp inside `ensure_venv`
  - [x] ✅ `cmd_prune_venvs` docstring in `src/claude_code_hooks_daemon/daemon/cli.py` updated to reference automatic upgrade-time cleanup; `--all-except-current` remains available for manual eager cleanup outside the upgrade flow
  - [x] ✅ QA 10/10 (coverage 95.0%), daemon restart RUNNING (PID 121109)

**Success gate**: A venv built at HEAD on python 3.13 and queried under `python3`=3.11 on PATH resolves correctly via `.daemon-metadata.json` without any scan fallback. Missing persisted Python triggers recovery, not hard failure. `untracked/` after `hooks-daemon upgrade` contains exactly one `venv-*/` directory.

---

### Phase 3.5, Task 3.5.1: the "inline-safe" precondition predicate

Part of Phase 3.5 (Self-Healing Bootstrap); see `PLAN.md` for the phase's
overall status and the still-open Tasks 3.5.2–3.5.7 (now carried by Plan
00456).

- [x] ✅ **Task 3.5.1**: Define the "inline-safe" precondition predicate
  - [x] ✅ New helper `can_inline_bootstrap(daemon_dir: Path) -> BootstrapDecision` in `src/claude_code_hooks_daemon/daemon/paths.py` returning a dataclass with `(allowed: bool, missing: list[str], reason: str)`
  - [x] ✅ All five must hold for `allowed=True`:
    1. `shutil.which("uv")` returns a path
    2. `{daemon_dir}/pyproject.toml` exists and parses
    3. `{daemon_dir}/uv.lock` exists
    4. `find_compatible_python()` returns a Python satisfying `pyproject.toml:requires-python`
    5. Target venv parent (`{daemon_dir}/untracked/`) is writable
  - [x] ✅ Failing tests first: `tests/unit/daemon/test_bootstrap_decision.py` — one test per precondition-missing path; one test for all-green case; plus the probe-failure exception branch (FAIL-FAST: `_probe_python_major_minor` raises rather than returning None)

---

### Phase 4: Concurrency Protection

- [x] ✅ **Task 4.0** (NEW in v2): Verify `flock` behaviour under Podman bind-mount — commit `80417d4b` (Plan 00362 Task 2.10)
  - [x] ✅ Spike: two processes in the CCY container both calling `flock` on `/workspace/untracked/.venv-bootstrap.lock`. Result (`container=podman`, bind-mounted btrfs): holder A took the lock for 3s; B's `flock -n` was refused while A held it and its `flock -w` acquired only after A released; 20 processes doing read-increment-write under the lock ended at 20. Mutual exclusion holds.
  - [x] ✅ Confirm mutual exclusion holds across bind-mount boundary: container ↔ container sharing the mount verified by the spike. Host ↔ container is not reachable from inside the container; the `mkdir` fallback below (`HOOKS_DAEMON_VENV_LOCK_BACKEND=mkdir`) is the documented escape if a mount is ever found not to propagate `flock`.
  - [x] ✅ `flock` passed, so it is the default backend. The fallback is a `mkdir` lock (`.venv-bootstrap.lock.d` + `pid` file) with a stale-age reclaim (`HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS`, 600s) rather than `kill -0`, because a PID is meaningless across a container boundary.
- [x] ✅ **Task 4.1**: Write failing test: two processes calling `ensure_venv` simultaneously do not corrupt the venv — `tests/integration/test_ensure_venv_lock.py`
  - [x] ✅ Uses `subprocess.Popen` pairs against a stub `uv` that sleeps (RED: both starters ran `uv sync` into one target)
  - [x] ✅ Asserts second process waits for first, then fast-paths (one sync, same path from both, "waiting up to" only on the second); 20-iteration gate marked `slow`
- [x] ✅ **Task 4.2**: Implement concurrency protection (flock, mkdir fallback) around the mutating section of `ensure_venv()` — `acquire_venv_lock`/`release_venv_lock`/`_ensure_venv_build` in `scripts/install/venv.sh`; the fast path stays lock-free and freshness is re-checked under the lock
  - [x] ✅ Lock file: `{daemon_dir}/untracked/.venv-bootstrap.lock`
  - [x] ✅ Timeout with clear error if lock held > 120s (`HOOKS_DAEMON_VENV_LOCK_TIMEOUT`; the message names the lock path and the bound)
- [x] ✅ **Task 4.3**: Python-side equivalent for CLI `repair` command — `src/claude_code_hooks_daemon/daemon/venv_lock.py`, same file, backend and env vars; `cmd_repair` runs `uv sync` inside it
- [x] ✅ **Task 4.4**: Touched suites, shellcheck, ruff and `mypy --strict` green in the worktree; the daemon restart and full QA run belong to the Plan 00362 merge session

**Success gate**: Concurrency test passes deterministically over 20 iterations. Bind-mount behaviour verified.
