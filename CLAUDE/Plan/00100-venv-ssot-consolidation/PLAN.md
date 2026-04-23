# Plan 00100 (v2): Venv SSOT Consolidation — Stop the Release Treadmill

**Status**: In Progress (Phase 2 — Phases 0 & 1 complete)
**Created**: 2026-04-23
**Revised**: 2026-04-23 (v2 — addresses CRITIQUE-v1.md)
**Started**: 2026-04-23
**Owner**: TBD
**Priority**: Critical
**Type**: Bug Fix / Architectural Consolidation
**Recommended Executor**: Opus (Sub-Agent Teams)
**Execution Strategy**: Sub-Agent Teams
**Predecessor**: Plan 00099 (Python-Fingerprint Venv Isolation) — shipped v3.7.0 and triggered the treadmill
**Supersedes**: PLAN-v1.md (see CRITIQUE-v1.md for the hostile-review findings that drove v2)

## v1 → v2 Changes (Summary)

The hostile Opus review of v1 identified 3 FATAL and 7 RISKY flaws. Full details in CRITIQUE-v1.md. v2 corrects each:

| v1 Flaw                                     | v2 Correction                                                                                                                   |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| FATAL-1: `uv.lock` doesn't exist            | Phase 3.0 introduces `uv lock` generation + commit; stamp becomes `sha256(pyproject.toml + uv.lock)`                            |
| FATAL-2: PID/socket race misdiagnosed       | Task 0.2 rewritten: replace `cli.py:341` fixed `sleep(0.5)` with polling loop; socket-poll is a belt-and-braces secondary check |
| FATAL-3: Retry loop treats symptom          | Task 0.1 rewritten: call `sync -f` after `uv sync`; switch `UV_LINK_MODE` to hardlink-with-copy-fallback. No retry loop.        |
| RISKY-1: Bootstrap fallback under-specified | Task 2.5 rewritten: bootstrap performs PID-kill only, no venv resolution                                                        |
| RISKY-2: Hardcoded min Python in wrapper    | Task 0.3: min Python parsed from `pyproject.toml:requires-python`                                                               |
| RISKY-3: Fail-on-missing-persisted-Python   | Decision 3 revised: on missing persisted Python, retry `find_compatible_python` then fail only if no compatible Python found    |
| RISKY-4: Phase 5 runtime unproven           | Task 5.0 added: timing spike before committing to `run_all.sh` inclusion                                                        |
| RISKY-5: `flock` across bind-mounts unclear | Task 4.0 added: verify `flock` under Podman bind-mount before implementation                                                    |
| RISKY-6: Metadata write not atomic          | Tasks 3.1/3.3 revised: single `.daemon-metadata.json`, temp-file + rename                                                       |
| RISKY-7: Task 1.5 vs 2.5 conflict           | Task 1.5 moved to end of Phase 2 (merged as Task 2.7); Phase 1 no longer contains guard                                         |

## Field Evidence (2026-04-23)

A project agent running `/hooks-daemon upgrade` on `/srv/example-app/front` (Fedora, `python3`=3.9 incompatible, `python3.13` compatible) reported three **new** failure modes not caught by the code-review agents. See `/workspace/untracked/hooks-daemon-upgrade-problems-python-version.md`. The fingerprint venv dir `venv-py313-956ed987` was created correctly and the daemon eventually ran — but the upgrade script declared failure twice along the way, leaving the user to manually recover:

- **`verify_venv` race on `uv sync` file visibility**: `uv sync` exits 0, writes `bin/python`, but the immediate `[ ! -f "$venv_python" ]` check returns "not found" under `UV_LINK_MODE=copy`. The file was present seconds later. **Root cause** (v2): `UV_LINK_MODE=copy` does copy-then-rename; no post-uv `sync` call.
- **`restart_daemon_verified` false negative**: daemon log confirms `Daemon listening on ...` at 14:51:37, but the script's PID-file poll timed out fractionally earlier. **Root cause** (v2): `cli.py:341` uses a fixed `time.sleep(0.5)` before polling — insufficient for startup overhead on slow hosts. The real bottleneck is the child's startup time (imports + config load + handler init), not the PID/socket file ordering.
- **No pre-check for `python3` version in the skill wrapper**: on this host `python3`→3.9. The daemon's Layer 1 correctly found `/usr/bin/python3.13`, but transient downstream failures surfaced only after the daemon had been stopped. **Root cause** (v2): the skill-layer runs no Python version pre-check before disrupting daemon state.

## Overview

Five consecutive releases have patched venv-related bugs:

| Release | What shipped                                               | What broke                                                       |
| ------- | ---------------------------------------------------------- | ---------------------------------------------------------------- |
| v3.1.1  | Post-install verification + recreate on idempotent upgrade | venv not recreated when deps changed without version bump        |
| v3.7.0  | Fingerprint-keyed venv isolation                           | Introduced second venv path scheme; didn't retire the first      |
| v3.8.0  | Skill wrapper venv fix                                     | Skill wrapper hardcoded legacy path; didn't use resolver         |
| v3.8.1  | Skill resolver fingerprint-mismatch fallback               | Fingerprint computed by installer != fingerprint seen at runtime |
| v3.8.2  | Comprehensive Venv Resolver SSOT (aspirational)            | Four parallel resolver implementations still exist in tree       |

Three independent investigations (venv-trace, venv-review, venv-test-audit) converge on the same diagnosis:

1. **Dead code is the seed.** `scripts/install/venv.sh` still exports `create_venv()` and `recreate_venv()` — legacy functions writing to `untracked/venv/`. Zero production callers, but every sourcer of `venv.sh` imports them.
2. **The "SSOT" is four implementations.** `scripts/install/venv_resolver.sh`, `scripts/venv-include.bash:_resolve_venv_dir`, `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh`, and `src/.../daemon/paths.py:resolve_existing_venv_python`. `venv-include.bash` already has a 5th branch the others lack — drift has begun.
3. **The scan fallback papers over a real bug.** If the installer's fingerprint and the resolver's fingerprint differ, the correct fix is to **persist the chosen Python inside the venv dir** — not scan for "any venv-\*".
4. **Stamp semantics are wrong.** `.daemon-version` misses `pyproject.toml` edits without version bumps (v3.1.1's bug).
5. **No concurrency protection.** Two daemons starting simultaneously both `rm -rf` and `uv sync` the same dir. No `flock`.
6. **Bash has zero CI coverage.** No end-to-end "install old tag → upgrade to HEAD → verify daemon RUNNING" test exists.

This plan eliminates the treadmill by **collapsing the four resolvers into one**, **deleting all dead paths**, **replacing the stamp with a lockfile hash**, **adding concurrency protection**, and **making bash changes CI-gated via a real end-to-end upgrade test**.

## Goals

- **Exactly one** venv resolver implementation (Python), with bash shelling out to it
- **Zero** legacy code paths in `venv.sh` — `create_venv()` and `recreate_venv()` deleted
- **Zero** scan fallbacks in steady state — resolver reads persisted `.daemon-metadata.json` from inside the venv dir, never recomputes
- **Deterministic stamp**: `sha256(pyproject.toml + uv.lock)`, persisted in `.daemon-metadata.json`
- **Concurrency-safe**: `flock` (or bind-mount-safe equivalent) around all `ensure_venv` mutations
- **CI-gated bash**: a pytest-integrated test that installs a prior released tag, upgrades to HEAD, and asserts `daemon status == RUNNING`
- **Clear error surfacing**: resolution failure cites every precedence step tried and the reason each failed

## Non-Goals

- Not revisiting the fingerprint *content*. Plan 00099 delivered it well.
- Not changing hostname-scoped socket/PID paths. That grain is correct.
- Not adding new CLI surface area beyond what's needed for testing.
- Not migrating existing deployed venvs forcibly. Legacy `untracked/venv/` is deleted on first upgrade encounter.

## Context & Background

Investigation artefacts:

- **venv-trace** report: 7 independent code paths, 6 different combinations
- **venv-review** report: critical bugs + design smells (four resolvers, source-time resolver under `pipefail`)
- **venv-test-audit** report: bash tests are `test_*_manual.sh`, not in CI
- **CRITIQUE-v1.md**: hostile Opus review of PLAN-v1.md

Key files:

- `/workspace/scripts/install/venv.sh` — dual creators (dead `create_venv` + live `ensure_venv`)
- `/workspace/scripts/install/venv_resolver.sh` — resolver #1 (install-time bash)
- `/workspace/scripts/install/python_fingerprint.sh` — fingerprint SSOT (keep as-is)
- `/workspace/scripts/venv-include.bash` — resolver #2 (init/QA bash)
- `/workspace/scripts/upgrade.sh` — Layer 1 bootstrap (lines 156-164)
- `/workspace/scripts/install/daemon_control.sh` — `restart_daemon_verified`
- `/workspace/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` — resolver #3
- `/workspace/src/claude_code_hooks_daemon/daemon/paths.py` — resolver #4 (Python)
- `/workspace/src/claude_code_hooks_daemon/daemon/server.py` — PID/socket lifecycle (lines 327-366)
- `/workspace/src/claude_code_hooks_daemon/daemon/cli.py` — start/restart handler (line 341 fixed sleep)
- `/workspace/pyproject.toml` — `requires-python` authoritative; no `uv.lock` currently exists

## Execution Strategy

Opus orchestrates a team. Each phase lands a green state before the next begins.

**Roles**:

- **Architect (Opus main thread)**: phase planning, design decisions, code review of each phase
- **Bash consolidator (sub-agent)**: phases 1, 3, 4
- **Python consolidator (sub-agent)**: phase 2
- **Test engineer (sub-agent)**: phases 0, 5
- **QA/release integrator (sub-agent)**: phase 6

**Checkpoint commits** after every phase. QA green + daemon restart RUNNING is the per-phase gate.

---

## Phases

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
- [ ] ⬜ **Task 2.5** (REWRITTEN from v1): Simplify the bootstrap case
  - [ ] ⬜ `upgrade.sh:156-164` currently resolves a venv just so it can stop the running daemon. Refactor: read PID path → `kill -TERM <pid>` → wait → fall through. No venv resolution needed at bootstrap time.
  - [ ] ⬜ After this refactor, there is zero duplication of resolver logic outside the Python SSOT
- [ ] ⬜ **Task 2.6**: Full QA + daemon restart + re-run phase 0 and 1 tests
- [ ] ⬜ **Task 2.7** (MOVED from v1 Task 1.5): Add a guard in `ensure_venv()` that refuses to create at the legacy path
  - [ ] ⬜ Write failing test FIRST: `tests/integration/test_legacy_path_refused.py` — confirms `ensure_venv` cannot produce `untracked/venv/`
  - [ ] ⬜ If `venv_path` ends in `/untracked/venv` (no fingerprint suffix), FAIL FAST with a loud error

**Success gate**: Grep for resolver precedence logic returns exactly one definition (Python). Bash wrappers each < 20 lines. All Phase 0 + 1 tests still pass. `ensure_venv` rejects legacy path.

---

### Phase 3: Persist Installer Choices (Eliminate Recompute Disagreement)

**Why**: the fingerprint mismatch that v3.8.1 papered over becomes impossible if the resolver *reads* the installer's choice.

- [ ] ⬜ **Task 3.0** (NEW in v2): Establish `uv.lock` as a first-class repo artefact
  - [ ] ⬜ Generate `uv.lock` at HEAD via `uv lock` (at project root)
  - [ ] ⬜ Commit the lockfile
  - [ ] ⬜ Add a CI step: `uv lock --check` must pass (fails if pyproject.toml diverges from uv.lock)
  - [ ] ⬜ Update `.gitignore` if needed (currently not ignored, so likely no change)
  - [ ] ⬜ Update CONTRIBUTING.md with the lockfile workflow (regenerate via `uv lock`, commit alongside dep changes)
- [ ] ⬜ **Task 3.1** (REVISED from v1): Design single atomic metadata file inside venv dir
  - [ ] ⬜ `.daemon-metadata.json`: `{"python_path": "...", "fingerprint": "py313-956ed987", "lock_hash": "sha256:...", "daemon_version": "v3.9.0", "written_at": "ISO8601"}`
  - [ ] ⬜ Schema: pydantic model in `paths.py` for read-side validation
- [ ] ⬜ **Task 3.2**: Write failing tests for metadata write and read
- [ ] ⬜ **Task 3.3** (REVISED from v1): Atomic write in `ensure_venv()` and `create_venv_at_path()`
  - [ ] ⬜ Write to `{venv}/.daemon-metadata.json.tmp`
  - [ ] ⬜ `mv .daemon-metadata.json.tmp .daemon-metadata.json` (single atomic rename)
  - [ ] ⬜ Interruption mid-write leaves the venv without metadata → resolver treats as stale → rebuild. Safe.
- [ ] ⬜ **Task 3.4**: Update the Python SSOT resolver to:
  - [ ] ⬜ Read `.daemon-metadata.json` and use `python_path` as authoritative interpreter
  - [ ] ⬜ Compare `lock_hash` against `sha256(current pyproject.toml + uv.lock)`; mismatch → rebuild
  - [ ] ⬜ Never recompute fingerprint for lookup (fingerprint stays a directory-naming convenience)
- [ ] ⬜ **Task 3.5**: Migration — if a venv has `.daemon-version` file but no `.daemon-metadata.json`, treat as stale → rebuild. Log clearly.
- [ ] ⬜ **Task 3.6** (REVISED from v1): Missing-persisted-Python recovery (Decision 3 change)
  - [ ] ⬜ Write failing test: persisted Python path no longer exists; assert resolver falls back to `find_compatible_python` and succeeds if a compatible one is found
  - [ ] ⬜ Implement: on `os.path.exists(metadata.python_path) == False`, run `find_compatible_python`, emit log message ("persisted Python X missing — searching for compatible alternative"), rebuild venv with the alternative
  - [ ] ⬜ Only error if no compatible Python exists — emit actionable message
- [ ] ⬜ **Task 3.7**: Downgrade safety — if `lock_hash` matches current state, do NOT rebuild on daemon version change
- [ ] ⬜ **Task 3.8**: Full QA + daemon restart + all prior phase tests

**Success gate**: A venv built at HEAD on python 3.13 and queried under `python3`=3.11 on PATH resolves correctly via `.daemon-metadata.json` without any scan fallback. Missing persisted Python triggers recovery, not hard failure.

---

### Phase 4: Concurrency Protection

- [ ] ⬜ **Task 4.0** (NEW in v2): Verify `flock` behaviour under Podman bind-mount
  - [ ] ⬜ Spike: two processes in the CCY container both calling `flock` on `/workspace/untracked/.venv-bootstrap.lock`
  - [ ] ⬜ Confirm mutual exclusion holds across bind-mount boundary (host ↔ container, and container ↔ container sharing the mount)
  - [ ] ⬜ If `flock` fails the spike, switch to PID-file lock with liveness check (write PID, check `kill -0 <pid>` on contention, wait or fail if alive). Document the choice.
- [ ] ⬜ **Task 4.1**: Write failing test: two processes calling `ensure_venv` simultaneously do not corrupt the venv
  - [ ] ⬜ Uses `multiprocessing` or `subprocess.Popen` pairs
  - [ ] ⬜ Asserts second process waits for first, then fast-paths
- [ ] ⬜ **Task 4.2**: Implement concurrency protection (flock or PID-lock per Task 4.0 outcome) around the mutating section of `ensure_venv()`
  - [ ] ⬜ Lock file: `{daemon_dir}/untracked/.venv-bootstrap.lock`
  - [ ] ⬜ Timeout with clear error if lock held > 120s
- [ ] ⬜ **Task 4.3**: Python-side equivalent for CLI `repair` command
- [ ] ⬜ **Task 4.4**: Full QA + daemon restart + all prior phase tests

**Success gate**: Concurrency test passes deterministically over 20 iterations. Bind-mount behaviour verified.

---

### Phase 5: End-to-End Upgrade Test

**Why**: without this, phase 6's release ships blind.

- [ ] ⬜ **Task 5.0** (NEW in v2): Runtime spike before committing to `run_all.sh` inclusion
  - [ ] ⬜ Build a minimal harness that runs ONE upgrade cycle (v3.8.0 → HEAD) and measures elapsed time end-to-end
  - [ ] ⬜ If a single cycle exceeds 60s, do not add the 5-tag matrix to `run_all.sh` — move to a nightly job instead (see Task 5.5 decision point)
  - [ ] ⬜ If single cycle is < 30s, the 5-tag matrix fits in run_all.sh under 3 minutes with parallelism
- [ ] ⬜ **Task 5.1**: Design `tests/integration/test_full_upgrade_cycle.py`
  - [ ] ⬜ Parameterised over prior released tags: `v3.6.0`, `v3.7.0`, `v3.8.0`, `v3.8.1`, `v3.8.2`
  - [ ] ⬜ Each case: `git worktree add` at that tag into a tmpdir, run its install, verify daemon starts, overlay HEAD, run upgrade, verify daemon starts
  - [ ] ⬜ Session-scoped fixture caches the worktree setup to amortise cost
- [ ] ⬜ **Task 5.2**: Write failing first against current HEAD (should reveal residual split brain)
- [ ] ⬜ **Task 5.3**: Promote `scripts/install/test_venv_manual.sh` deletion to real pytest tests that exercise bash functions via `subprocess`
  - [ ] ⬜ `tests/integration/test_venv_bash_functions.py`
- [ ] ⬜ **Task 5.4**: Second parameterised test: same-project-different-python
  - [ ] ⬜ Create two venvs at different fingerprints, switch, verify each resolves correctly
- [ ] ⬜ **Task 5.5**: Wire tests based on Task 5.0 spike result
  - [ ] ⬜ IF spike showed < 3 min for full matrix: add to `./scripts/qa/run_all.sh`
  - [ ] ⬜ ELSE: add to `.github/workflows/nightly.yml` (create if absent) + add a gate that `/release` skill runs the nightly suite before Step 8
- [ ] ⬜ **Task 5.6**: Update `CLAUDE/development/RELEASING.md` Step 8 QA Gate to explicitly require the upgrade-cycle test pass (wherever it runs)
- [ ] ⬜ **Task 5.7**: Full QA + daemon restart

**Success gate**: Upgrade-cycle test passes for every prior tag. Runtime target met or nightly-job escape hatch in place.

---

### Phase 6: Documentation, Release Notes, Post-Upgrade Task

- [ ] ⬜ **Task 6.1**: Update `CLAUDE.md` Self-Install Mode section to reflect the single-SSOT resolver
- [ ] ⬜ **Task 6.2**: Update `CLAUDE/SELF_INSTALL.md` similarly
- [ ] ⬜ **Task 6.3**: Write post-upgrade task: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-venv-ssot-migration.md`
  - [ ] ⬜ Severity: `recommended`
  - [ ] ⬜ Tells users: first upgrade will delete `untracked/venv/` (legacy) and rebuild the fingerprint-keyed venv
  - [ ] ⬜ Also: if on a host where `python3` is older than `requires-python`, set `HOOKS_DAEMON_PYTHON=...` (Phase 0 fix makes this actionable)
- [ ] ⬜ **Task 6.4**: Changelog entries under Fixed + Changed — reference Plan 00100 explicitly and cite five prior releases it supersedes
- [ ] ⬜ **Task 6.5**: Release notes: **no further venv fixes planned after this release**
- [ ] ⬜ **Task 6.6**: Full QA, daemon restart, acceptance tests, `/release`

**Success gate**: `/release` skill runs end-to-end. Step 12 (acceptance tests) passes. Step 8 (QA gate) passes including upgrade-cycle test.

---

## Dependencies

- **Depends on**: Plan 00099 (Python-Fingerprint Venv Isolation) — v3.7.0
- **Supersedes runtime bugs shipped in**: v3.1.1, v3.7.0, v3.8.0, v3.8.1, v3.8.2
- **Blocks**: Nothing — this is a cleanup plan

## Technical Decisions

### Decision 1: Python SSOT over bash SSOT

**Context**: Four resolvers must collapse to one.
**Decision**: Python SSOT with bash thin wrappers shelling out via `python -m ... paths resolve-venv`.
**Trade-off**: ~50ms bash → python startup cost on install/upgrade/CLI paths. Hot path unaffected (Plan 00018).
**Date**: 2026-04-23 | **Unchanged from v1**

### Decision 2 (REVISED): Lockfile hash over daemon version for stamp

**Context**: `.daemon-version` missed dep changes without version bumps (v3.1.1's bug).
**v1 flaw**: Assumed `uv.lock` existed. It does not.
**v2 Decision**: Commit `uv.lock` (generated via `uv lock`) as a first-class repo artefact. Stamp = `sha256(pyproject.toml + uv.lock)`. CI enforces `uv lock --check`. Human-readable `daemon_version` field retained in the metadata JSON for debug visibility (advisory, not authoritative).
**Trade-off**: Adds a lockfile to the repo, requires `uv lock` workflow for dep changes. Cost is minimal and aligns with other ecosystems (Cargo.lock, poetry.lock).
**Date**: 2026-04-23

### Decision 3 (REVISED): Persist installer's Python; fall back gracefully on missing

**Context**: v3.8.1's scan fallback existed because installer's fingerprint disagreed with resolver's.
**v1 flaw**: "Fail on missing persisted Python" breaks legitimate OS-upgrade scenarios.
**v2 Decision**: Persist `sys.executable` in `.daemon-metadata.json`. Resolver reads it. If the persisted path no longer exists (e.g. OS upgrade replaced 3.13 with 3.14), fall back to running `find_compatible_python`, log the fallback clearly, and rebuild the venv under the new Python. Only error if no compatible Python is found, with an actionable message.
**Trade-off**: Small amount of additional logic in the resolver. Acceptable for UX.
**Date**: 2026-04-23

### Decision 4 (NEW in v2): Atomic metadata writes via single JSON + rename

**Context**: v1 wrote four separate files; interruption mid-write would leave a partial state.
**Decision**: Single `.daemon-metadata.json` with all fields. Write to `.daemon-metadata.json.tmp`, then `os.replace()` / `mv` atomically.
**Trade-off**: One file instead of four. Slight schema rigidity — future fields require JSON migration, but pydantic handles this cleanly.
**Date**: 2026-04-23

### Decision 5 (NEW in v2): Fix `uv sync` race via `sync(1)` + hardlink-first, not retry

**Context**: v1 proposed 3×500ms retry loop in `verify_venv`.
**v1 flaw**: Symptom treatment. Adds latency (up to 4.5s worst case) and still fails on slow filesystems.
**v2 Decision**: Two independent mitigations at the correct layer:

1. After `uv sync` exits, call `sync -f "$venv_path"` on Linux (filesystem-scoped flush) or `sync` on macOS/fallback. Force metadata flush before verification.
2. Switch `UV_LINK_MODE` default from `copy` to `hardlink` (works on native filesystems, faster, no rename race). Detect the overlay-fs "Failed to hardlink" warning and retry once with `UV_LINK_MODE=copy` — preserving Plan 00047's container-safety behaviour as a fallback, not the default.
   **Trade-off**: Slightly more complex invocation wrapper. Net latency *decreases* on most hosts.
   **Date**: 2026-04-23

### Decision 6 (NEW in v2): Fix PID/socket race at `cli.py:341`, not by reordering

**Context**: Field report hypothesised "socket first, PID second". Actual code does PID first, socket second, but parent's `time.sleep(0.5)` wait is too short on slow hosts.
**Decision**: Replace fixed sleep with polling loop (100ms × 50 iterations = 5s ceiling). Secondary: `restart_daemon_verified` falls back to socket-reachability check (via `get_daemon_status`) if PID poll times out. Tertiary: if `pgrep` shows the process alive, give it a 5-second grace period before declaring failure.
**Trade-off**: Slightly more complex startup verification. Latency on a *successful* fast startup unchanged (polling exits on first observation).
**Date**: 2026-04-23

---

## Success Criteria

- [ ] Phase 0: `verify_venv` succeeds on delayed-visibility filesystems without a retry loop (test passes)
- [ ] Phase 0: `restart_daemon_verified` succeeds when daemon child takes 1200ms to write PID (test passes)
- [ ] Phase 0: Skill wrapper emits actionable error + exact `HOOKS_DAEMON_PYTHON=...` command when `python3` < minimum, without touching daemon state
- [ ] Phase 0: The exact scenario on `/srv/example-app/front` (2026-04-23) runs clean end-to-end against HEAD
- [ ] Phase 3: `uv.lock` committed; CI `uv lock --check` passes
- [ ] Phase 3: Resolver falls back gracefully when persisted Python is missing (test passes)
- [ ] Grep: exactly one implementation of venv precedence lookup (Python, `paths.py`)
- [ ] Grep: zero production references to `untracked/venv/` as write target
- [ ] Grep: zero calls to `create_venv` or `recreate_venv`
- [ ] Tests: `test_full_upgrade_cycle.py` green for every prior released tag
- [ ] Tests: `test_venv_bash_functions.py` covers every bash helper via subprocess
- [ ] Tests: concurrency test passes 20/20 iterations
- [ ] Tests: same-project-two-pythons green
- [ ] QA: `./scripts/qa/run_all.sh` green, including (or referencing nightly) upgrade-cycle test
- [ ] Daemon: restarts successfully, status → RUNNING
- [ ] Release notes: "no further venv fixes after this release" commitment
- [ ] Six months post-release: zero venv-related patch releases

## Risks & Mitigations

| Risk                                                          | Impact | Probability | Mitigation                                                                                                                  |
| ------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------------------------------- |
| Upgrade-cycle test too slow, gets excluded from CI            | High   | Medium      | Task 5.0 spike first. If > 3 min, move to nightly with release-skill dependency. Decision at spike time, not execution time |
| `uv lock` generates non-deterministic output across platforms | Medium | Low         | uv is documented as deterministic. If drift observed, CI failure is explicit (not silent) and can be investigated           |
| Hardlink default breaks on overlay-fs users                   | Medium | Low         | Detect "Failed to hardlink" warning, fall back to copy. Plan 00047's users see no behaviour change                          |
| `sync -f` unavailable on macOS                                | Low    | High        | Fallback to plain `sync`. Acceptable cost on dev hosts                                                                      |
| `flock` fails under Podman bind-mount                         | High   | Medium      | Task 4.0 spike. PID-file lock fallback if needed                                                                            |
| Migration destroys a user's custom venv they hand-edited      | Medium | Low         | Post-upgrade task warns. Legacy deletion is logged. User can opt out via env var                                            |
| Polling loop in cli.py:341 races with signal handling         | Medium | Low         | Standard polling idiom; Python handles signals on each iteration. Existing 500ms sleep already has this property            |
| Four-resolver drift re-emerges post-merge                     | High   | Low         | Phase 2 deletes three. Grep-based CI check could catch regressions (consider in Phase 5)                                    |

## Effort

Each phase ships a checkpoint commit; the plan survives context compaction. Single focused push preferred over interleaving. Effort breakdown withheld to comply with project plan-time-estimate policy.

## Notes & Updates

### 2026-04-23 (v1 → v2 revision)

- Hostile Opus review (CRITIQUE-v1.md) identified 3 FATAL and 7 RISKY flaws in v1
- Three confirming investigations (uv.lock existence, daemon/server.py + cli.py trace, UV_LINK_MODE history) validated the review
- v2 corrections documented in the "v1 → v2 Changes" table at the top of this document
- User directive remains: "last chance to rectify this stupid situation. No more shitness. absolute correctness."

### 2026-04-23 (v1)

- Plan created. Three parallel investigation agents (venv-trace, venv-review, venv-test-audit) produced converging diagnoses
- Field report `untracked/hooks-daemon-upgrade-problems-python-version.md` added three new failure modes → Phase 0
