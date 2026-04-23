# Critique of PLAN-v1.md — Hostile Opus Review

**Date**: 2026-04-23
**Reviewer**: code-reviewer sub-agent (Opus)
**Verdict**: **Not ready for execution. Requires revision.**

Three FATAL findings and seven RISKY findings. The plan is architecturally directionally-correct — collapse resolvers, persist choices, gate CI — but the load-bearing specifics of *how* are wrong in enough places that executing as-written would produce a sixth patch release.

This document captures the review findings verbatim enough to drive v2 revisions. Each finding is cross-referenced with the follow-up investigations that confirmed or refined it.

---

## FATAL Findings

### FATAL-1: Lockfile-hash stamp assumes a file that does not exist

**Claim in v1**: Decision 2 and Tasks 3.1/3.4 specify `sha256(pyproject.toml + uv.lock)` as the new stamp input, replacing `.daemon-version`.

**Problem**: `uv.lock` does not exist in this repository. It is not in `.gitignore` — it has simply never been generated. `pyproject.toml` has no `[tool.uv]` section. `uv sync` generates an in-memory lockfile during resolution but does not persist it.

**Investigation confirmation** (post-review):

- Glob for `**/uv.lock` → zero results
- `.gitignore` does not mention `uv.lock`
- `pyproject.toml` uses standard setuptools, no `[tool.uv]`
- `scripts/install/venv.sh` lines 71, 84, 432, 445 all call `uv sync` — but no step writes the lockfile
- Every venv creation re-resolves deps from scratch

**Consequence of executing v1 as-written**: Phase 3 would compute `sha256(pyproject.toml + <missing file>)` which would either error out or hash an empty string. The stamp would not actually protect against dep drift. v3.1.1's bug would still ship.

**Required fix in v2**: Either (a) commit `uv.lock` generated via `uv lock`, update `.gitignore` to explicitly permit it, add CI step to verify `uv.lock` matches `pyproject.toml`; or (b) drop the `uv.lock` component and stamp with `sha256(pyproject.toml)` alone (accepting that transitive version changes within a `>=` constraint won't be detected); or (c) drop dep-drift detection entirely and keep `.daemon-version`. Recommendation: (a), with `uv lock` added to CI.

---

### FATAL-2: PID/socket race is misdiagnosed

**Claim in v1**: Task 0.2 states that the daemon "writes socket at T+0 and PID at T+500ms" and proposes polling socket OR PID.

**Problem**: Reading `src/claude_code_hooks_daemon/daemon/server.py` shows the opposite. Line 340 writes the PID file. Lines 349–351 then call `asyncio.start_unix_server()`. Line 366 logs "Daemon listening". The PID is written *before* the socket, not after.

**Investigation confirmation** (post-review, tracing `cli.py` start flow):

- `cli.py` line 338–339: first fork
- `cli.py` line 341: parent does `time.sleep(0.5)` — fixed 500ms regardless of child progress
- `cli.py` line 342: parent calls `read_pid_file()` and returns based on its existence
- Child must: import DaemonController + HooksDaemon, load config, initialise handlers, start asyncio loop, call `_write_pid_file()` — *all within 500ms* for the parent to see success

**Root cause**: On a slow host (Fedora with many handlers, or any system under load), the child's PID-file write can slip past the parent's fixed 500ms wait. The field report correctly observed a timing failure but misattributed it to socket/PID ordering; the real race is `cli.py:341` vs the child's startup overhead.

**Consequence of executing v1 as-written**: Adding socket-poll does help incidentally (the socket is bound mid-startup), but the plan would leave the underlying fixed-sleep in place. On even slower hosts the same false-negative would reappear.

**Required fix in v2**: Replace fixed `time.sleep(0.5)` in `cli.py:341` with a proper polling loop (500ms interval × 10 attempts = 5s ceiling) that checks for PID file appearance. Keep socket-poll as a secondary check in `restart_daemon_verified` — not as the primary fix but as a belt-and-braces confirmation of readiness.

---

### FATAL-3: Retry loop treats the symptom, not the cause

**Claim in v1**: Task 0.1 proposes a 3×500ms retry on `[ ! -f "$venv_python" ]` in `verify_venv` to paper over the `uv sync` → file-visibility lag.

**Problem**: The lag is caused by `UV_LINK_MODE=copy` doing copy-then-rename. The correct fix is either to force a filesystem flush or to switch link mode. A retry loop adds up to 4.5s of latency per call and still fails on slow filesystems. It is a symptom treatment.

**Investigation confirmation** (post-review):

- `scripts/install/venv.sh:68` and `:429` hardcode `UV_LINK_MODE=copy`
- Commit `8285e7c` (2026-02-11, Plan 00047) set this deliberately to suppress overlay-fs warnings in containers
- Field host is a Fedora **native filesystem** ("hosted server" per report) — overlay-fs protection is not needed there
- Venv and uv cache are on the same filesystem (confirmed by field report paths) — hardlink would work
- `sync(1)` is available on Linux + macOS; `sync -f <path>` on Linux ≥ 2.36 is filesystem-scoped (avoids blocking on unrelated dirty buffers)

**Consequence of executing v1 as-written**: Retry loop usually works but adds latency; on a genuinely slow filesystem it still fails; on overlay-fs inside a container it is purely symptom treatment.

**Required fix in v2**: Either (a) call `sync -f "$venv_path"` (Linux) or `sync` (macOS fallback) after `uv sync` exits, before verification; or (b) change `UV_LINK_MODE=copy` → `UV_LINK_MODE=hardlink` with a try/fallback to `copy` if the warning re-emerges (hybrid approach per investigation 3); or (c) both. Recommendation: (c) — hybrid with explicit sync-after-uv. Remove the retry loop.

---

## RISKY Findings

### RISKY-1: Bootstrap case in Phase 2 is underspecified

**Claim in v1 Task 2.5**: The bootstrap case (`upgrade.sh:156-164` running before `src/` is checked out) is described as "a minimal inlined copy of the legacy-path lookup".

**Problem**: This is the only case where bash *must* resolve a venv without the Python SSOT being available. The plan calls it "the ONE intentional duplication" but does not specify what exactly is duplicated — is it the full 4-level precedence, just the fingerprint lookup, or just `untracked/venv`? Ambiguity here is how drift starts.

**Required fix in v2**: Specify the bootstrap fallback precisely. Recommendation: bootstrap resolves *only* to stop a running daemon (read PID path, send SIGTERM, done) — it does not need to resolve the venv at all. Refactor `upgrade.sh:156-164` to use PID-path → kill, then proceed to checkout.

### RISKY-2: Skill-wrapper Python pre-check creates a second source of truth for minimum Python

**Claim in v1 Task 0.3**: Skill wrapper checks `python3 --version` against `< 3.11`.

**Problem**: `pyproject.toml` already declares `requires-python = ">=3.11"` (authoritative). Hardcoding `3.11` in a bash script creates a second SoT that will drift when the project eventually bumps to 3.12.

**Required fix in v2**: Either (a) extract the minimum from `pyproject.toml` at pre-check time via `grep 'requires-python' pyproject.toml`; or (b) delegate the check to the Python SSOT via a tiny `python3 -c 'import sys; assert sys.version_info >= (3, 11)'` that reads the bound from a single constant. Avoid hardcoding.

### RISKY-3: Decision 3 "fail on missing persisted Python" contradicts legitimate UX

**Claim in v1 Decision 3**: "If the persisted Python no longer exists (user deleted it), resolution fails with a clear error pointing at the persisted path."

**Problem**: A user who upgrades their OS (Fedora 40 → 41) may have `/usr/bin/python3.13` replaced by `/usr/bin/python3.14`. The old persisted path is gone; this is legitimate, not a misconfiguration. Failing hard forces the user to manually delete the venv and rebuild.

**Required fix in v2**: On missing persisted Python, fall back to re-running `find_compatible_python` with a clear log message ("persisted Python /usr/bin/python3.13 missing — searching for compatible alternative"). Only fail hard if no compatible Python is found. Update Decision 3 wording.

### RISKY-4: Phase 5 "< 5 minutes" runtime claim is unproven

**Claim in v1 Task 5.1**: Parameterised over 5 prior tags (`v3.6.0` through `v3.8.2`), running `git worktree add`, install, daemon start, overlay HEAD, upgrade, daemon start — all within 5 minutes total.

**Problem**: Each case is a full install cycle. `uv sync` alone can take 30–60s on a cold cache. 5 cases × ~60s = 5 minutes just for `uv sync`, before factoring in the other steps.

**Required fix in v2**: Either (a) prove the target with a spike before committing the phase; or (b) drop the target, run the test nightly (not per-commit) with pytest-xdist parallelism. If kept in `run_all.sh`, cache the worktree setup via a pytest session fixture.

### RISKY-5: `flock` behaviour across container bind-mounts not verified

**Claim in v1 Task 4.2**: `flock` lockfile at `{daemon_dir}/untracked/.venv-bootstrap.lock`.

**Problem**: `flock` on Linux uses advisory locking via the VFS; across bind-mounts between host and container the behaviour is defined but can be surprising (locks on the same inode from both sides interact; locks on different inodes presented as the same path do not). The self-install mode commonly runs under Podman with `/workspace` bind-mounted.

**Required fix in v2**: Add a Phase 4 sub-task to verify `flock` behaviour under the supported runtime (Podman bind-mount). If behaviour is incorrect, switch to a file-presence lock with PID content and liveness check — uglier but bind-mount-safe.

### RISKY-6: Phase 3 metadata writes are not atomic

**Claim in v1 Task 3.3**: Writes `.daemon-python`, `.daemon-fingerprint`, `.daemon-lock-hash`, `.daemon-version` after `uv sync`.

**Problem**: If the writer is interrupted between file 1 and file 4, the venv dir contains some metadata but not all. The resolver then sees a partial state and must either heuristically repair or error out.

**Required fix in v2**: Write all four files via a temp-dir + atomic rename: write to `{venv}/.meta-tmp/`, then `mv .meta-tmp .meta` as a single directory rename. Or: write all four to a single `.daemon-metadata.json` file atomically. Recommendation: single JSON file (simpler, one rename, typed schema).

### RISKY-7: Task 1.5 vs Task 2.5 ordering conflict

**Claim in v1**: Task 1.5 adds a guard in `ensure_venv()` that refuses to create at legacy `untracked/venv/`. Task 2.5 introduces a bootstrap fallback that may need legacy-path awareness.

**Problem**: If Phase 1 lands before Phase 2's bootstrap design is finalised, the guard may reject the bootstrap path. If Phase 2 is completed first but Phase 1's guard is not added, Phase 1's rationale is weakened.

**Required fix in v2**: Sequence Task 1.5 AFTER Task 2.5. Or merge the two into a single cross-phase task. Alternative: the bootstrap fallback (per RISKY-1 fix) should not need to touch venv creation at all, in which case the conflict disappears.

---

## Required Fixes Checklist (for v2)

- [ ] Fix FATAL-1: commit `uv.lock` OR drop the `+ uv.lock` from the stamp
- [ ] Fix FATAL-2: replace `cli.py:341` fixed sleep with polling loop; keep socket-poll as secondary
- [ ] Fix FATAL-3: replace retry loop with `sync -f` + hybrid `UV_LINK_MODE` try/fallback
- [ ] Fix RISKY-1: specify bootstrap fallback precisely (recommendation: only PID/kill, no venv resolution)
- [ ] Fix RISKY-2: source minimum Python from `pyproject.toml`, not hardcoded
- [ ] Fix RISKY-3: on missing persisted Python, retry `find_compatible_python` before erroring
- [ ] Fix RISKY-4: prove Phase 5 runtime with spike OR move to nightly
- [ ] Fix RISKY-5: verify `flock` under Podman bind-mount
- [ ] Fix RISKY-6: atomic metadata write (single JSON file)
- [ ] Fix RISKY-7: sequence Task 1.5 after Task 2.5 OR merge

---

## Not Changed (Reviewer Endorsed)

The reviewer explicitly endorsed these v1 choices as correct:

- **Python SSOT over bash SSOT** (Decision 1): right call; bash wrappers shelling out to `python -m paths resolve-venv` is the correct architectural direction.
- **Four resolvers → one** (Phase 2 goal): the core consolidation is correct.
- **Dead code deletion** (Phase 1): `create_venv()` and `recreate_venv()` removal is unambiguously correct.
- **End-to-end upgrade-cycle test** (Phase 5 intent): the right shape of test, even if the runtime target needs revisiting.
- **Release-notes commitment** (Phase 6): "no further venv fixes" is the right public stance.
- **Dogfood-first phase** (Phase 0): landing the field-reported bugs before the architectural work is correct sequencing.

The v2 revision preserves these and corrects only the load-bearing specifics that the hostile review identified as broken.
