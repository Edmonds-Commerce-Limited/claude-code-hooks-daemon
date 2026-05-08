# Plan 00105: v3.11.0 Stability Hardening — close the gaps that let v3.10.0 ship a SEV-1

**Status**: In Progress
**Created**: 2026-05-01
**Owner**: Claude (Opus 4.7)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded with focused agent delegation for audits

## Overview

v3.10.0 added an H-1 acceptance gate specifically to prevent another v3.9.x-style field regression. The gate's fixture synthesised state via `write-venv-metadata` directly instead of running the actual `install.sh` → `ensure_venv` → `verify_venv` chain. As a result v3.10.0 shipped with `print_info` writing to stdout — corrupting every `VAR=$(ensure_venv ...)` capture in the install scripts — and broke every existing user's upgrade in the field. v3.10.1 was a SEV-1 hotfix.

This plan closes the structural gaps that let that escape happen, and the deferred items from Plan 00104 that should have shipped in v3.10.0.

## Goals

1. Make the H-1 acceptance gate exercise the actual `install.sh` end-to-end against a clean fixture project. Any future bug in the install chain — print-on-stdout, missing dependency, broken helper, anything — fails QA before tagging.
2. Add a static check + dynamic test that asserts every `scripts/install/*.sh` helper called via `VAR=$(fn ...)` produces an uncorrupted capture. Catch the v3.10.0 bug class permanently.
3. Audit every `scripts/install/*.sh` helper for the print-before-echo anti-pattern. Fix any other instances.
4. Land deferred Task 5.1.B / Decision 3.B from Plan 00104: skill-side self-bootstrap with sha256 verification for `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` (so far only `upgrade.sh` is protected).
5. Land deferred Task 5.3 from Plan 00104: `verify_venv` overlay-fs retry (Issue #5 from 2026-05-01 field report) and `venv.sh:465` silent-fallback removal (Opus review C-6).
6. Housekeeping: move Plan 00103 to `Completed/` (it shipped as v3.9.1, the index still says "Not Started").

## Non-Goals

- No new handler additions or removals.
- No new user-facing features.
- No structural refactors beyond what each goal requires.
- Not addressing every theoretical install-path regression — only the bug classes the v3.10.x experience proves are live.

## Context & Background

The v3.9.0 field report (Plan 00104 context dir) named six issues. v3.9.1 patched five resolver sites independently. v3.10.0 consolidated to one canonical resolver library, added an H-1 acceptance gate, and shipped — with a regression in `output.sh` that the gate didn't exercise. v3.10.1 fixed the regression and added a focused `VAR=$(fn)` capture test for `output.sh`.

The lesson, captured in `feedback_acceptance_gates_must_run_real_path.md`: a gate's fixture must run the actual production code path. Synthetic fixtures give false confidence. This plan operationalises that lesson.

## Tasks

### Phase 1: H-1 gate runs `install.sh` end-to-end (Goal 1)

The single highest-leverage item. Once this is in place, any bug class in the install chain — including the next print-before-echo regression — fails QA before tagging.

- [x] ✅ **Task 1.1**: Add `tests/acceptance/test_install_sh_end_to_end.py` with one case: build a fresh fixture project (no `.claude/`, no venv), run `scripts/install.sh` against it under a controlled environment, assert (a) exit code 0, (b) `.daemon-metadata.json` exists with `python_path` pointing at the venv's own `bin/python`, (c) `daemon-cli.sh status` reports daemon RUNNING.
- [x] ✅ **Task 1.2**: Wire the new case into `RELEASING.md` Step 12.0 alongside the existing diagnostic-script gate. Make the BLOCKING wording cover both files.
- [ ] ⬜ **Task 1.3**: Add a second case for the upgrade path: pre-load a fixture with the v3.10.0 source layout, then run `scripts/upgrade.sh` and assert the same daemon-RUNNING outcome. This guards against upgrade-only regressions.
- [x] ✅ **Task 1.4**: Confirm the v3.10.0 print_info bug WOULD fail this gate — temporarily revert `output.sh`, run the new case, see the failure, restore `output.sh`, see it pass. **VERIFIED 2026-05-01**: with `print_info` reverted to write to stdout, the test fails with the EXACT bug signature: `Virtual environment Python not found: → ensure_venv: creating venv at <path>\n<path>` (the print_info message and ensure_venv's echoed venv path concatenated into the `VAR=$(ensure_venv ...)` capture). Restoring `print_info` restores the test to green.

**Bonus bug fix (caught by Task 1.1's first run)**: `scripts/install_version.sh` line 243 fell back to `git rev-parse --short HEAD` when no exact tag matched. The 7-char SHA fails `write-venv-metadata`'s `vMAJOR.MINOR.PATCH` Pydantic validator and silently skips writing `.daemon-metadata.json` on every non-release-tag install. Fixed by reading `pyproject.toml` as the canonical fallback. This is a sister-bug to the v3.10.0 SEV-1 — same silent-degradation class — and exactly the kind of latent bug Plan 00105 Goal 1 is meant to catch.

### Phase 2: VAR=$(fn) capture-corruption static + dynamic check (Goal 2)

- [x] ✅ **Task 2.1**: Wrote `scripts/qa/audit_capture_corruption.py` (the static analyser) and `scripts/qa/run_capture_corruption_check.sh` (the wrapper). Implementation went deeper than the original task wording: two complementary rules (capture-corruption rule via `$(name ...)` callsite detection + log-helper rule for `print_*`/`log_*`/`warn_*`/`err_*`/`fail_*`/`die_*`/`info_*` functions). Either rule alone would have missed the v3.10.0 SEV-1 (the captured-function rule alone misses log helpers not yet captured but captured in future code; the log-helper rule alone misses non-conventionally-named functions captured today). Together they attack the same root cause from two angles. **Design decisions**: (a) terminal-return position detection uses proper if/case nesting tracking with `depth` counter and per-depth `in_alt_at[depth]` state — earlier flat heuristic conflated "in alt branch of current if" with "anywhere alt was ever entered", causing false negatives on sequential mid-function emits. (b) Function-level marker `# capture-audit: allow -- <reason>` in the comment block immediately above `name() {` exempts the whole function from the capture-corruption rule. Used to disambiguate `scripts/venv-include.bash::ensure_venv` (legacy, called as `ensure_venv || exit 1`, never captured) from `scripts/install/venv.sh::ensure_venv` (modern, captured via `VAR=$(ensure_venv ...)`).
- [x] ✅ **Task 2.2**: Wired as 13th QA gate in `scripts/qa/run_all.sh` and registered in `scripts/qa/llm_qa.py` TOOL_REGISTRY (between `canonical_callers` and `smoke_test`). JSON output at `untracked/qa/capture_corruption.json`.
- [x] ✅ **Task 2.3**: Real-repo violations found and fixed: (a) `scripts/install/output.sh` `fail_fast()` lines 130-131 — added `>&2` to two unredirected echoes; (b) `scripts/venv-include.bash::ensure_venv` — added function-level marker block (legacy non-captured function, see Task 2.1 design notes). Audit now reports 0 violations on the real repo. Unit tests at `tests/unit/qa/test_audit_capture_corruption.py` cover both rules + a real-repo smoke test (12 tests, all passing).
- [x] ✅ **Task 2.4**: Wrote `tests/integration/test_install_helpers_capture_uncorrupted.py` (11 tests, all passing). Covers the full inventory of cross-function `VAR=$(fn ...)` capture sites in `scripts/install/*.sh`: `get_snapshot_dir`, `get_daemon_dir` (both modes), `detect_install_mode` (no-config + self-install yaml), `detect_project_root`, `detect_project_root_current_dir`, `get_python_version`, `get_python_major_minor`, `python_venv_fingerprint`, plus a script-level test for `config_diff_analyzer.sh` (where `extract_handlers` is captured internally; sourcing the script standalone is not feasible because it has top-level `set -euo pipefail` + arg validation, so the dynamic test invokes the whole script and asserts its stdout is parseable JSON with no leaked progress messages). Each test uses sentinel-bracketed byte-exact capture and asserts the captured value matches the documented contract. **Bug-class catcher verified**: temporarily added `echo "DEBUG: about to return daemon dir"` inside `get_daemon_dir` (the v3.10.0 bug shape — unredirected stdout in a captured function) and confirmed `test_get_daemon_dir_self_install` failed with the exact bug-class signature: `'DEBUG: about to return daemon dir\nproject_root'`. Reverted the intentional break and re-ran: all 11 pass. Expensive sites (`ensure_venv` triggering venv creation, `get_daemon_status` starting a daemon) are exercised by `tests/acceptance/test_install_sh_end_to_end.py` instead — duplicating them here would just slow the test suite.

### Phase 3: Audit `scripts/install/*.sh` for the print-before-echo anti-pattern (Goal 3)

Read each file. For every function that ends in `echo "$value"` or `printf '%s\n' "$value"`, walk every other statement in the function body and confirm none writes to stdout. Fix violations.

- [ ] ⬜ **Task 3.1**: Audit `venv.sh` (the v3.10.0 site).
- [ ] ⬜ **Task 3.2**: Audit `venv_resolver.sh`, `prerequisites.sh`, `validation.sh`, `daemon_control.sh`, `python_fingerprint.sh`, `parse_min_python.sh`, `project_detection.sh`, `mode_guard.sh`, `gitignore.sh`, `hooks_deploy.sh`, `slash_commands.sh`, `config_diff_analyzer.sh`, `config_preserve.sh`, `rollback.sh`, `test_helpers.sh`.
- [ ] ⬜ **Task 3.3**: Fix every violation. Add a regression test for each (extending Task 2.4's matrix).
- [ ] ⬜ **Task 3.4**: Confirm Phase 2's static check now reports zero violations.

### Phase 4: Skill-side self-bootstrap for the diagnostic scripts (Goal 4 — Plan 00104 Task 5.1.B / Decision 3.B)

Currently only the skill's `upgrade.sh` self-bootstraps from the GitHub release artifacts with sha256 verification. `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` use whatever stale copy the user has locally. If any of those scripts ship a bug, users on stale skill copies have no auto-recovery.

- [ ] ⬜ **Task 4.1**: Extend `bootstrap-checksums.txt` manifest to cover `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` in addition to `upgrade.sh`.
- [ ] ⬜ **Task 4.2**: Update `scripts/release/build_bootstrap_checksums.sh` accept all four scripts as arguments. Update `RELEASING.md` Step 14 accordingly.
- [ ] ⬜ **Task 4.3**: Add a self-bootstrap stanza at the top of each of `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` (mirroring the existing `upgrade.sh` stanza): fetch the latest body and manifest from `releases/latest/download`, verify, re-exec.
- [ ] ⬜ **Task 4.4**: Wire the H-1 acceptance gate's existing self-bootstrap test cases (currently only for `upgrade.sh`) to also cover the three new scripts.
- [ ] ⬜ **Task 4.5**: Activate the placeholder DEFERRED case 6 in `tests/acceptance/test_diagnostic_scripts.py` — `daemon-cli.sh` self-bootstraps on first invocation per session.

### Phase 5: `verify_venv` overlay-fs retry + venv.sh silent-fallback removal (Goal 5 — Plan 00104 Task 5.3)

- [ ] ⬜ **Task 5.1**: Add overlay-fs detection + retry to `verify_venv` in `scripts/lib/resolve_venv.sh`. On `EBUSY`, sleep briefly, retry once. On second failure, exit 6 with directive.
- [ ] ⬜ **Task 5.2**: Remove the silent fallback at `venv.sh:465` (Opus review C-6 from Plan 00104). Replace with explicit failure + directive.
- [ ] ⬜ **Task 5.3**: Add regression tests for both — overlay-fs retry case (mocked) and the silent-fallback path (asserts the new explicit failure message).

### Phase 6: Plan 00103 housekeeping (Goal 6)

- [ ] ⬜ **Task 6.1**: Read `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/PLAN.md` and update Status to Complete with v3.9.1 release date.
- [ ] ⬜ **Task 6.2**: `git mv CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast CLAUDE/Plan/Completed/00103-v3.9.1-venv-resolution-failfast`.
- [ ] ⬜ **Task 6.3**: Update `CLAUDE/Plan/README.md`: remove from Active, add to Completed with brief summary.

### Phase 7: Release as v3.11.0 (MINOR — adds new QA gate + new acceptance gate cases + new self-bootstrap stanzas)

- [ ] ⬜ **Task 7.1**: Run full QA. 13/13 must pass.
- [ ] ⬜ **Task 7.2**: Run `/release minor`.
- [ ] ⬜ **Task 7.3**: Verify bootstrap artifacts (now four files) reachable at `releases/latest/download` URL with sha256 match.

## Dependencies

- Depends on: v3.10.1 (released, in main).
- Blocks: nothing immediately, but every future release benefits.

## Success Criteria

- [ ] H-1 acceptance gate runs `install.sh` end-to-end and `upgrade.sh` end-to-end, both asserting daemon RUNNING.
- [ ] 13th QA gate (capture-corruption check) integrated and reports zero violations.
- [ ] All four diagnostic scripts (`upgrade.sh`, `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh`) self-bootstrap with sha256 verification.
- [ ] `verify_venv` retries on overlay-fs EBUSY; `venv.sh:465` silent fallback removed.
- [ ] Plan 00103 moved to `Completed/`, README index updated.
- [ ] v3.11.0 tagged and published.

## Risks & Mitigations

| Risk                                                                     | Impact | Probability | Mitigation                                                                              |
| ------------------------------------------------------------------------ | ------ | ----------- | --------------------------------------------------------------------------------------- |
| End-to-end `install.sh` fixture is flaky in CI                           | High   | Medium      | Use deterministic temp dir, no network reads, mock GitHub fetches                       |
| Self-bootstrap stanza adds latency to every diagnostic-script invocation | Medium | Medium      | Cache the bootstrap-completed marker per session; only re-bootstrap on first invocation |
| Capture-corruption static check has false positives                      | Low    | Medium      | Allowlist documented helpers that intentionally write to stdout for piping              |
| Phase 3 audit turns up many fixes that could regress other behaviour     | Medium | Low         | Each fix gets a regression test; QA must remain green between fixes                     |

## Notes & Updates

### 2026-05-01

- Plan created in response to v3.10.1 SEV-1 hotfix shipping. Standing directive after that: "do we have more work to do on the stability front or has this done it?" → user answered "go" to address the gaps.
- Highest leverage is Phase 1 (real `install.sh` end-to-end gate). Starting there.
