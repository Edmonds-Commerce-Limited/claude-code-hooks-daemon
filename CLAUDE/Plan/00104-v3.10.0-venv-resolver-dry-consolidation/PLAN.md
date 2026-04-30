# Plan 00104: v3.10.0 — venv resolver DRY consolidation (structural)

**Status**: Not Started — blocked on Plan 00103 (v3.9.1 patch ships first)
**Created**: 2026-04-30
**Owner**: TBD
**Priority**: Medium (structural debt cleanup, not a regression)
**Recommended Executor**: Opus 4.6 (Sub-Agent Teams) — complexity warrants strategic oversight per three prior FATAL reviews of the bundled-with-patch attempt.
**Execution Strategy**: Sub-Agent Teams with explicit commit-by-commit ordering and per-commit verification gates.

## Overview

The five-site duplication of venv-resolution logic across `_resolve-venv.sh`, `venv-include.bash`, `scripts/install/venv_resolver.sh`, `init.sh::_resolve_python_cmd`, and `scripts/install/venv.sh:261` violates DRY/SSOT. After Plan 00103 (v3.9.1) lands per-site fixes for the field-reported regression, those five sites all do roughly the same thing in five places. This plan consolidates them into a single canonical bash library.

This plan was originally bundled with Plan 00103 (v3.9.1). Three consecutive FATAL Opus reviews of the combined plan demonstrated that bundling "patch release" with "structural refactor" creates irreversibly-coupled implementation bugs (caller-count miscount, wrong file paths, missing commit ordering, low-fidelity acceptance fixtures). Reviewer recommended splitting; user concurred. This plan is the structural half.

## Goals

1. **Single canonical bash library** at `scripts/lib/resolve_venv.sh` with public API (`resolve_venv_python`, `resolve_venv_dir`) sourced by all venv-resolution sites.
2. **Five sites collapse to shims** of 3–8 lines each. `scripts/install/venv_resolver.sh` collapses to a re-export shim (NOT deletion, per Review #3 F12 — 9 callers exist; deletion is unsafe).
3. **Hot-path latency budget** for `init.sh::_resolve_python_cmd` after consolidation: \<5ms median per hook fire (preserve fingerprint cache, optimise `source` cost).
4. **Static-check QA gate** `scripts/qa/check_canonical_callers.sh`: greps for forbidden patterns (`${[A-Z_]*:-python3}` parameter expansion outside bootstrap; bare `python3` in candidate-list arrays outside bootstrap; raw `python3 paths.py` outside Layer-1; canonical library emitting unversioned legacy path). Wired into `run_all.sh` as the 11th check.
5. **Multi-host NFS hostname-dimension fail-fast** when `HOSTNAME` is unset AND multiple hostname-suffixed venvs exist (R22 from Review #3).
6. **`requires-python` cross-check** on probed bootstrap interpreters (R23 from Review #3) — bootstrap rejects an interpreter if it falls outside `pyproject.toml`'s `requires-python` constraint, even if `>= 3.11`.
7. **`set -euo pipefail` exit-vs-return contract** (F17 from Review #3) — canonical library returns from sourced-and-called-as-function, exits only when run as a top-level script.

## Non-Goals

- Anything in Plan 00103 (per-site patches, deferred tomllib, bootstrap explicit probe). Those land first.
- Idle-window daemon death investigation.
- Compact-event correlation.

## Context & Background

- Plan 00103: `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/PLAN.md` (the patch).
- Three reviews of the v1 ambitious plan that bundled patch + structural: `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/context/2026-04-30-review-{1,2,3}-opus*.md`.
- v1 ambitious plan (superseded): `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/PLAN-v1-ambitious-superseded.md`.

The three reviews surfaced 18 amendments and 7 fatal findings. Most apply directly to this plan and must be addressed in its design phase.

## Pre-Design Required Reading

Before drafting tasks for this plan, the executor MUST read all three review files plus the v1 ambitious plan, then enumerate which findings are addressed in the design vs. deferred. The reviews already did the analysis — don't redo it from scratch.

Specific review #3 findings this plan must resolve (with file/line specificity):

- **F12**: `venv_resolver.sh` has 9 callers (not 2). Plan 00103 keeps the file in place; this plan converts it to a shim, NOT deletion. Enumerate the 9 callers in the design phase before any code is written.
- **F13**: `init.sh` lives at `/workspace/init.sh` (repo root), not in skill bundle. Three deploy locations exist: skill-bundle, self-install repo, downstream-clone. Source-path resolution must work in all three.
- **F14**: Probe-list `python3` vs parameter-expansion `:-python3` are different syntactic categories. Static check must cover BOTH.
- **F15**: Phase 4 of the v1 plan had 11 coupled tasks with no commit ordering. This plan must have explicit per-commit verification gates.
- **F16**: Acceptance fixture must reproduce multi-Python field-bug topology (handled in Plan 00103; this plan inherits but should not regress).
- **F17**: `set -euo pipefail` cascade through `venv-include.bash:56`. Canonical library API must distinguish sourced-as-function (`return`) vs invoked-as-script (`exit`).
- **F18**: Static check needs positive-include allowlist and inline marker comments, not line-anchor allowlist.
- **R17**: Hot-path latency budget — benchmark before/after.
- **R18**: Fingerprint cache chicken-and-egg — fingerprint requires Python invocation but cache is keyed on fingerprint.
- **R19**: `HOOKS_DAEMON_PYTHON` override hard-precedence semantics.
- **R20**: `tomllib.TOMLDecodeError` deferred-import via local helper (handled in Plan 00103).
- **R21**: Pre-v3.7.0 install upgrade-path circular dependency.
- **R22**: Multi-host NFS no-`HOSTNAME` fail-fast.
- **R23**: Bootstrap `requires-python` cross-check.
- **R24**: `check_canonical_callers.sh` actionable error output.
- **R25**: `upgrade.sh` preflight test sequencing.

## High-Level Phase Outline (to be detailed during design phase)

1. **Phase 1: Design refresh and Opus review gate** — Walk through every Review #3 finding against the live code tree (re-grep, don't trust prior enumerations). Spawn Opus 4.6 hostile review pass before any code.
2. **Phase 2: TDD failing tests** — Parity-matrix test, `set -euo pipefail` cascade test, hot-path latency benchmark, multi-host fail-fast test, static-check tests.
3. **Phase 3: Canonical library** — Write `scripts/lib/resolve_venv.sh` with public API and exit-vs-return contract. Source-path resolution robust across all three deploy locations.
4. **Phase 4: Site shims** — One commit per site (5 commits, explicit ordering). `venv_resolver.sh` collapses to re-export shim, NOT deletion.
5. **Phase 5: Static-check QA gate** — Author and wire `check_canonical_callers.sh`. Positive-include allowlist; inline marker comments for legitimate exceptions.
6. **Phase 6: Multi-host NFS + `requires-python` cross-check** — Add fail-fast logic to canonical and bootstrap.
7. **Phase 7: Hot-path optimisation** — Benchmark `init.sh` source-cost; optimise if median resolve time exceeds 5ms.
8. **Phase 8: Verification + acceptance** — Multi-Python fixture (inherited from Plan 00103) plus parity-matrix and per-host fixtures.
9. **Phase 9: Release** — `/release minor` for v3.10.0 (this is a structural change with new public bash API; minor bump justified).

## Dependencies

- **Depends on**: Plan 00103 complete (v3.9.1 released). Without 00103, the per-site fixes and 00104's canonical-library targets diverge.
- **Blocks**: Future hot-path optimisation work, multi-host deployment work.
- **Related**: Plan 00100 (venv SSOT — this plan refines its shell-wrapper layer with the DRY library).

## Success Criteria

- [ ] `scripts/lib/resolve_venv.sh` exists with documented public API.
- [ ] All five resolver sites are 3–8-line shims sourcing the canonical.
- [ ] `venv_resolver.sh` retained as re-export shim (9 callers preserved).
- [ ] `scripts/qa/check_canonical_callers.sh` wired into `run_all.sh` and passes.
- [ ] Hot-path latency: `init.sh::_resolve_python_cmd` median resolve \<5ms verified by benchmark.
- [ ] Multi-host NFS without `HOSTNAME` set fails fast with clear directive when multiple hostname-suffixed venvs exist.
- [ ] Bootstrap rejects interpreter outside `requires-python` even when `>= 3.11`.
- [ ] Sourced-as-function paths use `return`; invoked-as-script paths use `exit`. Test verifies `venv-include.bash:56` does not kill caller shell on `set -euo pipefail`.
- [ ] All Plan 00103 acceptance tests still pass after consolidation.
- [ ] Each commit in Phase 4 leaves daemon RUNNING and QA green.
- [ ] v3.10.0 released via `/release minor` with all 15 gates green.

## Risks & Mitigations

| Risk                                                              | Impact | Probability                                                           | Mitigation                                                                                                                     |
| ----------------------------------------------------------------- | ------ | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Bundling structural work back into a patch release                | High   | Medium                                                                | This plan is explicitly minor-version. Reject any pressure to backport into v3.9.x.                                            |
| Source-path resolution fragility across 3 deploy locations        | High   | Medium                                                                | Explicit deploy-location enumeration in Phase 3. Test fixture per location.                                                    |
| Hot-path latency regression after consolidation                   | Medium | Medium                                                                | Phase 7 benchmark gate. Roll back consolidation if latency exceeds budget.                                                     |
| Static check false positives on documentation/release notes       | Medium | High                                                                  | Phase 5 positive-include allowlist; inline marker comments per F18.                                                            |
| Incomplete `venv_resolver.sh` caller enumeration (F12 root cause) | High   | Low (Review #3 enumerated 9; verify against live tree before Phase 4) | Phase 1 design refresh re-greps the live tree.                                                                                 |
| `set -euo pipefail` cascade kills caller shell (F17)              | High   | High if naive                                                         | Phase 3 explicit exit-vs-return contract. Phase 2 test `test_resolver_when_sourced_under_pipefail_does_not_kill_caller_shell`. |

## Notes & Updates

### 2026-04-30 — Plan stub created

- Split from the v1 ambitious plan in 00103 after three Opus FATAL reviews.
- Reviewer's recommendation: this plan ships in weeks, not days. Get 00103 patch live first.
- Phase outline is intentionally high-level. Detailed task breakdown happens in Phase 1 (design refresh) AFTER 00103 ships, when the canonical-library targets are stable.
