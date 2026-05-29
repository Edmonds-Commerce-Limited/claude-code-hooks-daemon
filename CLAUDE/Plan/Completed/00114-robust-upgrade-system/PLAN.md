# Plan 00114: Fully Robust Upgrade System

**Status**: Complete
**Created**: 2026-05-29
**Owner**: Claude (Opus) + user (joseph)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (TDD per failure mode)

**Outcome**: F1–F4 implemented in an isolated worktree and merged to main (merge commit
on top of v3.16.0); QA 13/13 green. F1 (`--already-bootstrapped` tolerance) + F2
(self-contained python-discovery fetch) in `scripts/upgrade.sh`; F3 (overlay-fs proactive
copy mode) in `scripts/install/venv.sh`; F4 (recovery hints) in both Layer-1 and the skill
`upgrade.sh`. Regression tests added (legacy-shim e2e, recovery-hint, legacy-flag
tolerance, tmp self-contained, overlay-fs proactive copy); H-1 gate count bumped 23→24 in
RELEASING.md. G6 documentation closeout (LLM-UPDATE.md stuck-client troubleshooting) is the
only remaining tail item.

## Overview

A field report (`untracked/hooks-daemon-upgrade-broken.md`, 2026-05-29) documented a
client on v3.13.0 upgrading to v3.16.0 where **both** documented upgrade paths failed,
and the upgrade only succeeded via an undocumented escape hatch
(`HOOKS_DAEMON_SKIP_BOOTSTRAP=1`). The breakages are bootstrap/packaging problems, not
logic problems in the actual deploy — but they make the single most important operation
in the project (upgrading) fragile for any client more than ~2 versions behind.

Upgrades are the highest-leverage correctness surface we have: a broken upgrade flow
silently propagates to **every** project that depends on the daemon, and (worse) the
fix for a broken client-side shim is *delivered by* a successful upgrade — a circular
dependency that can leave a client hard-stuck. This plan makes the upgrade system
**backward-tolerant, self-contained, silent on containers, and self-documenting on
failure**, with regression tests for every failure mode so these classes never recur.

This plan also fixes the "benign" uv hardlink warning (F3 below) — it is noise emitted
on every container/overlay-fs install, and noise erodes trust in the upgrade output.

## Goals

- **G1** — Heal clients stuck on a pre-v3.15 `upgrade.sh` skill shim: Layer 1
  (`scripts/upgrade.sh`) must accept-and-ignore `--already-bootstrapped` (and any other
  historical bootstrap flag) instead of aborting.
- **G2** — Make Layer 1 self-contained for the documented curl-to-`/tmp` flow: it must
  obtain `python_discovery.sh` even when neither the installed daemon dir nor a `/tmp`
  sibling provides it.
- **G3** — Eliminate the uv hardlink warning on overlay-fs/container installs by
  detecting the filesystem up front and choosing copy mode proactively (no failed
  attempt, no warning) — while preserving hardlink speed on real disks.
- **G4** — Surface the `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` recovery hint (and the manual
  fallback) in the exact error messages where a stuck client would see them.
- **G5** — Regression tests for every failure mode, wired into the H-1 acceptance gate
  (RELEASING.md Step 12.0) so a release cannot ship with any of them reintroduced.
- **G6** — Update the documented manual upgrade instructions so the curl-to-`/tmp`
  flow we tell users to run actually works.

## Non-Goals

- Re-architecting Layer 2 (`upgrade_version.sh`) deploy logic — it ran cleanly in the
  report once reached.
- Removing the three sibling self-bootstrap skill scripts (daemon-cli.sh,
  health-check.sh, init-handlers.sh). They fetch their *own* artifacts, which ARE
  `--already-bootstrapped`-aware, so they are internally consistent. (Thinning them is a
  separate future plan — see Plan 00109 Decision 4.)
- Changing the bootstrap-checksums manifest contract.

## Context & Background

### Upgrade system layering (as of v3.16.0)

- **Layer 0 (skill scripts)** — pushed into client `.claude/skills/hooks-daemon/scripts/`:
  - `upgrade.sh` — since v3.15.0 (Plan 00109) a 49-line **thin shim**: detects project
    root, fetches `scripts/upgrade.sh` from `main`, `exec bash <tmp> --project-root … "$@"`.
    No `--already-bootstrapped`. **Old shims (pre-v3.15) still in the wild DO pass it.**
  - `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` — still self-bootstrap; each
    fetches the release artifact of *its own basename* and re-execs with
    `--already-bootstrapped`. The fetched artifacts handle that flag. Internally
    consistent — out of scope.
- **Layer 1** — `scripts/upgrade.sh` (canonical, in daemon repo, 408 lines). Fetched
  fresh by the thin shim into `/tmp`, OR curled to `/tmp` manually per docs, OR run from
  the installed daemon dir. Arg parser (lines 31-56) **rejects any unknown `-*` flag**.
  Sources `scripts/lib/python_discovery.sh` via `_resolve_python_discovery_lib`
  (lines 107-144): daemon_dir first, then `/tmp` sibling.
- **Layer 2** — `scripts/upgrade_version.sh` (version-specific deploy). Out of scope.

### Confirmed failure modes (verified against HEAD = v3.16.0, commit 3ebb40c)

| #   | Failure                                                               | Who hits it                                                                                | Root cause (file:line)                                                                |
| --- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| F1  | `ERR Unknown option: --already-bootstrapped`                          | clients with a pre-v3.15 `upgrade.sh` skill shim, which re-execs the release artifact      | `scripts/upgrade.sh:45-49` rejects unknown `-*` flags                                 |
| F2  | `ERR Canonical python discovery helper missing` (manual curl-to-/tmp) | clients whose *installed* daemon predates `python_discovery.sh`, using the documented flow | `scripts/upgrade.sh:107-144` sources a sibling/daemon-dir lib never fetched into /tmp |
| F3  | `⚠ uv hardlink failed (likely overlay-fs) — retrying …` (noise)       | **every** overlay-fs / container install + upgrade                                         | `scripts/install/venv.sh:451-474` is hardlink-first; warns, then retries copy         |
| F4  | recovery via `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` undiscoverable           | any stuck client                                                                           | hint not surfaced by the F1/F2 abort messages                                         |

### The bootstrap deadlock (why this is high priority)

The fix for the broken old shim (F1) is *delivered by* a successful upgrade — but the
broken shim is what blocks the upgrade. **Circular.** The only break in the circle is to
make the thing the old shim fetches (Layer 1 `scripts/upgrade.sh` on `main`/release)
tolerant of the flag the old shim passes. Once G1 lands, every stuck client self-heals on
its next `/hooks-daemon upgrade`.

### Existing test coverage (audited)

The upgrade-related tests that DO exist:

- `tests/acceptance/`: `test_install_sh_end_to_end.py`, `test_skill_install_python_discovery.py`,
  `test_skill_upgrade_end_to_end.py`, `test_skill_upgrade_shim.py`,
  `test_upgrade_md_metadata_contract.py`, `test_upgrade_metadata_emission.py`.
- `tests/integration/`: `test_build_bootstrap_checksums.py`, `test_upgrade_eager_cleanup.py`,
  `test_upgrade_sh_stop_bootstrap.py`, `test_upgrade_version_bootstraps_when_no_venv.py`.

**None of these cover F1 (legacy flag tolerance) or F2 (/tmp self-containment).** New
tests are required for both. `test_skill_upgrade_shim.py` / `test_skill_upgrade_end_to_end.py`
are the right style template for the F1 end-to-end "old shim → new artifact" test.

## Tasks

### Phase 0: Confirm reproduction (NO code changes)

- [ ] ⬜ **Task 0.1**: Run the existing upgrade suite green as a baseline:
  `pytest tests/integration/test_upgrade_*.py tests/acceptance/test_skill_upgrade_*.py tests/acceptance/test_install_sh_end_to_end.py -v`
- [ ] ⬜ **Task 0.2**: Reproduce F1: run `bash scripts/upgrade.sh --project-root <fixture> --already-bootstrapped`
  and confirm the "Unknown option" abort. Record exact output in Notes.
- [ ] ⬜ **Task 0.3**: Reproduce F2: copy `scripts/upgrade.sh` alone into a temp dir (no
  `lib/`), point at a daemon dir lacking `python_discovery.sh`, run it, confirm the
  "Canonical python discovery helper missing" abort.
- [ ] ⬜ **Task 0.4**: Locate the documented manual instructions (report quotes
  `curl … scripts/upgrade.sh -o /tmp/upgrade.sh; bash /tmp/upgrade.sh`). Known sources:
  `scripts/upgrade.sh` header, `src/.../skills/hooks-daemon/upgrade.md`,
  `CLAUDE/LLM-UPDATE.md`, `version_check.py`, `daemon_location_guard.py`,
  `references/troubleshooting.md`. List every copy to keep in sync for G6.
- [ ] ⬜ **Task 0.5**: Finalise the G2 mechanism (Decision 2) before any F2 code.

### Phase 1: F1 — Layer 1 legacy-flag tolerance (TDD) [G1]

- [ ] ⬜ **Task 1.1**: RED — new test `tests/integration/test_upgrade_sh_legacy_flag_tolerance.py`:
  `scripts/upgrade.sh --project-root X --already-bootstrapped [VERSION]` (flag in any
  position) does NOT abort with "Unknown option" and proceeds past arg-parse.
- [ ] ⬜ **Task 1.2**: GREEN — add an accept-and-ignore case to the arg parser
  (`scripts/upgrade.sh:31-56`) for an allowlist of historical bootstrap flags
  (`--already-bootstrapped`), with a one-line `_warn` that the flag is legacy/ignored.
  Keep rejecting genuinely-unknown flags (typo protection — Risk row).
- [ ] ⬜ **Task 1.3**: Verify the thin-shim happy path (`--project-root … VERSION`, no
  legacy flag) is unaffected.
- [ ] ⬜ **Task 1.4**: shellcheck clean; daemon restart RUNNING.

### Phase 2: F2 — Self-contained Layer 1 for /tmp (TDD) [G2, G6]

- [ ] ⬜ **Task 2.1**: RED — new test `tests/integration/test_upgrade_sh_tmp_self_contained.py`:
  Layer 1 run from a `/tmp`-style dir with NO sibling `lib/` AND a daemon dir lacking
  `python_discovery.sh` still resolves a Python (fetch mocked via base-URL/`file://`
  fixture per the chosen mechanism).
- [ ] ⬜ **Task 2.2**: GREEN — implement the Decision 2 mechanism. Preserve existing
  precedence (daemon-dir lib → sibling → new fallback); do not regress current call sites.
- [ ] ⬜ **Task 2.3**: Update every documented manual instruction copy from Task 0.4 so
  the published flow is runnable as written.
- [ ] ⬜ **Task 2.4**: shellcheck clean; daemon restart RUNNING.

### Phase 3: F3 — Silence uv hardlink noise on overlay-fs (TDD) [G3]

- [ ] ⬜ **Task 3.1**: RED — test (extend `scripts/install/` test coverage) that on an
  overlay-fs-style target `create_venv_at_path` emits NO "Failed to hardlink"/warning
  line, while a normal fs still uses hardlink mode. Use a fixture/mock for fs detection.
- [ ] ⬜ **Task 3.2**: GREEN — in `scripts/install/venv.sh`, detect hardlink-hostile fs
  (overlay/NFS) for the target path BEFORE the first `uv sync` and set
  `UV_LINK_MODE=copy` proactively. Keep hardlink-first for normal disks. Remove the
  now-unreachable warning (or downgrade to a quiet info line). No double `uv sync`.
- [ ] ⬜ **Task 3.3**: Verify the dev-container upgrade output is clean — no warning.
- [ ] ⬜ **Task 3.4**: shellcheck clean.

### Phase 4: F4 — Surface the escape hatch in error messages (TDD) [G4]

- [ ] ⬜ **Task 4.1**: RED — test that remaining hard-failure paths (`_fail` for missing
  discovery lib; thin-shim fetch failure) print a recovery hint naming
  `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` and the manual fallback.
- [ ] ⬜ **Task 4.2**: GREEN — add the hint to the relevant error strings in
  `scripts/upgrade.sh` and the skill `upgrade.sh` thin shim.

### Phase 5: Regression hardening + acceptance gate wiring (TDD) [G5]

- [ ] ⬜ **Task 5.1**: End-to-end acceptance test "old shim → fetches new Layer 1 artifact
  → upgrade succeeds" (a pre-v3.15 shim shape calling Layer 1 with `--already-bootstrapped`).
  Model on `test_skill_upgrade_end_to_end.py`.
- [ ] ⬜ **Task 5.2**: Add the new acceptance test(s) to RELEASING.md Step 12.0 H-1 gate
  list and bump the expected count (currently 23). Update the MEMORY H-1-count note.
- [ ] ⬜ **Task 5.3**: Confirm `check_canonical_callers.sh` / shell-audit QA still pass
  (Layer 1 has self-bootstrap exemptions — verify no false positive from new logic).

### Phase 6: Integration, QA, dogfood, docs

- [ ] ⬜ **Task 6.1**: Full QA: `./scripts/qa/llm_qa.py all` — all checks pass.
- [ ] ⬜ **Task 6.2**: `uv lock` re-run if any dependency/version touched.
- [ ] ⬜ **Task 6.3**: Daemon restart RUNNING; logs clean of errors.
- [ ] ⬜ **Task 6.4**: Update `upgrade.md` skill doc + `CLAUDE/LLM-UPDATE.md` with the
  hardened flow and recovery hint.
- [ ] ⬜ **Task 6.5**: Annotate the field report `untracked/hooks-daemon-upgrade-broken.md`
  with the resolution (file is untracked — not committed).
- [ ] ⬜ **Task 6.6**: Checkpoint commits per phase; final plan-completion commit.

## Dependencies

- Related: Plan 00109 (skill thin-shim), Plan 00110 (canonical Python discovery),
  Plan 00104/00105 (self-bootstrap stanzas + bootstrap-checksums), Plan 00100 (venv
  hardlink-first decision), Plan 00047 (original `UV_LINK_MODE=copy` default).
- Blocks: next release (should carry these fixes given the field report).

## Technical Decisions

### Decision 1: Heal old shims via Layer 1 tolerance, not by re-pushing skills

**Context**: F1's broken shim is client-side and cannot be fixed in place before an upgrade.
**Options**: (A) make Layer 1 accept-and-ignore the legacy flag; (B) publish the thin-shim
as the `releases/latest/download/upgrade.sh` artifact so the re-exec target understands it.
**Decision**: **A (primary)**. Layer 1 tolerance heals every old shim regardless of which
artifact it fetches, costs ~4 lines, and is pure backward-compat. (B) couples the release
bundle to shim internals and still fails for clients fetching the `main` raw path.
**Date**: 2026-05-29

### Decision 2: G2 mechanism — finalise in Phase 0

**Context**: Layer 1 needs `python_discovery.sh` when run from `/tmp` on an old client.
**Options**: (A) self-fetch the lib from a default ref when missing (needs a baked-in
default ref/base-URL — reuse `HOOKS_DAEMON_UPGRADE_REF`/`_BASE_URL`); (B) inline a minimal
discovery fallback into Layer 1 (DRY cost, fully offline-safe); (C) the thin shim fetches
the lib into `/tmp/lib/` alongside upgrade.sh, and docs do the same.
**Decision**: **Deferred to Phase 0 Task 0.5.** Leaning C+A hybrid: shim fetches the lib
(fixes the skill path cleanly), Layer 1 self-fetches as a safety net for the manual path,
surfacing F4's hint if the fetch fails offline. Final call after Phase 0.
**Date**: 2026-05-29

### Decision 3: Proactive fs detection over warn-then-retry for uv link mode

**Context**: hardlink-first emits a scary warning on every container install (F3).
**Decision**: detect the target filesystem before the first `uv sync`; pick copy mode when
hardlink-hostile (overlay/NFS), keep hardlink-first elsewhere. Removes both the warning and
the wasted first attempt — strictly better than the current retry loop. Fall back to the
current warn-then-retry only when detection is inconclusive.
**Date**: 2026-05-29

## Success Criteria

- [ ] An old-shim re-exec (`--already-bootstrapped`) runs Layer 1 to completion (G1).
- [ ] Manual curl-to-`/tmp` upgrade works on a client whose installed daemon lacks
  `python_discovery.sh` (G2).
- [ ] Container/overlay-fs install + upgrade produces **zero** hardlink warnings (G3).
- [ ] Every remaining hard-failure path prints the `HOOKS_DAEMON_SKIP_BOOTSTRAP=1`
  recovery hint (G4).
- [ ] New regression tests for F1-F4 pass and are wired into the H-1 gate (G5).
- [ ] Documented manual upgrade instructions are runnable as written (G6).
- [ ] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                                |
| ------------------------------------------------------ | ------ | ----------- | ------------------------------------------------------------------------- |
| Layer 1 self-fetch (G2) fails offline / behind a proxy | Med    | Med         | Inline fallback (Decision 2 B) + surface F4 hint; never hard-stick        |
| Loosening the arg parser hides a real typo'd flag      | Low    | Low         | Accept only a known allowlist of historical bootstrap flags; reject rest  |
| fs detection (G3) misclassifies a filesystem           | Low    | Low         | Fall back to current hardlink-then-copy retry when detection inconclusive |
| Changing Layer 1 trips `check_canonical_callers.sh`    | Low    | Med         | Phase 5 Task 5.3 explicitly verifies the QA exemption                     |

## Notes & Updates

### 2026-05-29

- Plan created from field report `untracked/hooks-daemon-upgrade-broken.md`.
- Verified F1-F4 root causes against HEAD (v3.16.0, commit 3ebb40c) via direct reads of
  `scripts/upgrade.sh`, the skill thin-shim `upgrade.sh`, `scripts/lib/python_discovery.sh`,
  and `scripts/install/venv.sh`.
- Audited existing upgrade tests: none cover F1 or F2 — new regression tests required.
  </content>
  </invoke>

<invoke name="Read">
<parameter name="file_path">/workspace/CLAUDE/Plan/README.md
