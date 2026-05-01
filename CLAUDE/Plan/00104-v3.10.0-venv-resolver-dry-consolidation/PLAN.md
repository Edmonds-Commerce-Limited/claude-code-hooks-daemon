# Plan 00104: v3.10.0 — venv resolver DRY + upgrade-flow resilience + production bug fixes

**Status**: Not Started
**Created**: 2026-04-30 (rewritten 2026-05-01 to absorb field-report issues)
**Owner**: TBD
**Priority**: High — contains active production bugs (issues #4 and #6 below) plus the structural DRY work that was previously deferred
**Recommended Executor**: Opus 4.6 (Sub-Agent Teams) — complexity warrants strategic oversight per three prior FATAL reviews of the original v1 attempt
**Execution Strategy**: Sub-Agent Teams with explicit commit-by-commit ordering and per-commit verification gates

## Why this plan now covers everything

The original 00104 was scoped to DRY consolidation only. The 2026-05-01 field
report (`context/2026-05-01-field-report-upgrade-issues.md`) surfaced six
additional production issues during a v2.26.0 → v3.9.1 upgrade attempt:

1. **Stale skill scripts** hardcoded the retired legacy venv path; the skill
   `upgrade.sh` runs whatever was deployed at install time rather than fetching
   latest from GitHub (architectural — same pattern as how `install.sh`
   bootstraps).
2. **`upgrade_version.sh` bootstrap paradox** — it requires a valid existing
   venv to find a Python interpreter, so jumping a major venv-format boundary
   leaves no entry point. Should fall back to `ensure_venv` to create one.
3. **Untracked `uv.lock` blocks `git checkout`** during version switching.
4. **`write-venv-metadata` stores the wrong `python_path`** in
   `.daemon-metadata.json` — it records the *system* Python that invoked the
   CLI rather than the venv's own `bin/python`. Skill scripts read this field
   via `paths.py resolve-venv` and end up running daemon code under
   `/usr/bin/python3.11`, which has no daemon packages installed →
   `ModuleNotFoundError: No module named 'claude_code_hooks_daemon'`. **This
   breaks `daemon-cli.sh` for every fresh install of v3.9.1.**
5. **`verify_venv` race on overlay-fs** — `sync -f` after `uv sync` with
   `UV_LINK_MODE=copy` is insufficient on Podman overlay-fs; `verify_venv`
   transiently fails despite the venv existing.
6. **`health-check.sh` ignores resolved `$PYTHON`** — sources `_resolve-venv.sh`
   correctly but a separate code path inside the script invokes the daemon CLI
   via a hardcoded interpreter, defeating resolution.

The user direction (2026-05-01) was unambiguous: **stop fragmenting,
absorb everything into one structural plan, ship as v3.10.0**. Issues #4 and #6
are critical regressions that justify the scope expansion. The deliberate
narrowing of v1 of 00103 was right at that point in time (3 FATAL reviews); now
the structural work is the next slot and the upgrade-flow issues belong with
it because they touch the same files (`venv_resolver.sh`, `upgrade_version.sh`,
`_resolve-venv.sh`, `paths.py`, `write-venv-metadata`).

## Scope

This plan delivers, in order:

1. **Production bug hotfixes** — issues #4, #6, #3 (small, low-risk,
   commit-first to de-risk the rest of the plan).
2. **Canonical resolver library** at `scripts/lib/resolve_venv.sh`.
3. **Five-site collapse to shims** — `_resolve-venv.sh`, `venv-include.bash`,
   `scripts/install/venv_resolver.sh`, `init.sh::_resolve_python_cmd`,
   `scripts/install/venv.sh:venv_lock_hash_matches`.
4. **Upgrade-flow resilience** — issues #1, #2, #5.
5. **Static-check QA gate** `scripts/qa/check_canonical_callers.sh` wired into
   `run_all.sh`.
6. **Multi-host NFS hostname-dimension fail-fast** (R22 from 00103 review #3).
7. **`requires-python` cross-check** on probed bootstrap interpreters (R23).
8. **`set -euo pipefail` exit-vs-return contract** (F17).
9. **Release v3.10.0** via `/release minor`.

## Goals

1. Daemon-cli.sh and health-check.sh work correctly out of the box after a
   fresh install of the released version. **No manual metadata fix required.**
2. Major-version upgrades (e.g. v2.26 → v3.10) work via the skill `upgrade.sh`
   without any of the failure modes documented in the 2026-05-01 field report.
3. Five resolver sites collapse to 3–8-line shims sourcing one canonical
   library; one source of truth for venv resolution.
4. Static check enforces the canonical pattern as the 11th `run_all.sh` gate.
5. Hot-path latency budget for `init.sh::_resolve_python_cmd`: <5ms median per
   hook fire post-consolidation.
6. All Plan 00103 acceptance tests still pass post-consolidation (no regression
   of the v3.9.1 fixes).
7. The skill `upgrade.sh` fetches the latest version of itself (and the
   delegated upgrade chain) from GitHub before doing destructive work, mirroring
   how `install.sh` already works.
8. v3.10.0 ships via `/release minor` with all 15 release-pipeline gates green.

## Non-Goals

- Idle-window daemon death (field report items #4 and #5 from 00103's
  2026-04-30 report; pre-existing v3.8.2 issue, separate plan).
- Compact-event correlation.
- Hot-path optimisation beyond the 5ms latency budget (further improvements
  belong in a follow-up).
- Anything in Plan 00101 (recap-stoppage / silent-stop) — separate plan, has
  its own active investigation.

## Context & Background

### Field reports

- **Plan 00103** field report (2026-04-30): `paths.py:22 import tomllib` at
  module top crashed under `python3 → 3.9`. Five resolver sites silently fell
  back to retired legacy path. **Shipped in v3.9.1.**
- **This plan's** field report (2026-05-01):
  `context/2026-05-01-field-report-upgrade-issues.md`. Six additional issues
  encountered during an actual v2.26.0 → v3.9.1 upgrade in a Podman overlay-fs
  container. Notable verbatim user observation:

  > "the skill scripts should fetch the LATEST versions from upstream GitHub
  > before orchestrating the upgrade, rather than running whatever version
  > was deployed at install time."

### Prior reviews

The original v1 of Plan 00103 attempted to bundle the patch with the
structural refactor and received three consecutive FATAL Opus reviews:

- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-1-opus.md`
- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-2-opus-dry.md`
- `CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-3-opus.md`

Findings inherited by this plan (re-verify against live tree before any
code, do not trust prior enumerations verbatim):

- **F12**: `venv_resolver.sh` has 9 callers (not 2). Convert to re-export shim,
  do NOT delete.
- **F13**: `init.sh` lives at `/workspace/init.sh` (repo root). Three deploy
  locations exist: skill bundle, self-install repo, downstream clone.
  Source-path resolution must work in all three.
- **F14**: Probe-list `python3` and parameter-expansion `${VAR:-python3}` are
  different syntactic categories — static check covers both.
- **F15**: Explicit per-commit verification gates, not coupled batches.
- **F16**: Acceptance fixture must reproduce multi-Python field-bug topology.
- **F17**: `set -euo pipefail` cascade — canonical library distinguishes
  sourced-as-function (`return`) vs invoked-as-script (`exit`).
- **F18**: Static check uses positive-include allowlist + inline marker
  comments, not line-anchor allowlist.
- **R17**: Hot-path latency benchmark before/after.
- **R18**: Fingerprint cache chicken-and-egg — fingerprint requires Python
  invocation but cache is keyed on fingerprint.
- **R19**: `HOOKS_DAEMON_PYTHON` override hard-precedence semantics.
- **R21**: Pre-v3.7.0 install upgrade-path circular dependency.
- **R22**: Multi-host NFS no-`HOSTNAME` fail-fast.
- **R23**: Bootstrap `requires-python` cross-check.
- **R24**: `check_canonical_callers.sh` actionable error output.
- **R25**: `upgrade.sh` preflight test sequencing.

## Design Decisions

### Decision 1: Bug fixes ship FIRST as small commits, before any structural work

**Context**: Issues #4 and #6 are active production bugs breaking
`daemon-cli.sh` for v3.9.1 fresh installs. Issue #3 is a small upgrade-path
glitch. None of the three depend on the canonical-library work. Shipping them
first means even if the structural phases hit a wall, the production bugs are
already gone.

**Decision**: Phase 2 (Production bug fixes) lands before Phase 3 (Canonical
library). Each fix is a separate commit with its own daemon-restart
verification.

**Date**: 2026-05-01

### Decision 2: `write-venv-metadata` uses `sys.executable`, not `python3` from PATH

**Context** (issue #4): `write-venv-metadata` is invoked from shell after the
venv is created, typically via `$PYTHON_CMD -m claude_code_hooks_daemon...`.
The CLI handler resolves `python_path` from somewhere — turns out it stores
the `python3` argv[0] of the calling Python interpreter, which is the system
Python that invoked the install script, not the venv Python.

**Decision**: `write-venv-metadata` records `sys.executable` of the *calling*
process. The contract is: "run me from the venv's Python and I'll record that
venv's interpreter path". Bootstrap callers must invoke `write-venv-metadata`
via the venv's own `bin/python`, not via the system `python3`.

Defensive belt-and-braces: `paths.py resolve-venv` should prefer
`{venv_dir}/bin/python` (constructed from disk) over the stored
`python_path` field — the metadata field exists for tooling diagnostics, not
as the source of truth for which interpreter to use.

**Date**: 2026-05-01

### Decision 3: Skill `upgrade.sh` self-bootstraps from GitHub before destructive work

**Context** (issue #1): The skill `upgrade.sh` deployed at v2.26.0 hardcoded
the legacy venv path and was unable to resolve a Python interpreter post-v3.7.0.
It should fetch the latest version of itself first, just like `install.sh`
already does.

**Decision**: Skill `upgrade.sh` first downloads the latest skill `upgrade.sh`
from `main` to a temp file, verifies the download, and `exec`s it with the
same arguments. Subsequent layers (Layer 1 wrapper inside `.claude/hooks-daemon/`,
Layer 2 `upgrade_version.sh`) are still version-pinned to whatever git tag is
checked out, but the skill orchestrator no longer runs stale.

This means a user with a 6-month-old skill bundle can still upgrade
successfully; the skill scripts pinned in their project no longer block them.

**Date**: 2026-05-01

### Decision 4: `upgrade_version.sh` falls back to `ensure_venv` when no valid venv exists

**Context** (issue #2): Calling `resolve_existing_venv_python` first means a
fresh major-version upgrade aborts before it has a chance to create the new
fingerprint-keyed venv.

**Decision**: `upgrade_version.sh` tries to resolve an existing venv; if that
fails, it calls `ensure_venv "$DAEMON_DIR" "$INSTALLED_VERSION" "$BOOTSTRAP_PYTHON"`
with the bootstrap Python (resolved via the same explicit-versioned probe used
by `install.sh`). The bootstrap Python is then used solely to drive
`uv sync`; once the new venv exists, the rest of the upgrade runs through it.

This eliminates the bootstrap paradox without weakening fail-fast behaviour
elsewhere.

**Date**: 2026-05-01

### Decision 5: Daemon installer adds `uv.lock` to `.gitignore` for the daemon directory

**Context** (issue #3): Untracked `uv.lock` was present in the user's
`.claude/hooks-daemon/`, blocking `git checkout` during version switching.
The file is generated by `uv sync`; it should not be tracked in the daemon's
own git tree, and any stray copy in the user's checkout should be cleaned
or ignored before checkout.

**Decision**:

1. The daemon's own `.gitignore` (in the daemon repo) lists `uv.lock` so it
   is never tracked.
2. Skill `upgrade.sh` (after self-bootstrap, before `git fetch + checkout`)
   removes any `uv.lock` it finds in the daemon directory. This is safe
   because `uv sync` regenerates it during venv setup.

**Date**: 2026-05-01

### Decision 6 — 8: Inherited from prior 00104 design

**6. Canonical bash library** at `scripts/lib/resolve_venv.sh` with public API
(`resolve_venv_python`, `resolve_venv_dir`). Sourced-as-function uses `return`;
invoked-as-script uses `exit`.

**7. Static check `check_canonical_callers.sh`** added as 11th `run_all.sh`
gate. Positive-include allowlist; inline `# canonical-resolver-exempt:` marker
comments for legitimate exceptions.

**8. Multi-host NFS hostname fail-fast**: when `HOSTNAME` is unset AND multiple
hostname-suffixed venvs exist, fail fast with a clear directive listing the
discovered hostnames so the operator can pick one explicitly.

## Tasks

### Phase 1: Design refresh + Opus hostile review gate

- [ ] ⬜ **Task 1.1**: Re-grep the live tree for every assumption in this plan
  — caller counts for `venv_resolver.sh`, deploy locations of `init.sh`, sites
  consuming `${HOOKS_DAEMON_PYTHON:-...}`. Update tasks if reality has shifted
  since 2026-04-30.
- [ ] ⬜ **Task 1.2**: Spawn Opus 4.6 hostile review pass against this plan.
  Address every FATAL/CRITICAL finding before any code. Capture review under
  `context/2026-05-NN-review-N-opus.md`.
- [ ] ⬜ **Task 1.3**: After review, sign off the plan and lock the commit
  ordering in Phase 9.

### Phase 2: Production bug hotfixes (low-risk, ship FIRST)

These three fixes are independent of the structural work and ship as separate
commits at the start of the plan. They de-risk the rest by narrowing the diff
that gets blamed if anything breaks during structural phases.

- [ ] ⬜ **Task 2.1 — Issue #4 fix**:
  - [ ] ⬜ Failing test: `tests/unit/install/test_write_venv_metadata.py::test_python_path_records_caller_sys_executable`
    — fixture invokes `write-venv-metadata` via a temp venv's Python; asserts
    the JSON `python_path` equals that venv's `bin/python`, not
    `/usr/bin/python3.x`.
  - [ ] ⬜ Failing test: `tests/unit/daemon/test_paths_resolve_venv.py::test_resolve_venv_prefers_disk_python_over_metadata_field`
    — fixture creates a venv whose `.daemon-metadata.json` lies (says
    `/usr/bin/python3.11`); asserts resolver returns the venv's actual
    `bin/python` from disk.
  - [ ] ⬜ Implement: `write-venv-metadata` records `sys.executable`.
  - [ ] ⬜ Implement: `paths.py resolve-venv` constructs candidate path from
    `{venv_dir}/bin/python` first; falls back to `python_path` field only if
    the constructed path is missing.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 2.2 — Issue #6 fix**:
  - [ ] ⬜ Audit `health-check.sh` for every daemon-CLI invocation; identify
    the path that bypasses `$PYTHON`.
  - [ ] ⬜ Failing test: `tests/integration/test_health_check_uses_resolved_python.py`
    — fixture with venv at fingerprint path, asserts `health-check.sh` invokes
    daemon CLI via the venv interpreter (not `/usr/bin/python3.11`).
  - [ ] ⬜ Implement: every CLI invocation in `health-check.sh` uses the
    `$PYTHON` resolved by `_resolve-venv.sh`.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 2.3 — Issue #3 fix**:
  - [ ] ⬜ Add `uv.lock` to the daemon repo's `.gitignore` if not already
    present.
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_handles_stale_uv_lock.py`
    — fixture daemon dir with stray `uv.lock`; asserts skill `upgrade.sh`
    cleans it before `git checkout` (test will land green after Task 5.1
    implements the cleanup; for now mark xfail with reason).
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.

### Phase 3: TDD failing tests for structural work

- [ ] ⬜ **Task 3.1**: Parity matrix test — every site returns the same Python
  for the same daemon-dir input.
- [ ] ⬜ **Task 3.2**: `set -euo pipefail` cascade test —
  `test_resolver_when_sourced_under_pipefail_does_not_kill_caller_shell`.
- [ ] ⬜ **Task 3.3**: Hot-path latency benchmark — measure
  `init.sh::_resolve_python_cmd` median time over N hook fires; assert <5ms
  post-consolidation.
- [ ] ⬜ **Task 3.4**: Multi-host NFS fail-fast test — fixture with two
  hostname-suffixed venvs, `HOSTNAME` unset, asserts fail-fast with a directive
  listing the hostnames.
- [ ] ⬜ **Task 3.5**: Static-check tests — positive-include allowlist
  passes the canonical library, inline marker comments pass tagged exceptions,
  legitimate violations are flagged.
- [ ] ⬜ **Task 3.6**: `requires-python` cross-check test — bootstrap rejects
  an interpreter outside `pyproject.toml`'s `requires-python` even when
  `>= 3.11`.

### Phase 4: Canonical library — `scripts/lib/resolve_venv.sh`

- [ ] ⬜ **Task 4.1**: Write `scripts/lib/resolve_venv.sh` with public API:
  - `resolve_venv_python <daemon_dir>` → echo path or fail.
  - `resolve_venv_dir <daemon_dir>` → echo dir or fail.
  - Sourced-as-function: `return` non-zero. Invoked-as-script: `exit`
    non-zero. Detection via `${BASH_SOURCE[0]}` vs `$0`.
- [ ] ⬜ **Task 4.2**: Source-path resolution robust across the 3 deploy
  locations (skill bundle, self-install repo, downstream clone).
- [ ] ⬜ **Task 4.3**: Phase 3 Tasks 3.1, 3.2 turn green.
- [ ] ⬜ **Task 4.4**: Daemon restart RUNNING; QA green; commit.

### Phase 5: Five-site shim collapse + upgrade-flow resilience

Each site becomes a 3–8-line shim sourcing the canonical library. `venv_resolver.sh`
collapses to a re-export shim (NOT deletion — F12). One commit per site.

- [ ] ⬜ **Task 5.1 — Issue #1 fix (skill upgrade self-bootstrap)**:
  - [ ] ⬜ Failing test: `tests/integration/test_skill_upgrade_self_bootstraps.py`
    — fixture skill `upgrade.sh` is intentionally stale (echoes "OLD"),
    repository `main` has a fresh upgrade.sh that echoes "NEW"; asserts
    actual run echoes "NEW". Network-mocked.
  - [ ] ⬜ Implement: skill `upgrade.sh` first stage downloads latest
    `upgrade.sh` from GitHub `main`, verifies download (size + maybe sha256),
    `exec`s it with original argv.
  - [ ] ⬜ Implement: skill `upgrade.sh` (post-self-bootstrap) cleans any
    stray `uv.lock` in the daemon dir before `git checkout`. (Closes Task 2.3
    xfail.)
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 5.2 — Issue #2 fix (upgrade_version.sh bootstrap fallback)**:
  - [ ] ⬜ Failing test: `tests/integration/test_upgrade_version_bootstraps_when_no_venv.py`
    — fixture daemon dir with only legacy v2.x stamp (no `.daemon-metadata.json`,
    no fingerprint venv); asserts upgrade succeeds by creating the new venv.
  - [ ] ⬜ Implement: `upgrade_version.sh` falls back to `ensure_venv` with
    bootstrap-resolved Python when `resolve_existing_venv_python` fails.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 5.3 — Issue #5 fix (verify_venv overlay-fs race)**:
  - [ ] ⬜ Reproduce locally on overlay-fs (this repo runs in a Podman
    container so reproduction is in-tree).
  - [ ] ⬜ Failing test: `tests/integration/test_verify_venv_after_uv_link_copy.py`
    — fixture forces `UV_LINK_MODE=copy`, asserts `verify_venv` succeeds
    after the sync without needing manual retry.
  - [ ] ⬜ Implement: `verify_venv` retries on transient
    `ModuleNotFoundError` / missing-binary errors with a small bounded sleep
    loop (e.g. 5 attempts × 200ms) when `UV_LINK_MODE=copy` was used. Flag
    that this is a workaround for overlay-fs visibility, not the canonical
    expected path.
  - [ ] ⬜ Daemon restart RUNNING; QA green; commit.
- [ ] ⬜ **Task 5.4**: `_resolve-venv.sh` collapses to canonical shim.
- [ ] ⬜ **Task 5.5**: `venv-include.bash` collapses to canonical shim.
- [ ] ⬜ **Task 5.6**: `venv_resolver.sh` collapses to re-export shim
  preserving all 9 caller signatures.
- [ ] ⬜ **Task 5.7**: `init.sh::_resolve_python_cmd` collapses; preserves
  fingerprint cache write.
- [ ] ⬜ **Task 5.8**: `venv.sh:venv_lock_hash_matches` collapses.

### Phase 6: Static-check QA gate

- [ ] ⬜ **Task 6.1**: Author `scripts/qa/check_canonical_callers.sh` per
  Decision 7. Positive-include allowlist; inline `# canonical-resolver-exempt:`
  marker support; actionable error output (R24).
- [ ] ⬜ **Task 6.2**: Wire into `run_all.sh` as the 11th check.
- [ ] ⬜ **Task 6.3**: Phase 3 Task 3.5 turns green; full QA passes (11/11).
- [ ] ⬜ **Task 6.4**: Daemon restart RUNNING; commit.

### Phase 7: Multi-host NFS + `requires-python` cross-check

- [ ] ⬜ **Task 7.1**: Multi-host fail-fast logic in canonical library; Phase 3
  Task 3.4 turns green.
- [ ] ⬜ **Task 7.2**: `requires-python` cross-check in bootstrap probe; Phase
  3 Task 3.6 turns green.
- [ ] ⬜ **Task 7.3**: Daemon restart RUNNING; QA green; commit.

### Phase 8: Hot-path latency verification

- [ ] ⬜ **Task 8.1**: Run Phase 3 Task 3.3 benchmark against the consolidated
  code. If median exceeds 5ms, optimise `source` cost in `init.sh`
  (e.g. cache the canonical library's resolved output via the existing
  `untracked/.python-cmd-cache` mechanism). Document optimisation in plan.
- [ ] ⬜ **Task 8.2**: Daemon restart RUNNING; commit.

### Phase 9: Verification + acceptance

- [ ] ⬜ **Task 9.1**: Re-run all Plan 00103 acceptance tests
  (`tests/acceptance/test_v391_field_regression.py`) — must still pass.
- [ ] ⬜ **Task 9.2**: New acceptance test mirroring the 2026-05-01 field
  report scenario:
  - Container fixture with overlay-fs (or filesystem mock).
  - Skill `upgrade.sh` from a stale-pinned starting point.
  - Stray `uv.lock`.
  - Asserts the upgrade succeeds end-to-end with the new code.
- [ ] ⬜ **Task 9.3**: Final full `./scripts/qa/run_all.sh` — all 11 checks
  pass.
- [ ] ⬜ **Task 9.4**: Daemon restart RUNNING.
- [ ] ⬜ **Task 9.5**: Live diagnostic test from project root: `health-check.sh`,
  `daemon-cli.sh status`, `init-handlers.sh` — all clean. **Confirms issues #4
  and #6 are gone in the integrated build.**

### Phase 10: Release v3.10.0

- [ ] ⬜ **Task 10.1**: Run `/release minor` skill end-to-end. All 15 release
  pipeline gates must pass.
- [ ] ⬜ **Task 10.2**: Release notes: explicit transparency about every
  shipped fix (issues #1–#6 plus the structural consolidation). Reference the
  field report from 2026-05-01 verbatim.
- [ ] ⬜ **Task 10.3**: Acceptance gate covers diagnostic-script invocation
  paths (the v3.9.0 regression escaped because acceptance focused on hook
  dispatch).
- [ ] ⬜ **Task 10.4**: Verify release published, tag pushed, GitHub release
  marked latest.
- [ ] ⬜ **Task 10.5**: Plan completion checklist (move folder to
  `Completed/`, update `README.md`, etc.).

## Dependencies

- **Depends on**: Plan 00103 complete (v3.9.1 released — yes, complete).
- **Blocks**: Future hot-path optimisation work, multi-host deployment work.
- **Related**: Plan 00100 (venv SSOT — this plan refines its shell-wrapper
  layer with the DRY library).

## Success Criteria

- [ ] On a fresh install of v3.10.0: `daemon-cli.sh status` works without any
  manual `.daemon-metadata.json` patching. **Issue #4 closed.**
- [ ] On a fresh install of v3.10.0: `health-check.sh` reports daemon health
  without `ModuleNotFoundError`. **Issue #6 closed.**
- [ ] Major-version upgrade (v2.26 → v3.10) via the skill `/hooks-daemon
  upgrade` succeeds without manual intervention; no stale-skill-script
  failure, no `uv.lock` checkout abort, no bootstrap paradox.
  **Issues #1, #2, #3, #5 closed.**
- [ ] `scripts/lib/resolve_venv.sh` exists with documented public API.
- [ ] All five resolver sites are 3–8-line shims sourcing the canonical.
- [ ] `venv_resolver.sh` retained as re-export shim (9 callers preserved).
- [ ] `scripts/qa/check_canonical_callers.sh` wired into `run_all.sh` and
  passes (11/11).
- [ ] Hot-path latency: `init.sh::_resolve_python_cmd` median resolve <5ms
  verified by benchmark.
- [ ] Multi-host NFS without `HOSTNAME` set fails fast with clear directive
  when multiple hostname-suffixed venvs exist.
- [ ] Bootstrap rejects interpreter outside `requires-python` even when
  `>= 3.11`.
- [ ] Sourced-as-function paths use `return`; invoked-as-script paths use
  `exit`. Test verifies `venv-include.bash` does not kill caller shell on
  `set -euo pipefail`.
- [ ] All Plan 00103 acceptance tests still pass after consolidation.
- [ ] Each commit in Phase 5 leaves daemon RUNNING and QA green.
- [ ] v3.10.0 released via `/release minor` with all 15 gates green.

## Risks & Mitigations

| Risk                                                                                                          | Impact | Probability | Mitigation                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| This plan re-creates the v1 ambitious-bundle anti-pattern that earned three FATAL reviews                     | High   | Medium      | Phase 1 hostile review gate before any code. Phase 2 ships bug fixes as standalone commits so they survive even if structural phases stall. Per-commit verification gates throughout. |
| Skill `upgrade.sh` self-bootstrap introduces network failure modes                                            | High   | Medium      | Self-bootstrap is best-effort with explicit timeout; falls back to running the locally-deployed version with a warning. Test `test_skill_upgrade_falls_back_when_github_unreachable`. |
| `write-venv-metadata` change breaks downstream consumers reading `python_path` field                          | Medium | Low         | The field semantics tighten (now correctly records calling Python); resolver no longer trusts it as source of truth. Audit for external consumers in Phase 1.           |
| `verify_venv` retry loop masks a real bug elsewhere                                                           | Medium | Medium      | Retry is bounded (5 × 200ms = 1s max). Logs warn when retry was needed. Phase 9 acceptance test confirms first-attempt success in normal conditions.                    |
| Source-path resolution fragility across 3 deploy locations                                                    | High   | Medium      | Explicit deploy-location enumeration in Phase 4. Test fixture per location.                                                                                             |
| Hot-path latency regression after consolidation                                                               | Medium | Medium      | Phase 8 benchmark gate. Roll back consolidation if latency exceeds budget.                                                                                              |
| Static check false positives on documentation/release notes                                                   | Medium | High        | Phase 6 positive-include allowlist; inline marker comments per F18.                                                                                                     |
| Incomplete `venv_resolver.sh` caller enumeration (F12 root cause)                                             | High   | Low         | Phase 1 design refresh re-greps the live tree.                                                                                                                          |
| `set -euo pipefail` cascade kills caller shell (F17)                                                          | High   | High if naive | Phase 4 explicit exit-vs-return contract. Phase 3 Task 3.2 covers it.                                                                                                  |
| Self-install dogfooding: developer's own venv breaks while applying this plan                                 | High   | Low         | This repo IS a self-install. Each commit's daemon-restart-RUNNING check catches it. Revert plan: `git revert` any commit that breaks `daemon-cli.sh status`.            |

## Notes & Updates

### 2026-04-30 — Plan stub created (split from v1 ambitious 00103)

- v1 (`PLAN-v1-ambitious-superseded.md` in 00103) attempted to combine the
  patch fix with a DRY consolidation. Three Opus 4.6 hostile reviews returned
  FATAL.
- This plan was originally scoped to DRY consolidation only.

### 2026-05-01 — Plan rewritten to absorb 2026-05-01 field report

- 2026-05-01 field report (`context/2026-05-01-field-report-upgrade-issues.md`)
  surfaced 6 production issues from a real v2.26 → v3.9.1 upgrade.
- User direction: "stop beating about the bush ... ONE single plan, all the
  work in there in the correct order. Get it all done, get it through the
  release process and get it released."
- Rewrite folds issues #1–#6 into the structural plan with explicit ordering
  (bug fixes first, structural after, release as v3.10.0).
- Issue #4 alone (broken `python_path` in metadata) justifies the scope
  expansion; it breaks `daemon-cli.sh` for every fresh install of v3.9.1.
- Plan 00105 / 00106 NOT created — single plan absorbs everything.
