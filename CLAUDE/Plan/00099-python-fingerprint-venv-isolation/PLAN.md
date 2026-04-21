# Plan 00099: Python-Fingerprint Venv Isolation

**Status**: In Progress
**Created**: 2026-04-21
**Started**: 2026-04-21
**Owner**: TBD
**Priority**: High
**Type**: Bug Fix / Architectural Enhancement
**Recommended Executor**: Sonnet (Sub-Agent Orchestration)
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: (to be opened — relates to closed #15 and open #28)

## Overview

Projects are increasingly opened from two places on the same developer machine:

1. **Mounted inside a YOLO container** (podman/docker) — typically running a distro Python (e.g. Fedora 3.11 at `/usr/bin/python3`) with overlayfs at `/workspace`. Container HOSTNAME is an **ephemeral 12-char hex ID** that changes every launch.
2. **Directly on the desktop host** — a different Python binary at a different absolute path (e.g. `/home/user/.pyenv/versions/3.13.x/bin/python`) with incompatible bytecode, native wheels, and `.pth` files.

Currently every install writes the venv to one shared path: `{HOOKS_DAEMON_ROOT_DIR}/untracked/venv/`. Because that directory is persisted on the host filesystem and bind-mounted into the container, **both environments stomp on the same venv**. The first environment to run does `uv sync`; the second sees a venv whose Python binary / `.pth` files / compiled wheels point at paths that don't resolve — leading to `ModuleNotFoundError`, `cannot import claude_code_hooks_daemon`, or silent wrong-Python execution.

Plan 00018 (completed) already solved the *runtime* side of this — hook scripts use system `python3`, and socket/PID files are isolated per hostname: `daemon-{hostname}.sock`, `daemon-{hostname}.pid`. That grain is **correct for concurrent live processes** (each container needs its own socket) but **wrong for venvs** — container HOSTNAMEs are ephemeral hex IDs, so hostname-keyed venvs would create a fresh directory on every container launch and accumulate hundreds of dead venvs.

This plan keys venvs by a **Python environment fingerprint** instead: `md5(python_version + sys.executable + platform.machine())[:8]` → `venv-py311-2fa8b3c1/`. Concurrent containers from the same image share one venv. The desktop host gets its own. Cross-arch is bulletproof. Socket/PID paths **remain hostname-scoped** (correct grain for live processes — unchanged by this plan).

The existing `.daemon-version` stamp mechanism in `venv.sh` (already implemented: `VENV_VERSION_STAMP`, `stamp_venv_version()`, `get_venv_version()`, `venv_version_matches()`) is the lynchpin that handles upgrade invalidation across non-active envs.

## Goals

- Each unique Python environment fingerprint gets its own isolated venv directory
- Concurrent containers from the same image share one venv (no per-launch churn)
- Installs/upgrades/repairs touch only the current env's venv
- On upgrade, stamp the current env's venv with the new daemon version; other envs' venvs auto-rebuild on next use via stamp mismatch
- Auto-bootstrap: if no venv exists for the current env, create one automatically on daemon start
- CI-safe: CI path stubs instead of triggering venv create/upgrade
- Existing runtime files (socket/PID) keep working unchanged — hostname scoping preserved
- Graceful migration: existing `untracked/venv/` is treated as legacy, migrated on first upgrade
- Zero new runtime dependencies

## Non-Goals

- No change to the hot path (Plan 00018 already decoupled it — socket client uses system `python3`)
- No change to the daemon socket/PID path scheme — **explicitly preserved as hostname-scoped**
- No cross-fingerprint venv sharing optimisation (each venv is fully independent)
- Not solving Issue #28 directly, though the repair path this plan produces makes #28 easier to fix

## Context & Background

### Why Ephemeral Container HOSTNAMEs Break Hostname-Keyed Venvs

`/workspace/untracked/` currently contains 5 live-or-stale daemon sockets from container instances:

```
daemon-12a27a246032.sock   (container instance 1 — ephemeral ID)
daemon-4cd450365396.sock   (current container — ephemeral ID)
daemon-8f9345f744b7.sock   (container instance 2 — ephemeral ID)
daemon-e32205e55881.sock   (container instance 3 — ephemeral ID)
daemon-f2a3a564bbe8.sock   (container instance 4 — ephemeral ID)
```

Every time you launch a YOLO container, it gets a brand-new 12-char hex HOSTNAME. Sockets/PIDs being ephemeral is **fine** — they're cheap files, cleaned up when the daemon stops. But creating a 150-250MB venv per launch is not fine. Hostname-keyed venvs were wrong for this axis of the problem.

### What Python Fingerprint Captures

The fingerprint is `md5(python_version + sys.executable + platform.machine())[:8]`, prefixed with a human-readable `py{MAJOR}{MINOR}-` tag:

| Input component      | Example                                       | Why included                                                                                              |
| -------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `python_version`     | `3.11.5`                                      | ABI differs across minor versions; wheels keyed by it                                                     |
| `sys.executable`     | `/usr/bin/python3.11` or `/home/x/.pyenv/...` | Different Pythons with same version (distro vs pyenv) are distinct; absolute path baked into `.pth` files |
| `platform.machine()` | `x86_64`, `aarch64`                           | Cross-arch safety (e.g. x86 host opens project, then ARM container)                                       |

Example outputs:

- Container Python 3.11 at `/usr/bin/python3.11`, `x86_64` → `py311-2fa8b3c1`
- Desktop pyenv Python 3.13 at `/home/joe/.pyenv/versions/3.13.1/bin/python3.13`, `x86_64` → `py313-9d4e0f82`
- Same container relaunched → same fingerprint → same venv reused ✅

### What's Already Hostname-Isolated (UNCHANGED BY THIS PLAN)

From `init.sh`, via `_get_hostname_suffix()`:

```bash
SOCKET_PATH="$_untracked_dir/daemon${_hostname_suffix}.sock"
PID_PATH="$_untracked_dir/daemon${_hostname_suffix}.pid"
```

These stay hostname-scoped. Each concurrent container still gets its own socket — **correct grain for concurrent live processes**. Only the venv path changes.

### The Venv Version Stamp Mechanism (Already Active)

`scripts/install/venv.sh` already implements:

```bash
VENV_VERSION_STAMP=".daemon-version"

stamp_venv_version()      # writes daemon version into venv/.daemon-version
get_venv_version()        # reads it back
venv_version_matches()    # compares to target version
```

This is the trigger mechanism for rebuilds across envs: every venv carries a stamp recording which daemon version it was built for. On daemon start in any env, if stamp != current daemon version → rebuild.

### The Fix in One Sentence

Replace `untracked/venv/` with `untracked/venv-py{MM}-{fingerprint}/`, keyed by the Python env, and use the existing `.daemon-version` stamp to auto-invalidate stale venvs on upgrade.

## Proposed Architecture

### Path Scheme

| Purpose                | Before                             | After                                           |
| ---------------------- | ---------------------------------- | ----------------------------------------------- |
| Venv directory         | `untracked/venv/`                  | `untracked/venv-py311-2fa8b3c1/`                |
| Python binary          | `untracked/venv/bin/python`        | `untracked/venv-py311-2fa8b3c1/bin/python`      |
| Version stamp          | `untracked/venv/.daemon-version`   | `untracked/venv-py311-2fa8b3c1/.daemon-version` |
| Socket (**unchanged**) | `untracked/daemon-{hostname}.sock` | `untracked/daemon-{hostname}.sock`              |
| PID (**unchanged**)    | `untracked/daemon-{hostname}.pid`  | `untracked/daemon-{hostname}.pid`               |

### Single Source of Truth for Fingerprint Logic

Two implementations must agree exactly:

**Python side** — new helper in `src/claude_code_hooks_daemon/daemon/paths.py`:

```python
import hashlib
import platform
import sys

def python_venv_fingerprint() -> str:
    """Return a stable per-Python-environment fingerprint for venv keying.

    Components: python_version + sys.executable + platform.machine().
    Concurrent containers from the same image share one fingerprint.
    Distinct pyenv/distro Pythons on one host produce distinct fingerprints.
    Cross-arch is differentiated.
    """
    parts = f"{sys.version}|{sys.executable}|{platform.machine()}"
    digest = hashlib.md5(parts.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"

def get_venv_path(project_context: ProjectContext) -> Path:
    """Return the current env's isolated venv directory."""
    return project_context.daemon_untracked_dir() / f"venv-{python_venv_fingerprint()}"
```

**Bash side** — new helper `scripts/install/python_fingerprint.sh`:

```bash
python_venv_fingerprint() {
    local py="${1:-python3}"
    "$py" -c '
import hashlib, platform, sys
parts = f"{sys.version}|{sys.executable}|{platform.machine()}"
digest = hashlib.md5(parts.encode()).hexdigest()[:8]
print(f"py{sys.version_info.major}{sys.version_info.minor}-{digest}")
'
}
```

By computing the fingerprint **in Python itself** from the bash side (invoking the same Python that will own the venv), parity is automatic — there is no dual implementation to drift.

### Daemon Startup — Auto-Bootstrap Flow

`init.sh` builds `PYTHON_CMD` once at init time. New flow:

```bash
# Step 1: Resolve which Python to use (same as today)
PYTHON_SYSTEM="${HOOKS_DAEMON_PYTHON:-python3}"

# Step 2: Compute fingerprint from THAT Python
VENV_FINGERPRINT="$(python_venv_fingerprint "$PYTHON_SYSTEM")"
VENV_DIR="$HOOKS_DAEMON_ROOT_DIR/untracked/venv-$VENV_FINGERPRINT"
PYTHON_CMD="$VENV_DIR/bin/python"

# Step 3: CI-safe gate — never mutate venvs in CI
if _is_ci_environment; then
    # Existing passthrough/stub path — no venv operations
    return 0
fi

# Step 4: Ensure venv exists and is current-version
ensure_venv "$VENV_DIR" "$DAEMON_VERSION" || {
    emit_hook_error "venv bootstrap failed — run: $PYTHON_SYSTEM -m claude_code_hooks_daemon.daemon.cli repair"
    return 1
}
```

`ensure_venv()` is a new function in `scripts/install/venv.sh`:

```bash
ensure_venv() {
    local venv_path="$1"
    local target_version="$2"

    # Case A: venv doesn't exist → create it
    if [[ ! -x "$venv_path/bin/python" ]]; then
        create_venv "$venv_path" && stamp_venv_version "$venv_path" "$target_version"
        return $?
    fi

    # Case B: venv exists but stamp mismatches → rebuild (upgrade invalidation)
    if ! venv_version_matches "$venv_path" "$target_version"; then
        print_info "venv version stamp mismatch — rebuilding for $target_version"
        recreate_venv "$venv_path" && stamp_venv_version "$venv_path" "$target_version"
        return $?
    fi

    # Case C: venv present and current → no-op
    return 0
}
```

### Upgrade Invalidation Strategy (Key Design)

On `hooks-daemon upgrade` inside any env:

1. **Current env** — `ensure_venv` rebuilds the current env's venv and stamps it with the new version.
2. **Other envs** — we do NOT proactively delete them. They become **auto-invalidated via the stamp mechanism**: next time a daemon starts in one of those envs, `venv_version_matches()` returns false and `ensure_venv` rebuilds it.

This is lazy, correct, and CI-safe:

- Proactively deleting other envs' venvs would require enumerating `untracked/venv-*/` and `rm -rf`-ing them — risky and surprising (the other env may be a long-lived desktop pyenv the user cares about).
- Lazy rebuild via stamp is self-healing and transparent.
- A `prune-venvs --stale` CLI command is provided for users who want to reclaim disk eagerly.

### CI Path

`init.sh` already has `_is_ci_environment()` detection (CI env var, `GITHUB_ACTIONS`, etc.). CI code path:

- **Never** calls `ensure_venv`.
- Uses system `python3` directly if needed, or passthrough/stub mode that doesn't require a venv at all.
- Tests that explicitly test `ensure_venv` do so with a tmpdir-isolated fake venv, not the real one.

Add an explicit env-var override `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` for any edge case where CI detection misses a CI-like environment.

### Migration Strategy for Existing Installs (Legacy `untracked/venv/`)

The existing shared `untracked/venv/` (no suffix) is **legacy** and must not linger. On upgrade under the new code:

1. `ensure_venv` creates the new fingerprint-keyed venv and stamps it.
2. The daemon restarts and verifies RUNNING on the new venv.
3. **After** successful restart verification, `upgrade.sh` deletes the legacy `untracked/venv/`.
4. `upgrade.sh` emits: `"Removed legacy venv at untracked/venv/ — daemon now runs from untracked/venv-py{MM}-{fingerprint}/"`

Deletion is ordered **after** the new daemon is confirmed healthy so a failed upgrade doesn't strand the user with no venv at all. If restart verification fails, legacy is preserved and the new fingerprint venv is removed instead (rollback).

For `ensure_venv` invocations outside `upgrade.sh` (e.g. daemon start on a box that was never upgraded through our script): if a fingerprint-keyed venv is created AND a legacy `untracked/venv/` exists AND the fingerprint venv is healthy, same rule — delete legacy after the fingerprint venv is stamped.

`prune-venvs --legacy` is kept as a manual escape hatch and as a no-op safety-net if automatic cleanup ever misses.

### CLI Additions

| Command                                           | Behaviour                                                                                                                      |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `... daemon.cli repair`                           | (existing) rebuild the current env's venv                                                                                      |
| `... daemon.cli list-venvs`                       | List all `untracked/venv-*` dirs with fingerprint, Python version, path, stamped version, size; mark current env with asterisk |
| `... daemon.cli prune-venvs`                      | Delete stale venvs (interactive confirm; `--force`, `--dry-run`)                                                               |
| `... daemon.cli prune-venvs --stale`              | Delete only venvs whose stamp != current daemon version                                                                        |
| `... daemon.cli prune-venvs --legacy`             | Delete the legacy non-suffixed `untracked/venv/`                                                                               |
| `... daemon.cli prune-venvs --all-except-current` | Delete every venv except the current env's                                                                                     |

### Disk Space Note

Each venv is ~150-250MB. Typical developer machine: 2 venvs (container + host). Stamp-based auto-rebuild on upgrade keeps the count bounded at the number of active envs. `uv` shares its global cache across all venvs, so the incremental cost per venv is `.pth` + site-packages, not re-downloaded wheels.

## Tasks

### Phase 1: Fingerprint Helper (SSOT)

- [x] ✅ **Task 1.1**: Add `python_venv_fingerprint()` + `get_venv_path()` to `src/claude_code_hooks_daemon/daemon/paths.py`
  - [x] ✅ Write failing test in `tests/unit/daemon/test_paths_venv_fingerprint.py` — 21 tests covering format, stability, differentiation, path integration, unicode/filesystem safety
  - [x] ✅ Implement using `hashlib.md5(..., usedforsecurity=False)` keyed on `sys.version | sys.base_prefix | platform.machine()` (base_prefix stable between system-python and venv-python so bash-side and Python-side agree)
  - [x] ✅ Edge case tests: Python version extraction, short fingerprint length, safe characters only
  - [x] ✅ Verified: this container fingerprint = `py311-66bbc57c`, venv_path = `/workspace/untracked/venv-py311-66bbc57c`
- [x] ✅ **Task 1.2**: Create `scripts/install/python_fingerprint.sh`
  - [x] ✅ Bash wrapper that invokes the target Python and runs the same MD5 logic (no dual implementation)
  - [x] ✅ Smoke-tested against `python3` (default) and explicit `/usr/bin/python3` / venv python — all produce identical fingerprint
- [x] ✅ **Task 1.3**: Parity integration test `tests/integration/test_fingerprint_parity.py`
  - [x] ✅ 5 tests: helper-exists, helper-executable, bash↔Python parity, format regex, system↔venv parity (same base_prefix)
  - [x] ✅ Verified: bash-side and Python-side produce byte-identical `py311-66bbc57c` against the same interpreter

### Phase 2: Auto-Bootstrap (`ensure_venv`)

- [x] ✅ **Task 2.1**: Add `ensure_venv()` to `scripts/install/venv.sh`
  - [x] ✅ Failing pytest-driven shell test: no venv → `ensure_venv` creates one and stamps it
  - [x] ✅ Failing pytest-driven shell test: stamp mismatch → `ensure_venv` recreates and re-stamps
  - [x] ✅ Failing pytest-driven shell test: venv present + stamp matches → no-op (SENTINEL file preserved)
  - [x] ✅ Implement delegates to `python_venv_fingerprint` (SSOT) + new `create_venv_at_path` + existing `stamp_venv_version` / `venv_version_matches`
  - [x] ✅ Prints venv path to stdout so callers can capture it
- [x] ✅ **Task 2.2**: Wire CI gate (partial — bash-side done; init.sh wiring is Task 4.2)
  - [x] ✅ `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` → `ensure_venv` early-returns 0
  - [x] ✅ `CI=true` → same
  - [ ] ⬜ `init.sh` wiring deferred to Task 4.2

### Phase 3: Update Install/Upgrade Scripts

- [ ] ⬜ **Task 3.1**: Update `scripts/install/venv.sh::create_venv` to accept explicit venv path
  - [ ] ⬜ Failing test: after `create_venv "$path"`, expect venv at `$path`, not at a hardcoded location
  - [ ] ⬜ Remove hardcoded `$daemon_dir/untracked/venv`
  - [ ] ⬜ Update all callers
- [ ] ⬜ **Task 3.2**: Same for `recreate_venv`, `verify_venv`, `install_package_editable`
- [ ] ⬜ **Task 3.3**: Audit every hardcoded `untracked/venv` in shell + Python
  - [ ] ⬜ `rg "untracked/venv" --type sh --type py` — review/update every hit
  - [ ] ⬜ Pay attention to `install.py`, `install.sh`, `upgrade.sh`, `scripts/detect_location.sh`
- [ ] ⬜ **Task 3.4**: Update `.claude/hooks-daemon.env` generation
  - [ ] ⬜ Export `VENV_DIR` and `VENV_FINGERPRINT` for downstream consumers

### Phase 4: Update Daemon Runtime (init.sh)

- [ ] ⬜ **Task 4.1**: Update `init.sh::PYTHON_CMD` derivation (line 230)
  - [ ] ⬜ Source `scripts/install/python_fingerprint.sh`
  - [ ] ⬜ Compute `VENV_FINGERPRINT` from resolved system Python
  - [ ] ⬜ Set `PYTHON_CMD` to `$HOOKS_DAEMON_ROOT_DIR/untracked/venv-$VENV_FINGERPRINT/bin/python`
- [ ] ⬜ **Task 4.2**: Call `ensure_venv` at init (guarded by CI gate)
- [ ] ⬜ **Task 4.3**: Preserve `HOOKS_DAEMON_PYTHON` override
- [ ] ⬜ **Task 4.4**: Add `HOOKS_DAEMON_VENV_PATH` override (skips fingerprint computation)
- [ ] ⬜ **Task 4.5**: **Do NOT touch** `SOCKET_PATH` or `PID_PATH` derivations — hostname-scoped stays hostname-scoped

### Phase 5: CLI Enhancements

- [ ] ⬜ **Task 5.1**: Update `daemon.cli repair` to operate on current env's venv
- [ ] ⬜ **Task 5.2**: Implement `list-venvs`
  - [ ] ⬜ TDD: output format = table with (fingerprint, python-version, path, stamped-version, size, current-marker)
  - [ ] ⬜ Read each venv's `.daemon-version` stamp
- [ ] ⬜ **Task 5.3**: Implement `prune-venvs` with flags `--stale`, `--legacy`, `--all-except-current`, `--dry-run`, `--force`
  - [ ] ⬜ TDD each flag combination
  - [ ] ⬜ Safety: never delete current env's venv without `--force --yes`

### Phase 6: Documentation

- [ ] ⬜ **Task 6.1**: Update `CLAUDE.md` — "Key Paths" section shows fingerprint-keyed path
- [ ] ⬜ **Task 6.2**: Update `CLAUDE/SELF_INSTALL.md` — document fingerprint venv isolation + container/host rationale
- [ ] ⬜ **Task 6.3**: Update `CLAUDE/LLM-INSTALL.md` + `CLAUDE/LLM-UPDATE.md`
- [ ] ⬜ **Task 6.4**: Add post-upgrade task file under `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` (severity: recommended) pointing users with dual container+host setups at the new layout + `prune-venvs --legacy`

### Phase 7: Integration Tests & QA

- [ ] ⬜ **Task 7.1**: Simulated env-switch test
  - [ ] ⬜ Mock different Pythons → verify distinct fingerprints → verify distinct venvs created → verify no cross-contamination
- [ ] ⬜ **Task 7.2**: Upgrade-invalidation test
  - [ ] ⬜ Create two venvs with stamp v1.0.0 → upgrade to v1.1.0 → verify active env rebuilds, other env's stamp still v1.0.0 → run daemon in other env → verify it auto-rebuilds
- [ ] ⬜ **Task 7.3**: Concurrent-container simulation
  - [ ] ⬜ Same Python binary invoked with different HOSTNAMEs → same fingerprint → same venv reused
- [ ] ⬜ **Task 7.4**: CI-gate test
  - [ ] ⬜ `CI=true` → `ensure_venv` not invoked → daemon still initialises
- [ ] ⬜ **Task 7.5**: Legacy auto-deletion test
  - [ ] ⬜ Create `untracked/venv/` → run upgrade → verify fingerprint venv created + stamped + daemon RUNNING → verify legacy `untracked/venv/` auto-deleted
  - [ ] ⬜ Failure-rollback test: inject restart failure → verify legacy preserved, fingerprint venv removed
  - [ ] ⬜ `prune-venvs --legacy` no-op test: runs cleanly when legacy already absent
- [ ] ⬜ **Task 7.6**: Bash↔Python fingerprint parity matrix
- [ ] ⬜ **Task 7.7**: Dogfooding — install in this repo, inspect `untracked/`, verify fingerprint-keyed dir + hostname-keyed sockets coexist
- [ ] ⬜ **Task 7.8**: Full QA suite: `./scripts/qa/run_all.sh` — all 10 checks green
- [ ] ⬜ **Task 7.9**: Daemon restart verification in both container and host

### Phase 8: Acceptance Testing

- [ ] ⬜ **Task 8.1**: Fresh install in container → `untracked/venv-py{MM}-{fingerprint}/` created, stamped
- [ ] ⬜ **Task 8.2**: Relaunch same container (new HOSTNAME) → same fingerprint → existing venv reused (no rebuild)
- [ ] ⬜ **Task 8.3**: Open project directly on desktop host (different Python) → different fingerprint → second venv created, first untouched
- [ ] ⬜ **Task 8.4**: Upgrade path: v3.6.0 legacy `untracked/venv/` → upgrade → fingerprint venv created, stamped, daemon RUNNING → legacy `untracked/venv/` auto-deleted → only fingerprint venv remains
- [ ] ⬜ **Task 8.5**: Cross-env upgrade invalidation: upgrade in container → switch to desktop → daemon detects stamp mismatch → auto-rebuilds → works
- [ ] ⬜ **Task 8.6**: CI path: run in GitHub Actions environment → no venv operations triggered
- [ ] ⬜ **Task 8.7**: `list-venvs` / `prune-venvs --dry-run` output matches reality

### Phase 9: Release

- [ ] ⬜ **Task 9.1**: Invoke `/release` skill — MUST be the final task of this plan
  - [ ] ⬜ Pre-release validation passes (clean git, QA green, version consistency)
  - [ ] ⬜ Version bump: MINOR → v3.7.0
  - [ ] ⬜ Changelog entry covers fingerprint venv keying, auto-bootstrap, legacy auto-deletion, CLI additions
  - [ ] ⬜ Release notes reference upgrade guide for dual container+host users
  - [ ] ⬜ Move `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/*` into versioned `v3/v3.6-to-v3.7/`
  - [ ] ⬜ Opus documentation review approval
  - [ ] ⬜ QA Verification Gate passes
  - [ ] ⬜ Breaking Changes Check → none
  - [ ] ⬜ Code Review Gate passes
  - [ ] ⬜ CLAUDE.md Guidance Audit passes
  - [ ] ⬜ Acceptance Testing Gate passes (full suite since MINOR + handler-adjacent infrastructure changes)
  - [ ] ⬜ Commit + push + tag + GitHub release

## Technical Decisions

### Decision 1: Fingerprint-keyed venvs vs hostname-keyed venvs

**Context**: Original plan used `venv-{hostname}/`. User challenged it: container HOSTNAMEs are ephemeral hex IDs that change every launch.
**Options**:

1. Hostname-keyed venvs (`venv-{hostname}/`) — creates new venv per container launch (bloat)
2. Python-fingerprint-keyed venvs (`venv-py{MM}-{md5}/`) — concurrent containers share, distinct Pythons are distinct
3. Hybrid: hostname for host Pythons, fingerprint for containers — complex and error-prone

**Decision**: Option 2. Python fingerprint is the correct identity axis for venv compatibility. Hostname is the correct axis for live processes (sockets/PIDs) which this plan preserves.

### Decision 2: Fingerprint components

**Context**: What to hash?
**Options**:

1. `python_version` only — too coarse, misses pyenv-vs-distro distinction
2. `python_version + sys.executable` — distinguishes pyenv vs distro on same host
3. `python_version + sys.executable + platform.machine()` — bulletproof cross-arch

**Decision**: Option 3. User asked to keep `platform.machine()` "for bulletproof". Cross-arch edge cases (x86 desktop + ARM container on same mounted filesystem) are real in modern dev setups.

### Decision 3: Dual implementation parity (bash ↔ Python)

**Context**: How to guarantee bash and Python agree.
**Options**:

1. Reimplement the MD5 logic in both bash and Python — risk of drift
2. Bash wrapper invokes Python to compute the fingerprint — zero drift, one source of truth

**Decision**: Option 2. The bash helper is a 5-line shell wrapper that `exec`s `python3 -c '...'`. The Python is already installed (it's the one we're fingerprinting). No dual implementation exists.

### Decision 4: Upgrade invalidation — proactive delete vs lazy rebuild

**Context**: On upgrade, what happens to non-active envs' venvs?
**Options**:

1. Proactively `rm -rf` all other `untracked/venv-*/` — aggressive, surprises users
2. Lazy rebuild via stamp mismatch — venvs rebuild on next use in that env
3. Mark obsolete (touch a file) — implicit, same as stamp
4. Do nothing — leaves broken venvs that fail on next startup

**Decision**: Option 2 (stamp-based lazy rebuild). The `.daemon-version` stamp mechanism is already in place. `ensure_venv` compares stamp to current daemon version and rebuilds on mismatch. Self-healing, transparent, CI-safe. Users who want eager cleanup can run `prune-venvs --stale`.

### Decision 5: Auto-bootstrap vs explicit install

**Context**: What if no venv exists for the current env?
**Options**:

1. Error out — "run install first"
2. Auto-create the venv on daemon start via `ensure_venv`

**Decision**: Option 2. User explicitly requested: "we need to ensure a process to detect when no venv for current env and create it automatically". CI is exempted via explicit gate.

### Decision 6: CI handling

**Context**: CI runs shouldn't create venvs.
**Options**:

1. Detect CI and skip venv operations — leverage existing `_is_ci_environment`
2. Require explicit `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP` env var
3. Both

**Decision**: Option 3. Use existing CI detection AND provide explicit override for edge cases.

### Decision 7: Legacy venv — auto-delete vs manual

**Context**: What to do with existing `untracked/venv/` on upgrade.
**Options**:

1. Auto-delete on first upgrade, ordered AFTER the new fingerprint venv is created, stamped, and daemon restart verified — clean filesystem, zero user confusion
2. Ignore and emit advisory; provide `prune-venvs --legacy` — leaves orphan directory lying around

**Decision**: Option 1. User directive: "dont leave legacy venvs lying around - clean up, avoid confusion". The kill-a-running-daemon risk is mitigated by ordering deletion after the new fingerprint venv is healthy. If restart verification fails, rollback: delete the new fingerprint venv, keep legacy. `prune-venvs --legacy` remains as a manual escape hatch and safety-net.

### Decision 8: `uv` cache sharing

**Context**: `uv` has a global cache at `~/.cache/uv` shared across venvs.
**Decision**: Share the cache (default behaviour). `uv` keys cached wheels by interpreter ABI — each fingerprint's `uv sync` correctly pulls the right artifacts. No change needed.

## Success Criteria

- [ ] Two environments (container + desktop host) on the same filesystem install, run, and upgrade without corrupting each other's venv
- [ ] Concurrent containers from the same image share one venv (verified by fingerprint equality across container launches)
- [ ] `untracked/venv-py{MM}-{fingerprint}/` appears per distinct Python env; `untracked/daemon-{hostname}.{sock,pid}` remain hostname-scoped
- [ ] On upgrade in any env: current env's venv rebuilt + stamped with new version; other envs auto-rebuild on next use via stamp mismatch
- [ ] `ensure_venv` auto-creates a missing venv on daemon start (CI-gated)
- [ ] CI path never triggers venv create/upgrade
- [ ] Legacy `untracked/venv/` is auto-deleted after successful upgrade (rollback if restart fails)
- [ ] `list-venvs` / `prune-venvs` CLI commands work with all flags
- [ ] Full QA suite passes with 95%+ coverage
- [ ] Daemon restart verified in container and host
- [ ] Zero new runtime dependencies
- [ ] No change to hot-path behaviour (socket/PID paths unchanged)

## Risks & Mitigations

| Risk                                                              | Impact | Probability | Mitigation                                                                                            |
| ----------------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------- |
| Bash↔Python fingerprint drift                                     | High   | Low         | Bash wrapper invokes Python — no dual impl. Parity test in Phase 7.                                   |
| Users confused by multiple `venv-*` dirs                          | Low    | Medium      | `list-venvs` shows what each is; docs explain; `prune-venvs` for cleanup                              |
| Disk bloat from accumulated venvs                                 | Low    | Medium      | `prune-venvs --stale` auto-invalidates on upgrade; `uv` cache shared; document eviction               |
| Hardcoded `untracked/venv/` paths missed during audit             | Medium | Medium      | Task 3.3 explicit grep-audit; integration test covers fresh install end-to-end                        |
| Auto-bootstrap triggers in unintended CI-like env                 | Medium | Low         | CI detection + `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP` override                                            |
| `sys.executable` changes due to symlink resolution                | Medium | Low         | Use raw `sys.executable` (not `os.path.realpath`) — stable across reruns of same Python launcher      |
| Stamp-mismatch rebuild loop if version read fails                 | Medium | Low         | `venv_version_matches` treats read failure as mismatch; `ensure_venv` rebuilds once; next run matches |
| Concurrent `ensure_venv` from two daemons racing on same venv dir | High   | Low         | Use file lock in `untracked/venv-{fingerprint}/.lock`; second caller waits                            |
| Release pipeline tests assume legacy path                         | Medium | Medium      | Task 3.3 audit + CI smoke test on fresh clone before release                                          |

## Dependencies

- Builds on Plan 00018 (completed) — hot-path venv decoupling
- Leverages existing `.daemon-version` stamp mechanism in `scripts/install/venv.sh` (already active)
- Related to Issue #28 (open) — `ensure_venv` makes upgrade idempotent-path fix trivial
- Release gating: requires a MINOR version bump (adds CLI commands, backward compatible) — candidate v3.7.0

## Release Impact

- **Version bump**: MINOR (new CLI commands, backward-compatible auto-migration via stamp)
- **Upgrade guide required**: Yes — `CLAUDE/UPGRADES/v3/v3.6-to-v3.7/` with migration walkthrough
- **Post-upgrade task**: `informational` severity — describe the new fingerprint venv layout; no user action required (legacy auto-deleted)
- **Breaking changes**: None at the user-facing level. Upgrade automatically creates the new fingerprint venv and removes the legacy venv after confirming the daemon is healthy.

## Notes & Updates

### 2026-04-21

- Plan created based on user report: "hooks daemon venv gets borked completely when project is opened both inside YOLO container and directly on desktop host"
- Originally proposed hostname-keyed venvs
- **Pivoted** after user challenge: container HOSTNAMEs are ephemeral 12-char hex IDs that change every launch — hostname keying would cause venv-per-launch bloat
- Switched to Python-environment-fingerprint keying: `md5(python_version + sys.executable + platform.machine())[:8]`
- User confirmed: keep `platform.machine()` for bulletproof cross-arch safety
- User explicitly scoped out changes to socket/PID paths — hostname keying stays correct for concurrent live processes
- User added scope: (a) upgrade invalidation across non-active envs, (b) auto-bootstrap on first run, (c) CI-safe stubbing, (d) leverage existing `.daemon-version` stamp mechanism
- Confirmed stamp mechanism is already active in `scripts/install/venv.sh`: `VENV_VERSION_STAMP=".daemon-version"`, `stamp_venv_version()`, `get_venv_version()`, `venv_version_matches()` — used as the lazy-rebuild trigger across non-active envs
