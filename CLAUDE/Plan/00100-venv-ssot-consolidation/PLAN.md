# Plan 00100 (v3): Venv SSOT Consolidation — Stop the Release Treadmill

**Status**: Dormant (residue scope awaits scheduling)

## Wave 4 close-out note (Plan 00107)

Plan 00107 Wave 4 audit confirmed that Phases 0–3.9 are **fully shipped** in
v3.9.0 / v3.10.0 / v3.11.0. The canonical SSOT resolver
(`scripts/lib/resolve_venv.sh`), `.daemon-metadata.json` writers, dead-code
removal (`create_venv` / `recreate_venv` gone), Phase 0 field-pain fixes
(`uv sync` file-visibility, polling restart verifier, skill wrapper Python
pre-check), path slug, and eager upgrade cleanup all landed and are covered
by the H-1 acceptance gate. Full task-level detail for every shipped phase:
[SHIPPED-PHASES.md](SHIPPED-PHASES.md).

**Residue scope** (not yet shipped):

- **Phase 3.5.2–3.5.7**: carried by
  [Plan 00456](../Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md)
  (GitHub #53, merged at `9e2f74cd`). There, a hook finding no venv for its
  path starts ONE detached, venv-locked build when every precondition holds,
  names the missing condition when one fails, and never suggests `--force`.
  This phase is no longer residue here.
- **Phase 4**: Concurrency protection (flock around `ensure_venv` mutations)
- **Phase 5**: Parameterised end-to-end upgrade-cycle acceptance test
  (`test_full_upgrade_cycle.py`) — blocked by Phase 4
- **Phase 6**: Release notes + post-upgrade task documentation

**Decision (Plan 00107 Wave 4)**: Defer the Phase 3.5 / 4 / 5 / 6 residue to
a future release. The reasons mirror the Plan 00085 deferral:

- The residue is fresh implementation work (concurrency primitive, advisory
  handler wiring, end-to-end test infrastructure) — not audit-and-close
- The v3.12.0 batch is already substantial; adding flock + bootstrap-fallback
  wiring increases regression surface in the venv hot path right after
  v3.11.0 hardened it
- The residue is internally coherent and well-suited to its own dedicated
  release (e.g. v3.13.0 "venv self-healing & concurrency")

Plan 00100 stays Active in the index, ready to execute in a dedicated session.
**Created**: 2026-04-23
**Revised**: 2026-04-24 (v3 — path slug + eager upgrade cleanup + self-healing bootstrap)
**Prior Revision**: 2026-04-23 (v2 — addresses CRITIQUE-v1.md)
**Started**: 2026-04-23
**Owner**: TBD
**Priority**: Critical
**Type**: Bug Fix / Architectural Consolidation
**Recommended Executor**: Opus (Sub-Agent Teams)
**Execution Strategy**: Sub-Agent Teams
**Predecessor**: Plan 00099 (Python-Fingerprint Venv Isolation) — shipped v3.7.0 and triggered the treadmill
**Supersedes**: PLAN-v1.md (see CRITIQUE-v1.md for the hostile-review findings that drove v2)

Revision history (v1 → v2 → v3 change tables, the field evidence that
seeded Phase 0, and the full Technical Decisions log with reasoning):
[DECISIONS.md](DECISIONS.md).

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

### Phase 0: Field-Pain Fixes (LAND FIRST) — SHIPPED

All tasks (0.1–0.5) complete; full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-0-field-pain-fixes-land-first).

**Success gate**: The three field-reported scenarios are covered by passing tests. The user's original `/hooks-daemon upgrade` command, re-run against HEAD on a host with `python3`=3.9 and `python3.13`=3.13.11, either succeeds cleanly OR fails with actionable messaging and leaves the daemon state unchanged. Met.

---

### Phase 1: Delete Dead Code — SHIPPED

All tasks (1.1–1.5) complete; full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-1-delete-dead-code).

**Success gate**: `./scripts/qa/run_all.sh` green. Daemon status → RUNNING. Grep for `untracked/venv"` (bare legacy path string) returns zero hits outside cleanup/migration logic. Met.

---

### Phase 2: Collapse Four Resolvers Into One Python SSOT — SHIPPED

All tasks (2.1–2.7) complete; full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-2-collapse-four-resolvers-into-one-python-ssot).

**Success gate**: Grep for resolver precedence logic returns exactly one definition (Python). Bash wrappers each < 20 lines. All Phase 0 + 1 tests still pass. `ensure_venv` rejects legacy path. Met.

---

### Phase 3: Persist Installer Choices (Eliminate Recompute Disagreement) — SHIPPED

All tasks (3.0–3.9) complete; full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-3-persist-installer-choices-eliminate-recompute-disagreement).

**Success gate**: A venv built at HEAD on python 3.13 and queried under `python3`=3.11 on PATH resolves correctly via `.daemon-metadata.json` without any scan fallback. Missing persisted Python triggers recovery, not hard failure. `untracked/` after `hooks-daemon upgrade` contains exactly one `venv-*/` directory. Met.

---

### Phase 3.5: Self-Healing Bootstrap (reopens Plan 00099 Task 4.2)

**Why**: Current behaviour on missing venv is "error, run installer manually". Friction for every fresh-clone / post-prune / cross-env first-start. User directive: if the preconditions are unambiguous, bootstrap inline; otherwise emit a hook for LLM-guided recovery.

- [x] ✅ **Task 3.5.1**: Define the "inline-safe" precondition predicate — SHIPPED, full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-35-task-351-the-inline-safe-precondition-predicate)
- [ ] ⬜ **Task 3.5.2**: Wire daemon startup to call `ensure_venv` when resolver finds no current venv AND `can_inline_bootstrap` says yes
  - [ ] ⬜ Hook site: `scripts/init.sh::validate_venv` → on failure, branch on `BootstrapDecision`
  - [ ] ⬜ Inline path: invoke `ensure_venv` via the Python SSOT CLI (from Phase 2) with a timeout ceiling (180s) — log progress, stream uv output
  - [ ] ⬜ On success: continue startup as normal
  - [ ] ⬜ On inline failure or timeout: fall through to LLM-guided path (Task 3.5.3)
- [ ] ⬜ **Task 3.5.3**: LLM-guided fallback when preconditions NOT all green
  - [ ] ⬜ Emit a structured error JSON to stderr describing exactly which precondition(s) failed and the remediation command for each
  - [ ] ⬜ Add a SessionStart handler `venv_missing_advisor` that detects the no-venv state on session start and injects actionable guidance into context (install command, required Python version, uv install instructions per-OS)
  - [ ] ⬜ Advisory-only handler (never blocks); priority ~53 (early advisory range)
  - [ ] ⬜ Tests: `tests/unit/handlers/session_start/test_venv_missing_advisor.py` + integration test verifying the hook fires when venv absent
- [ ] ⬜ **Task 3.5.4**: Concurrency — inline bootstrap MUST respect the flock from Phase 4 (two simultaneous first-starts don't race)
  - [ ] ⬜ Ordering note: Phase 4 ships the flock primitive; Phase 3.5 depends on it. If Phase 3.5 lands first, use a PID-file lock as interim and migrate when Phase 4 lands.
- [ ] ⬜ **Task 3.5.5**: Acceptance test in a fresh container (no venv, uv pre-installed) — daemon starts, bootstraps, ends in RUNNING state with exactly one current-fingerprint venv
- [ ] ⬜ **Task 3.5.6**: Acceptance test with uv absent — daemon surfaces the advisory, does NOT attempt bootstrap, does NOT corrupt anything
- [ ] ⬜ **Task 3.5.7**: Full QA + daemon restart

**Note**: Tasks 3.5.2–3.5.7 as scoped above are carried by
[Plan 00456](../Completed/00456-missing-venv-self-heals-and-repair-runs-without-one/PLAN.md)
(see the "Residue scope" note at the top of this document) and are no
longer open work of this plan; the checklist is kept here for historical
task-shape reference.

**Success gate**: Fresh clone with `uv` installed → `hooks-daemon status` on first invocation reports RUNNING without a separate install step. Fresh clone without `uv` → clear advisory, zero mutation, daemon does not claim to be running.

---

### Phase 4: Concurrency Protection — SHIPPED

All tasks (4.0–4.4) complete; full detail in [SHIPPED-PHASES.md](SHIPPED-PHASES.md#phase-4-concurrency-protection). Landed via Plan 00362; the daemon restart and full QA run for this work belong to that plan's merge session.

**Success gate**: Concurrency test passes deterministically over 20 iterations. Bind-mount behaviour verified. Met.

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

Full decision log (Decisions 1–9), each with context, trade-off and date:
[DECISIONS.md](DECISIONS.md#technical-decisions).

## Success Criteria

- [ ] Phase 0: `verify_venv` succeeds on delayed-visibility filesystems without a retry loop (test passes)
- [ ] Phase 0: `restart_daemon_verified` succeeds when daemon child takes 1200ms to write PID (test passes)
- [ ] Phase 0: Skill wrapper emits actionable error + exact `HOOKS_DAEMON_PYTHON=...` command when `python3` < minimum, without touching daemon state
- [ ] Phase 0: The exact scenario on `/srv/example-app` (2026-04-23) runs clean end-to-end against HEAD
- [ ] Phase 3: `uv.lock` committed; CI `uv lock --check` passes
- [ ] Phase 3: Resolver falls back gracefully when persisted Python is missing (test passes)
- [ ] Phase 3 (v3): Path slug in venv dir name — host view and container view of same project get distinct venv dirs even when Python fingerprints collide (test passes)
- [ ] Phase 3 (v3): `hooks-daemon upgrade` leaves exactly one `venv-*/` dir in `untracked/` after success; rollback preserves prior state on failure
- [ ] Phase 3.5 (v3): Fresh clone with `uv` available → daemon self-bootstraps on first start → RUNNING status
- [ ] Phase 3.5 (v3): Fresh clone without `uv` → advisory surfaces via SessionStart handler; zero mutation to filesystem
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

Dated narrative (v1/v2/v3 revision history) lives in this plan's
[JOURNAL/](JOURNAL/); see the 2026-09-24 `finding` entry titled
"Notes & Updates relocated from PLAN.md" for the migrated content, and the
same day's `decision` entry for the Phase 3.5 residue call recorded in the
header above.
