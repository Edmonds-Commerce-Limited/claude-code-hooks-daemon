# Plan 00100: Venv SSOT Consolidation — Stop the Release Treadmill

**Status**: Not Started
**Created**: 2026-04-23
**Owner**: TBD
**Priority**: Critical
**Type**: Bug Fix / Architectural Consolidation
**Recommended Executor**: Opus (Sub-Agent Teams)
**Execution Strategy**: Sub-Agent Teams
**Predecessor**: Plan 00099 (Python-Fingerprint Venv Isolation) — shipped v3.7.0 and triggered the treadmill

## Field Evidence (2026-04-23)

A project agent running `/hooks-daemon upgrade` on `/srv/example-app` (Fedora, `python3`=3.9 incompatible, `python3.13` compatible) reported three **new** failure modes not caught by the code-review agents. See `/workspace/untracked/hooks-daemon-upgrade-problems-python-version.md` for the full timeline. The fingerprint venv dir `venv-py313-956ed987` was created correctly and the daemon eventually ran — but the upgrade script declared failure twice along the way, leaving the user to manually recover. Specifics:

- **`verify_venv` race on `uv sync` file visibility**: `uv sync` exits 0, writes `bin/python`, but the immediate `[ ! -f "$venv_python" ]` check returns "not found" under `UV_LINK_MODE=copy` on overlay/NFS/slow disk. No retry. The file was present seconds later.
- **`restart_daemon_verified` false negative**: daemon log confirms `Daemon listening on ...daemon-host-d.sock` at 14:51:37, but the script's PID-file poll timed out fractionally earlier and declared failure. The daemon was running (confirmed PID 5323) when the script aborted.
- **No pre-check for `python3` version in the skill wrapper**: on this host `python3`→3.9 (incompatible). The daemon's Layer 1 script correctly found `/usr/bin/python3.13`, but by the time any downstream transient failure surfaced, the daemon had already been stopped and the user had no clear "run with `HOOKS_DAEMON_PYTHON` set" guidance.

**These are field-proven failure modes, not hypothetical edge cases.** Plan 00100 lands them as Phase 0 — *before* the architectural consolidation — so the next release the user touches does not bite them again.

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

1. **Dead code is the seed.** `scripts/install/venv.sh` still exports `create_venv()` and `recreate_venv()` — legacy functions writing to `untracked/venv/`. Zero production callers, but every sourcer of `venv.sh` imports them. One accidental call seeds the scan-fallback with a stale legacy venv that then out-ranks the correct fingerprint-keyed path.
2. **The "SSOT" is four implementations.** `scripts/install/venv_resolver.sh`, `scripts/venv-include.bash:_resolve_venv_dir`, `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh`, and `src/.../daemon/paths.py:resolve_existing_venv_python` all implement the same 4-level precedence. `venv-include.bash` already has a 5th branch the others lack — drift has begun.
3. **The scan fallback papers over a real bug.** Fingerprint is computed from `sys.base_prefix`, stable across venv/system Python. If the installer's fingerprint and the resolver's fingerprint differ, the correct fix is to **persist the chosen Python inside the venv dir** and *read* it back — not scan for "any venv-\*". The fallback hides the real inconsistency.
4. **Stamp semantics are wrong.** `.daemon-version` tracks daemon version. A `pyproject.toml` edit without a version bump (v3.1.1's bug) is invisible. Also, downgrades destroy valid venvs.
5. **No concurrency protection.** Two daemons starting simultaneously both `rm -rf` and `uv sync` the same dir. No `flock`.
6. **Bash has zero CI coverage.** Every regression lived in bash. Python tests mock the bash. No end-to-end "install old tag → upgrade to HEAD → verify daemon RUNNING" test exists. That test would have caught every one of the five bugs above.

This plan eliminates the treadmill by **collapsing the four resolvers into one**, **deleting all dead paths**, **replacing the stamp with a lockfile hash**, **adding concurrency protection**, and **making bash changes CI-gated via a real end-to-end upgrade test**. No more venv releases after this one.

## Goals

- **Exactly one** venv resolver implementation (Python), with bash shelling out to it
- **Zero** legacy code paths in `venv.sh` — `create_venv()` and `recreate_venv()` deleted
- **Zero** scan fallbacks in steady state — resolver reads persisted `.daemon-python` + `.daemon-lock-hash` from inside the venv dir, never recomputes
- **Deterministic stamp semantics**: stamp = `sha256(pyproject.toml + uv.lock)`, not daemon version
- **Concurrency-safe**: `flock` around all `ensure_venv` mutations
- **CI-gated bash**: a pytest-integrated test that installs a prior released tag, upgrades to HEAD, and asserts `daemon status == RUNNING`
- **Clear error surfacing**: resolution failure cites every precedence step tried and the reason each failed

## Non-Goals

- Not revisiting the fingerprint *content* (python version + base_prefix + machine). That design is correct and Plan 00099 delivered it well.
- Not changing hostname-scoped socket/PID paths. That grain is correct.
- Not adding new CLI surface area beyond what's needed for testing. `list-venvs` / `prune-venvs` stay.
- Not migrating existing deployed venvs forcibly. Legacy `untracked/venv/` is deleted on first upgrade encounter, not eagerly.

## Context & Background

Investigation artefacts (do not repeat the work — read these for full context):

- **venv-trace** report (in conversation): 7 independent code paths, 6 different combinations of (write target, read precedence, fingerprint check, stamp check)
- **venv-review** report (in conversation): prioritised list of critical bugs (dead code, fallback-3 masking, legacy-path phantom returns, no flock, downgrade destruction) and design smells (four resolvers, source-time resolver in `venv-include.bash` under `pipefail`, duplicated cleanup)
- **venv-test-audit** report (in conversation): bash tests are `test_*_manual.sh`, not in CI; Python tests mock the bash; no e2e upgrade test exists

Key files (every one of these has a role in the treadmill):

- `/workspace/scripts/install/venv.sh` — dual creators (dead `create_venv` + live `ensure_venv`)
- `/workspace/scripts/install/venv_resolver.sh` — resolver #1 (install-time bash)
- `/workspace/scripts/install/python_fingerprint.sh` — fingerprint SSOT (this is correct; keep)
- `/workspace/scripts/venv-include.bash` — resolver #2 (init/QA bash) with drifted 5th branch
- `/workspace/scripts/upgrade.sh` — Layer 1 bootstrap that bypasses all resolvers (lines 156-164)
- `/workspace/scripts/upgrade_version.sh` — Layer 2 upgrade flow
- `/workspace/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh` — resolver #3 (skill wrappers)
- `/workspace/src/claude_code_hooks_daemon/daemon/paths.py` — resolver #4 (Python runtime)

## Execution Strategy

Opus orchestrates a team. Each phase lands a green state before the next begins. No phase merges on top of a broken baseline.

**Roles**:

- **Architect (Opus main thread)**: phase planning, design decisions, code review of each phase
- **Bash consolidator (sub-agent)**: phases 1, 3
- **Python consolidator (sub-agent)**: phase 2
- **Test engineer (sub-agent)**: phases 4, 5
- **QA/release integrator (sub-agent)**: phase 6

**Checkpoint commits** after every phase. QA green + daemon restart RUNNING is the per-phase gate.

## Phases

### Phase 0: Field-Pain Fixes (LAND FIRST)

**Why first**: three field-proven bugs from the 2026-04-23 report. Every user upgrading today can hit them. Fixing them before the architectural consolidation means the consolidation inherits a stable baseline.

- [ ] ⬜ **Task 0.1**: `verify_venv` retry loop for `uv sync` file-visibility race
  - [ ] ⬜ Write failing test: `tests/integration/test_verify_venv_retry.py` — simulate a delayed-visibility filesystem by writing `bin/python` after a 200ms sleep; assert `verify_venv` succeeds via retry
  - [ ] ⬜ Implement retry in `scripts/install/venv.sh:verify_venv()`: 3 attempts × 500ms backoff on `[ ! -f "$venv_python" ]`
  - [ ] ⬜ Also retry on `[ ! -x "$venv_python" ]` and `--version` check (same race class)
  - [ ] ⬜ Distinguish "transient" log (`print_verbose`) from "final failure" log (`print_error`) so the user sees clear intent on genuine failure
- [ ] ⬜ **Task 0.2**: `restart_daemon_verified` should poll the socket, not just the PID file
  - [ ] ⬜ Write failing test: simulate daemon that writes socket at T+0 and PID at T+500ms; assert verification succeeds inside 1s
  - [ ] ⬜ Update `scripts/install/daemon_control.sh:restart_daemon_verified()` to poll for EITHER socket file OR PID file presence (daemon is functionally ready when socket exists)
  - [ ] ⬜ Extend overall timeout to 15s (current: likely 5s); log progress every 1s so user sees "waiting for daemon" instead of silent failure
  - [ ] ⬜ If timeout expires but daemon process is visible via `pgrep`, log a "running but not yet ready — continuing" message, don't abort
- [ ] ⬜ **Task 0.3**: Skill-wrapper Python version pre-check
  - [ ] ⬜ Write failing test: run the skill wrapper with `PATH` containing only a stubbed `python3`=3.9; assert clear error and no daemon stop
  - [ ] ⬜ Update `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh` (and install.sh if applicable) to check `python3 --version` BEFORE stopping the daemon
  - [ ] ⬜ If `python3` < 3.11, emit a clear message naming a compatible Python found on PATH (if any) and the exact `HOOKS_DAEMON_PYTHON=...` command to re-run; exit 1 without touching daemon state
  - [ ] ⬜ Use `find_compatible_python` logic from Layer 1, but surface it at Layer 0 (the skill) for fail-fast
- [ ] ⬜ **Task 0.4**: Clear error surfacing across all three fixes
  - [ ] ⬜ Error messages must include: what was checked, what was found, what to do next (exact command)
  - [ ] ⬜ No silent truncation, no "try again later" without a concrete next step
- [ ] ⬜ **Task 0.5**: Full QA + daemon restart + add the three new tests to `run_all.sh`

**Success gate**: The three field-reported scenarios are covered by passing tests. The user's original `/hooks-daemon upgrade` command, re-run against HEAD on a host with `python3`=3.9 and `python3.13`=3.13.11, either succeeds cleanly OR fails with actionable messaging and leaves the daemon state unchanged (no partial stop).

### Phase 1: Delete Dead Code (BLEED STOPPER)

**Why first**: every future phase is easier once the legacy path is impossible to reach.

- [ ] ⬜ **Task 1.1**: Grep for all callers of `create_venv`, `recreate_venv`, and any hardcoded `untracked/venv/` string across the entire tree (including `src/`, `scripts/`, `tests/`, `docs/`)
  - [ ] ⬜ Produce a caller list with file:line
  - [ ] ⬜ Classify each: production, test, docs, dead
- [ ] ⬜ **Task 1.2**: Delete `create_venv()` and `recreate_venv()` from `scripts/install/venv.sh`
  - [ ] ⬜ Delete `scripts/install/test_venv_manual.sh` (tested dead functions)
  - [ ] ⬜ Update any sourcer that referenced them
- [ ] ⬜ **Task 1.3**: Remove the legacy-fallback step (step 4, `untracked/venv/bin/python`) from all resolvers
  - [ ] ⬜ After phase 2 lands, there is exactly one resolver — this becomes a one-line deletion then
  - [ ] ⬜ For this phase, mark the fallback path with a `# TODO phase 2: remove` comment and a deprecation log line
- [ ] ⬜ **Task 1.4**: Delete the `venv-include.bash` 5th branch drift
  - [ ] ⬜ Verify it was never load-bearing (scan branch covers it)
- [ ] ⬜ **Task 1.5**: Add a guard in `ensure_venv()` that refuses to create at the legacy path: if `venv_path` ends in `/untracked/venv` (no fingerprint suffix), FAIL FAST with a loud error
- [ ] ⬜ **Task 1.6**: Write failing test FIRST, then verify fix: `tests/integration/test_legacy_path_refused.py` — confirms `ensure_venv` cannot produce `untracked/venv/`
- [ ] ⬜ **Task 1.7**: Full QA + daemon restart verification

**Success gate**: `./scripts/qa/run_all.sh` green. `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` → RUNNING. Grep for `untracked/venv\"` (legacy path as bare string) returns zero hits outside of cleanup/migration logic.

### Phase 2: Collapse Four Resolvers Into One Python SSOT

**Why**: drift is inevitable with four parallel implementations. Collapsing to one eliminates an entire class of bugs.

- [ ] ⬜ **Task 2.1**: Design a single Python entry point: `python -m claude_code_hooks_daemon.daemon.paths resolve-venv [--python PYTHON] [--daemon-dir DIR]`
  - [ ] ⬜ Output: single line, the venv python path, exit 0 on success
  - [ ] ⬜ On failure: stderr cites every precedence step tried and why each failed; exit 1
- [ ] ⬜ **Task 2.2**: Write failing unit tests for the entry point covering every precedence and every failure mode (stamp missing, stamp corrupt, `.daemon-python` missing, fingerprint mismatch, interpreter missing)
- [ ] ⬜ **Task 2.3**: Implement the entry point in `src/claude_code_hooks_daemon/daemon/paths.py`
  - [ ] ⬜ Uses persisted `.daemon-python` and `.daemon-lock-hash` from inside the venv dir (written in phase 3)
  - [ ] ⬜ No scan fallback. Explicit lookup only.
- [ ] ⬜ **Task 2.4**: Replace each bash resolver with a thin wrapper that shells out to the Python SSOT
  - [ ] ⬜ `scripts/install/venv_resolver.sh` → calls `python -m ... paths resolve-venv`
  - [ ] ⬜ `scripts/venv-include.bash` → same
  - [ ] ⬜ `src/.../skills/hooks-daemon/scripts/_resolve-venv.sh` → same
  - [ ] ⬜ Each wrapper is < 20 lines, calls the Python SSOT, falls through only if the SSOT itself is missing (i.e. daemon not yet installed — legitimate bootstrap case with a single well-defined fallback)
- [ ] ⬜ **Task 2.5**: Handle the bootstrap case: `upgrade.sh:156-164` runs before `src/` is checked out. The bootstrap fallback is a minimal inlined copy of the legacy-path lookup, explicitly scoped to "find whatever venv exists to stop it before upgrade". Document this as the ONE intentional duplication with a comment linking to Plan 00100.
- [ ] ⬜ **Task 2.6**: Full QA + daemon restart + re-run phase 1 tests

**Success gate**: Grep for `resolve_existing_venv_python` returns exactly one definition (Python). Bash wrappers each < 20 lines. All Phase 1 tests still pass.

### Phase 3: Persist Installer Choices Inside Venv (Eliminate Recompute Disagreement)

**Why**: the recomputed-fingerprint mismatch that v3.8.1 papered over becomes impossible if the resolver *reads* the installer's choice instead of recomputing.

- [ ] ⬜ **Task 3.1**: Design persisted metadata files inside venv dir:
  - [ ] ⬜ `.daemon-python`: absolute path of the Python binary the installer used
  - [ ] ⬜ `.daemon-fingerprint`: the fingerprint the installer computed (for verification, not authority)
  - [ ] ⬜ `.daemon-lock-hash`: `sha256(pyproject.toml + uv.lock)` at install time (replaces `.daemon-version` stamp)
  - [ ] ⬜ `.daemon-version`: kept for backwards-compat readability (humans reading the directory), but not used for matching logic
- [ ] ⬜ **Task 3.2**: Write failing tests for each metadata file's write and read
- [ ] ⬜ **Task 3.3**: Update `ensure_venv()` and `create_venv_at_path()` to write all four files after successful `uv sync`
- [ ] ⬜ **Task 3.4**: Update the Python SSOT resolver (from Phase 2) to:
  - [ ] ⬜ Read `.daemon-python` and use that as the authoritative interpreter path
  - [ ] ⬜ Compare `.daemon-lock-hash` against `sha256(current pyproject.toml + uv.lock)`; mismatch → rebuild
  - [ ] ⬜ Never recompute fingerprint for lookup (fingerprint stays a directory-naming convenience; it is not authoritative)
- [ ] ⬜ **Task 3.5**: Migration: if a venv has `.daemon-version` but no `.daemon-lock-hash`, treat as stale → rebuild. Log clearly.
- [ ] ⬜ **Task 3.6**: Downgrade safety: if `.daemon-lock-hash` matches, do NOT rebuild on version change. Existing venv is valid.
- [ ] ⬜ **Task 3.7**: Full QA + daemon restart + all prior phase tests

**Success gate**: A venv built at HEAD on python 3.13 and then queried under python3=3.11 on PATH resolves correctly via `.daemon-python` without any scan fallback.

### Phase 4: Concurrency Protection (flock)

- [ ] ⬜ **Task 4.1**: Write failing test: two processes calling `ensure_venv` simultaneously do not corrupt the venv
  - [ ] ⬜ Uses `multiprocessing` or `subprocess.Popen` pairs
  - [ ] ⬜ Asserts second process waits for first, then fast-paths
- [ ] ⬜ **Task 4.2**: Implement `flock` around the mutating section of `ensure_venv()`
  - [ ] ⬜ Lock file: `{daemon_dir}/untracked/.venv-bootstrap.lock`
  - [ ] ⬜ Timeout with clear error if lock held > 120s
- [ ] ⬜ **Task 4.3**: Python-side equivalent via `fcntl.flock` for any Python code path that might mutate venv state (CLI `repair` command)
- [ ] ⬜ **Task 4.4**: Full QA + daemon restart + all prior phase tests

**Success gate**: Concurrency test passes deterministically over 20 iterations.

### Phase 5: End-to-End Upgrade Test (The Test That Would Have Caught Every Bug)

**Why**: this is the single most load-bearing piece of work in the plan. Without it, phase 6's release ships blind.

- [ ] ⬜ **Task 5.1**: Design `tests/integration/test_full_upgrade_cycle.py`
  - [ ] ⬜ Parameterised over prior released tags: `v3.6.0`, `v3.7.0`, `v3.8.0`, `v3.8.1`, `v3.8.2`
  - [ ] ⬜ Each case: `git worktree add` at that tag into a tmpdir, run its install, verify daemon starts, then overlay HEAD, run upgrade, verify daemon starts
  - [ ] ⬜ Run under a controlled Python version (the test's own)
- [ ] ⬜ **Task 5.2**: Write it as failing first against current HEAD (it should reveal any remaining split brain)
- [ ] ⬜ **Task 5.3**: Promote `scripts/install/test_venv_manual.sh` deletion to real pytest tests that exercise the bash functions via `subprocess`
  - [ ] ⬜ `tests/integration/test_venv_bash_functions.py`
- [ ] ⬜ **Task 5.4**: Add a second parameterised test: same-project-different-python
  - [ ] ⬜ Create two venvs at different fingerprints, switch between them, verify each resolves correctly
- [ ] ⬜ **Task 5.5**: Wire both tests into `./scripts/qa/run_all.sh` (not a separate slow suite — if it takes too long, optimise, don't separate; separation is how they got skipped before)
- [ ] ⬜ **Task 5.6**: Update `CLAUDE/development/RELEASING.md` Step 8 QA Gate to explicitly require the upgrade-cycle test pass
- [ ] ⬜ **Task 5.7**: Full QA + daemon restart

**Success gate**: `run_all.sh` runs the upgrade-cycle test and it passes for every prior tag. CI time increase acceptable (< 5 minutes).

### Phase 6: Documentation, Release Notes, and Post-Upgrade Task

- [ ] ⬜ **Task 6.1**: Update `CLAUDE.md` Self-Install Mode section to reflect the single-SSOT resolver and remove legacy-path mentions
- [ ] ⬜ **Task 6.2**: Update `CLAUDE/SELF_INSTALL.md` similarly
- [ ] ⬜ **Task 6.3**: Write post-upgrade task: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-venv-ssot-migration.md`
  - [ ] ⬜ Severity: `recommended`
  - [ ] ⬜ Tells users: first upgrade on this version will delete `untracked/venv/` (legacy) and rebuild the fingerprint-keyed venv. Expected. One-time cost.
- [ ] ⬜ **Task 6.4**: Changelog entries under Fixed + Changed — reference Plan 00100 explicitly and cite the five prior releases it supersedes
- [ ] ⬜ **Task 6.5**: Release notes call out: **no further venv fixes planned after this release**
- [ ] ⬜ **Task 6.6**: Full QA, daemon restart, acceptance tests, `/release`

**Success gate**: `/release` skill runs end-to-end. Step 12 (acceptance tests) passes. Step 8 (QA gate) passes including new upgrade-cycle test.

## Dependencies

- **Depends on**: Plan 00099 (Python-Fingerprint Venv Isolation) — shipped v3.7.0, delivered the fingerprint design this plan builds on
- **Supersedes runtime bugs shipped in**: v3.1.1, v3.7.0, v3.8.0, v3.8.1, v3.8.2
- **Blocks**: Nothing — this is a cleanup plan, not a feature path

## Technical Decisions

### Decision 1: Python SSOT over bash SSOT

**Context**: Four resolvers must collapse to one. Which language?
**Options Considered**:

1. Bash SSOT — requires every caller to source a specific helper; Python side still needs its own implementation
2. Python SSOT with bash thin wrappers — bash calls `python -m ... paths resolve-venv`; one implementation of the precedence logic

**Decision**: Option 2. The Python side already has `paths.py`, tests are easier, logic is clearer. Bash wrappers become thin and obviously-correct.
**Trade-off**: Bash wrappers pay a `python3` startup cost (~50ms). Acceptable for install/upgrade; hot-path already decoupled by Plan 00018.
**Date**: 2026-04-23

### Decision 2: Lockfile hash over daemon version for stamp

**Context**: `.daemon-version` stamp missed dependency changes without version bumps (v3.1.1's bug).
**Decision**: Stamp = `sha256(pyproject.toml + uv.lock)`. Deterministic, catches every dep change, survives downgrades.
**Trade-off**: Version is no longer the stamp. Human reading the directory loses that visual. Mitigation: write both — `.daemon-version` (human-readable, advisory) and `.daemon-lock-hash` (authoritative).
**Date**: 2026-04-23

### Decision 3: Persist installer's Python; no recompute

**Context**: v3.8.1 added a scan fallback because the installer's fingerprint and the resolver's fingerprint disagreed.
**Decision**: The installer's chosen `sys.executable` is persisted at `.daemon-python`. The resolver reads it. No recompute, no scan, no fallback-3.
**Trade-off**: If the persisted Python no longer exists (user deleted it), resolution fails with a clear error pointing at the persisted path. This is correct behaviour — better than silently picking a wrong venv.
**Date**: 2026-04-23

## Success Criteria

- [ ] Phase 0: `verify_venv` retries successfully on delayed-visibility filesystems (test passes)
- [ ] Phase 0: `restart_daemon_verified` succeeds when the daemon writes socket before PID (test passes)
- [ ] Phase 0: Skill wrapper emits a clear pre-check error + exact `HOOKS_DAEMON_PYTHON=...` command when `python3` < 3.11, without touching daemon state
- [ ] Phase 0: The exact scenario reported on `/srv/example-app` (2026-04-23) runs clean end-to-end against HEAD
- [ ] Grep: exactly one implementation of venv precedence lookup across the tree (Python, in `paths.py`)
- [ ] Grep: zero production references to `untracked/venv/` as a write target
- [ ] Grep: zero calls to `create_venv` or `recreate_venv`
- [ ] Tests: `test_full_upgrade_cycle.py` green for every prior released tag
- [ ] Tests: `test_venv_bash_functions.py` covers every bash helper via subprocess
- [ ] Tests: concurrency test passes 20/20 iterations
- [ ] Tests: same-project-two-pythons test green
- [ ] QA: `./scripts/qa/run_all.sh` green, including upgrade-cycle test
- [ ] Daemon: restarts successfully, `status` → RUNNING
- [ ] Release notes: explicit "no further venv fixes after this release" commitment
- [ ] Six months post-release: zero venv-related patch releases

## Risks & Mitigations

| Risk                                                                | Impact | Probability | Mitigation                                                                                                                                           |
| ------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Upgrade-cycle test too slow, gets excluded from CI                  | High   | Medium      | Target < 5min total. Cache the `git worktree` setup across cases. If too slow, optimise — do not split it off                                        |
| Migration destroys a user's custom venv they hand-edited            | Medium | Low         | Post-upgrade task warns. Legacy `untracked/venv/` deletion is logged, not silent. User can opt out via env var                                       |
| Python 3 startup cost in bash wrappers slows hook hot path          | High   | Low         | Hot path already uses system python3 (Plan 00018). Wrappers only fire at install/upgrade/CLI, not per-hook                                           |
| Lockfile hash changes every time uv re-resolves (non-deterministic) | Medium | Low         | uv.lock is deterministic by design. If drift observed, fall back to hashing pyproject.toml only                                                      |
| Four-resolver drift re-emerges post-merge                           | High   | Low         | Phase 2 deletes three of them. Future PRs adding resolver code will be caught in review (new Python code in `paths.py` is reviewed by the same eyes) |

## Timeline

- Phase 1 (dead code): ~4 hours
- Phase 2 (SSOT collapse): ~8 hours
- Phase 3 (persist metadata): ~6 hours
- Phase 4 (flock): ~3 hours
- Phase 5 (e2e tests): ~8 hours
- Phase 6 (release): ~4 hours

Total: ~33 hours. Single focused push preferred over interleaving with other work. Each phase ships a checkpoint commit; the plan survives context compaction.

## Notes & Updates

### 2026-04-23

- Plan created. Origin: user frustration after v3.8.2 still left venv confusion. Three parallel investigation agents (venv-trace, venv-review, venv-test-audit) produced converging diagnoses. This plan is the consolidated response.
- User directive: "last chance to rectify this stupid situation. No more shitness. absolute correctness."
- Interpretation: zero tolerance for residual split-brain, zero tolerance for missing test coverage, zero tolerance for "probably works" after this release.
