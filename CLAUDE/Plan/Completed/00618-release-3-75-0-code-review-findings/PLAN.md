# Plan 00618: release 3 75 0 code review findings

**Status**: Complete
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The Step 10 code review of release 3.75.0 (`subagent-reports/261116-step10-code-review.md`) returned FAIL with 38 findings against `git diff v3.74.0..HEAD -- src/`: 5 blocking, 20 non-blocking defects and 13 nits. The release was aborted at that gate, as RELEASING.md requires, with no merge, tag or publish. The release branch `release/3.75.0` is kept for the re-run.

A release carries no known defect, and deferring one needs the human's explicit acceptance. The five blocking findings are all fail-open or data-loss paths introduced since the last release, so they are fixed first, test-first, with no loosening of any guard. The remaining defects are triaged: each is fixed or recorded as accepted by the owner.

## Goals

- Each blocking finding is fixed test-first, with a red test committed before the fix: B-1 (delete-branch content proof can delete unpushed work and no recovery copy exists), B-2 (the stop guard hands over any worktree under the harness directory or any locked one without a liveness check), B-3 and B-4 (the new git search-option exemption lets `git grep -G <protected>` and `git blame -S <protected>` read a protected file), B-5 (the grep/rg check skips the first searched directory when the pattern is written `-ezz` or `--regexp=zz`).
- Every non-blocking defect is fixed or has an explicit owner decision recorded.
- The nits are fixed where trivial in the touched code.
- Each fix is independently reviewed for loosening before merge.

## Non-Goals

- Re-cutting the release (the owner starts that with `/release`).
- Implementing Plan 00614, 00615 or 00617 (separate plans).

## Tasks

### Phase 1: Blocking findings

- [x] ✅ **Task 1.1**: B-1, delete-branch content-preserved proof (use the per-path net-change proof or drop the tier), with the reviewer's reproduction as the red test. Red `cd6631424`, fix `8d0e37de4`, budget nit `09f149d7c`; on main (`subagent-reports/261116-fix-b1-b2.md`).
- [x] ✅ **Task 1.2**: B-2, stop guard handover requires proof a live agent owns the worktree, and never drops a branch in the session's own set. Red `6e16b8ac8`/`9111cee6c`, fix `95e5dc55e`/`d4aa70de7`; on main (`261116-fix-b1-b2.md`, `261116-fix-b2-rework.md`).
- [x] ✅ **Task 1.3**: B-3 and B-4, the git search-option exemption applies only to the subcommands where the option takes a value; `git grep -G` and `git blame -S` stay denied for protected files. Red `9348caa50`, fix `2f3349403`; on main (`261116-fix-b3-b5.md`, follow-up `261117-fix-older-holes-review.md`).
- [x] ✅ **Task 1.4**: B-5, the grep/rg first-searched-directory check handles `-e<pattern>` and `--regexp=<pattern>` spellings. Red `9348caa50`/`d4974189c`, fix `42180df61`/`7f0331142`; on main.

### Phase 2: Non-blocking defects and nits

- [x] ✅ **Task 2.1**: Triage the 20 non-blocking defects in the report: fix each test-first, or record the owner's explicit acceptance. 17 fixed test-first and N-16 already fixed (merge `73cd364e5`, `subagent-reports/261117-phase2-defects.md`). N-7 and N-8 are D-1 and D-2, answered yes and implemented (merge `d7c7efe37`, review `261117-d1-d2-review.md`). Residuals ledgered N650 to N659 (`CLOSEOUT-AUDIT.md`).
- [x] ✅ **Task 2.2**: Fix the nits in the code touched by Tasks 1.x and 2.1. 12 of 13 fixed. T-7 is D-3, which the owner answered no (journal 2026-11-17 `111756Z`): the false positive is accepted.

### Phase 2b: Red release gate (run 43961579876 on the aborted release head)

- [x] ✅ **Task 2.3**: The Plan 00609 proof script failed the `format` check; formatted on main (`873880239`).
- [x] ✅ **Task 2.4**: Done inside the release re-run at `78999499b`. On the re-run, after the Step 1H remote-docs refresh, update `docs_sha256` in the instruction-loading contract's `META.json` through the contract refresh procedure (the refreshed memory page changed one paragraph about additional-directory loading); confirm no contract fact breaks. Done inside the release re-run, not before it.
- [x] ✅ **Task 2.5**: The playbook harness probe for the Kotlin linter timed out at 15 s on a loaded runner and the blocking gate skipped; make that probe's timeout load-scaled, test-first. Harness half on main: the playbook generator's subprocess bounds are load-scaled. Harness half: red `ce15433cc`, fix `6d309904b`. Daemon half: the owner chose D-4 option A (limit stated in release note 092); option B is carried as ledger N632.

### Phase 3: Hand-off

- [x] ✅ **Task 3.1**: Independent loosening review of Phase 1 and 2, CI green on main, a release note, then tell the owner the release can be re-run. In place: loosening reviews per fix group, CI run 44000713338 green on the Phase 2 merge, release notes 089 to 092. The owner answered D-1 to D-5 (journal `111756Z`); the re-run found S-1 and S-2, both fixed (`45f713dd2`, `b05e57cda`, `df00a1e70`, `8f3f469cd`), and v3.75.0 was tagged and merged through PR 209.

## Owner decisions

**Answered** (journal 2026-11-17 `111756Z`): D-1 yes, D-2 yes (both implemented, `d7c7efe37`), D-3 no, D-4 option A, D-5 the release was run. The cases below are kept as the record of what was decided. "Main" means the default branch at the time.

### D-1 (N-7): should `warn` mode stop the stop guard from denying?

- **Case.** The branch pools have a `mode` setting (`wip.mode`, `dormancy.mode`) with values such as `off`, `warn` and the blocking default. In `warn` mode the branch-creation guard only warns. The stop guard tests only whether the mode is not `off`, so in `warn` mode it still denies. Example: cap 1, `wip.mode: warn`, the session touched two of its own pushed open branches; the stop is denied with "open pool over cap".
- **Today.** The stop is denied in `warn` mode, as in the blocking mode. No test covers this.
- **If yes.** In `warn` mode the stop guard gives an advisory and allows the stop, matching the creation guard. This allows stops that main denies.
- **If no.** Behaviour stays; the setting's documentation should say `warn` only softens creation, not stops.
- **Choice:** yes / no. **Recommendation: yes.** A setting named `warn` that denies is a defect, and the owner who sets it has already chosen not to be blocked; add a test for both modes.

### D-2 (N-8): should the stop guard count branches on the same tip once?

- **Case.** The stop guard counts open branches by name. The other counts (open-work count, pool count, creation report) count branches that point at the same commit once. Example: branches `a` and `a2` on the same pushed commit, cap 1, the session touched `a`; the stop is denied as over cap, while the open-work count reports 1.
- **Today.** Two names on one commit count as two at stop time, so the stop guard can deny where the creation guard would not.
- **If yes.** The stop guard uses the same tip-deduplicated count; the example stop is allowed. This allows stops that main denies.
- **If no.** The counts keep disagreeing; the stop guard stays the stricter one.
- **Choice:** yes / no. **Recommendation: yes.** One open-work definition everywhere; a duplicate name holds no extra unfinished work.

### D-3 (T-7): should `bash -s <script> <name>` stop counting as a branch creation?

- **Case.** The branch-creation guard recognises a worktree setup script run through an interpreter. With `bash -s`, bash reads its program from stdin, so in `bash -s scripts/setup_worktree.sh x` the script name is only an argument and nothing is created: a false positive. But `echo 'bash "$1" "$2"' | bash -s scripts/setup_worktree.sh x` does run the script and reads identically on the command line.
- **Today.** Both forms are judged as creating `x`, so both can be denied when the pools are full.
- **If yes.** Both forms are allowed unjudged, including the stdin form that really creates a branch. This allows a creation main denies.
- **If no.** The false positive stays; the workaround is to run the script directly.
- **Choice:** yes / no. **Recommendation: no.** The false positive costs one rephrased command; the fix opens a real bypass.

### D-4 (Task 2.5, daemon half): how should the lint time budget handle load?

- **Case.** `lint_on_edit` gives a lint check up to 15 s, inside the 20 s overall deadline for the PostToolUse handler chain. On a loaded machine the Kotlin linter exceeded 15 s, and the release playbook gate reported the check as skipped. A per-language lint timeout above about 15 s (such as the documented `PHP: 30` example) is already cut off by the chain deadline today.
- **Today.** The lint budget is fixed; a slow lint is skipped, never denied. The harness half (the playbook generator's subprocess bounds) is already load-scaled.
- **Options.**
  - **A. Leave as is**, and document that per-language lint timeouts above the chain deadline have no effect.
  - **B. Give PostToolUse the three-layer event budget the Worktree events use:** a PostToolUse entry in the per-handler budget, the chain deadline and the client wait, the matching `init.sh` mirror and the registered hook timeout, then load-scale the lint budget within it; test-first, as its own plan.
  - **C. Load-scale only the lint budget.** Not recommended: above the chain deadline the reply is a "skipped" the harness does not read as inconclusive, so today's skip becomes a hard failure.
- **Recommendation: A for this release, B as a follow-up plan.** B touches every PostToolUse hook and is too wide for a release-fix plan.

### D-5: re-run the release

- **Case.** All blocking findings and the agreed non-blocking ones are fixed on main with CI green. The release itself must be started by the owner.
- **Action.** The owner types `/release`. Earlier typed authority covered a limited window and an `accept-wip` instruction; it does not carry over to this run. Task 2.4 (the contract hash refresh after the remote-docs step) is done inside that run.
- **Choice:** re-run now, or after D-1 to D-4 are decided and any "yes" is implemented. **Recommendation: decide D-1 to D-4 first**, so the release carries no open defect without explicit acceptance.

## Success Criteria

- [x] All five blocking findings are fixed, each with a test that failed before the fix.
- [x] No fix makes a guard allow anything it denied on the previous commit (per-group loosening reviews); the only loosenings are the owner-approved D-1 and D-2 (review `261117-d1-d2-review.md` PASS).
- [x] The non-blocking defects are each fixed or explicitly accepted by the owner (D-1 and D-2 yes and implemented, D-3 no, D-4 option A); every residual is in ledger 00474 (`CLOSEOUT-AUDIT.md`).
- [x] Release notes 089 to 095 were written in the pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`) and shipped in v3.75.0; they now live in `CLAUDE/UPGRADES/v3/v3.74.0-to-v3.75.0/release-notes/`. The plan's release-bound consequences all shipped in v3.75.0, so nothing remains in the holding area.

## Delivery & Milestones

- Filed after the 3.75.0 release was aborted at Step 10.
- Phase 1 (B-1 to B-5) merged to main, each fix after its red test.
- Phase 2 merged to main at `73cd364e5` (CI run 44000713338 green on the branch tip `e53eef183` that was merged): 29 of 33 items fixed, N-16 already fixed, N-7, N-8 and T-7 held for the owner.
- Owner decisions answered (journal `111756Z`); D-1 and D-2 merged at `d7c7efe37`.
- Release re-run: Step 10 re-run found S-1 (fixed, two independent reviews) and S-2 (fixed); v3.75.0 tagged and merged through PR 209.
- Close-out: every task and finding audited in `CLOSEOUT-AUDIT.md`; residuals ledgered N650 to N659.
