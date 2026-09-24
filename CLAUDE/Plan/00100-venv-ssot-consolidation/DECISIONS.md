# Plan 00100 — Decisions & Rationale

Durable detail extracted from `PLAN.md` (Plan 00100-shrink): revision
history tables, the field evidence that seeded Phase 0, and the full
Technical Decisions log with reasoning. Moved verbatim; see
[PLAN.md](PLAN.md) for current status and the task list.

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

## v2 → v3 Scope Expansion (2026-04-24)

User-driven corrections after re-examining the fingerprint scheme against real cross-env use. Each flips a v2/Plan-00099 assumption that doesn't survive contact with reality.

| v2 / Plan-00099 Assumption                                                                             | v3 Correction                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python fingerprint (`sys.version \| sys.base_prefix \| platform.machine()`) uniquely identifies an env | **Fingerprint collision case missed**: host at `/home/user/proj` and container bind-mounting that project at `/workspace` can both resolve Python at `/usr/bin/python3.11` with `sys.base_prefix="/usr"`. Identical fingerprint, different libc/ABI runtime. Wheels built on one corrupt the other — the exact bug Plan 00099 was meant to prevent. Fix: include a **human-readable path slug** derived from `HOOKS_DAEMON_ROOT_DIR` in the venv dir name. |
| Plan 00099 Decision 4: lazy rebuild of non-current venvs via stamp mismatch                            | **User directive**: `hooks-daemon upgrade` must leave a clean state. Eagerly delete ALL `untracked/venv-*/` except the current-fingerprint+lockhash match after the new venv is verified. Lazy rebuild preserved for *plain daemon start* (non-upgrade paths) where eager delete would surprise.                                                                                                                                                           |
| Plan 00099 Task 4.2 deferred: "conflates install/runtime, pays fingerprint cost every restart"         | Weak rationale. Cost is ~50ms one-time when venv is actually missing. **User directive**: auto-bootstrap inline when the situation is unambiguous; emit an LLM-guided hook otherwise. Preconditions-for-inline (all must hold): `uv` on PATH, `pyproject.toml` readable, `uv.lock` present, compatible Python resolvable, target dir writable.                                                                                                             |

## Field Evidence (2026-04-23)

A project agent running `/hooks-daemon upgrade` on `/srv/example-app` (Fedora, `python3`=3.9 incompatible, `python3.13` compatible) reported three **new** failure modes not caught by the code-review agents. See `/workspace/untracked/hooks-daemon-upgrade-problems-python-version.md`. The fingerprint venv dir `venv-py313-956ed987` was created correctly and the daemon eventually ran — but the upgrade script declared failure twice along the way, leaving the user to manually recover:

- **`verify_venv` race on `uv sync` file visibility**: `uv sync` exits 0, writes `bin/python`, but the immediate `[ ! -f "$venv_python" ]` check returns "not found" under `UV_LINK_MODE=copy`. The file was present seconds later. **Root cause** (v2): `UV_LINK_MODE=copy` does copy-then-rename; no post-uv `sync` call.
- **`restart_daemon_verified` false negative**: daemon log confirms `Daemon listening on ...` at 14:51:37, but the script's PID-file poll timed out fractionally earlier. **Root cause** (v2): `cli.py:341` uses a fixed `time.sleep(0.5)` before polling — insufficient for startup overhead on slow hosts. The real bottleneck is the child's startup time (imports + config load + handler init), not the PID/socket file ordering.
- **No pre-check for `python3` version in the skill wrapper**: on this host `python3`→3.9. The daemon's Layer 1 correctly found `/usr/bin/python3.13`, but transient downstream failures surfaced only after the daemon had been stopped. **Root cause** (v2): the skill-layer runs no Python version pre-check before disrupting daemon state.

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

### Decision 7 (NEW in v3): Human-readable path slug in venv dir name, not an MD5 hash

**Context**: Python fingerprint alone collides when host and container both resolve `/usr/bin/python3.11` with `sys.base_prefix="/usr"`. Need a second axis that distinguishes host view from container view of the same mounted project.
**Options**:

1. `md5(HOOKS_DAEMON_ROOT_DIR)[:8]` — opaque, requires lookup to debug
2. Slug: strip leading `/`, replace `/` with `_`, trim to 40 chars with 4-hex hash suffix only when truncated — readable, debuggable, collision-safe

**Decision**: Option 2. User directive: "pathhash is fine but keep it human readable not an md5". A directory name of `venv-home_user_projects_hooks-daemon-py311-2fa8b3c1/` reads out loud; `venv-a1b2c3d4-py311-2fa8b3c1/` does not.
**Trade-off**: Slightly longer dir names. Filesystem name-length cap (255 bytes) is untouchable; the 40-char cap + hash suffix handles the pathological case deterministically.
**Date**: 2026-04-24

### Decision 8 (NEW in v3): Eager venv cleanup on `upgrade`; lazy rebuild preserved on plain start

**Context**: Plan 00099 Decision 4 chose lazy rebuild for all non-current venvs via stamp mismatch — the concern was surprising users by deleting a host venv when a container started. But on `hooks-daemon upgrade` the user is explicitly acting on the project and expects a clean end-state.
**Decision**: Split the policy by path:

- `hooks-daemon upgrade`: after the new venv is built AND daemon restart verification passes, `rm -rf` every `untracked/venv-*/` whose absolute path != current venv path. Ordered AFTER restart so a failed upgrade rolls back.
- Plain daemon start (non-upgrade): unchanged — stamp mismatch triggers lazy rebuild of the *current* env only; other envs untouched until they themselves start.

**Trade-off**: Two behaviours instead of one. The difference is intentional and reflects intent (explicit upgrade vs implicit start).
**Date**: 2026-04-24

### Decision 9 (NEW in v3): Inline auto-bootstrap when preconditions are unambiguous; LLM-guided hook otherwise

**Context**: Plan 00099 Task 4.2 deferred on the argument that auto-bootstrap "conflates install/runtime, pays fingerprint cost every restart". Cost analysis: fingerprint ≈ 50ms *once*, only when venv absent. The real question is whether the daemon has enough information to bootstrap unambiguously.
**Decision**: Two-mode bootstrap guarded by a five-precondition gate:

1. `uv` on PATH
2. `pyproject.toml` readable
3. `uv.lock` present (Task 3.0)
4. `find_compatible_python` returns a Python matching `requires-python`
5. Target venv parent dir writable

All five hold → daemon runs `ensure_venv` inline on startup (180s timeout, streaming uv output).
Any fail → daemon surfaces actionable structured error + emits a SessionStart advisory handler (`venv_missing_advisor`, priority ~53) that tells the LLM agent precisely what to fix.
**Trade-off**: More code paths in startup. Mitigated by the precondition gate being a pure-Python predicate with 6 targeted unit tests.
**Date**: 2026-04-24
