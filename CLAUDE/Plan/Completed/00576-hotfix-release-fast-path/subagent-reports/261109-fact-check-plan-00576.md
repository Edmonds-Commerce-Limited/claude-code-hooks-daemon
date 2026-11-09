# Fact check: Plan 00576 PLAN.md

Worktree: /workspace/untracked/worktrees/hotfix-release-fast-path (branch hotfix-release-fast-path)

Result: 19 claims: 18 verified, 0 refuted, 1 unverifiable. Two minor drift notes (not refutations) below.

Tests run: `tests/unit/qa/test_run_corpus_qa.py`, `test_release_gate_layout.py`, `tests/integration/test_release_skill_hotfix_mode.py` give 41 passed. `test-project-handlers` gives 300 passed.

| #   | Claim                                                                                                                                                                               | Verdict           | Evidence                                                                                                                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | invoke.sh accepts `hotfix` as either argument (`hotfix`, `X.Y.Z hotfix`)                                                                                                            | VERIFIED          | invoke.sh arg loop `hotfix) RELEASE_MODE="hotfix"`; any other arg becomes VERSION                                                                     |
| 2   | The bump is a patch                                                                                                                                                                 | VERIFIED          | `""` becomes `patch`; `major`/`minor` exit 2                                                                                                          |
| 3   | In hotfix mode it passes `--accept` to release-slate-check, and the report still prints                                                                                             | VERIFIED          | `SLATE_ACCEPT_FLAG="--accept"` for hotfix; `--accept` exists in cli.py:4732 and release_slate.py                                                      |
| 4   | It tells the orchestrator to write `"mode": "hotfix"` and prints the fast-path list                                                                                                 | VERIFIED          | invoke.sh HOTFIX heredoc                                                                                                                              |
| 5   | RELEASING.md "Hotfix fast path" owns the step list: skip 1H, 1c, the Step 7 Opus review; Step 6 unchanged; Step 10 hotfix range only; Step 12 is 12.0 plus targeted tests           | VERIFIED          | RELEASING.md:271-309, table rows 1H, 1c, 6, 7, 10, 12                                                                                                 |
| 6   | "No code validates the top-level keys strictly (only the `ci` record, in check_release_ci.py)"                                                                                      | VERIFIED          | check_release_ci.py:85-88 rejects unknown keys of `ci` only. release_merge_freeze.py and branch_stop_gate.py do no top-level key validation.          |
| 7   | `release_blocker`'s deny message names the mode: hotfix points at the fast path and states its acceptance scope; an unrecognised mode is named and the standard pipeline is assumed | VERIFIED          | release_blocker.py `_pipeline_paragraph` (lines ~276-306), used in the deny at ~330. TestTheReleaseModeIsNamed exists at test_release_blocker.py:573. |
| 8   | run_corpus_qa.py previously set `passed: not findings` and exited 1 on any finding                                                                                                  | UNVERIFIABLE-HERE | The current tree has no old code. `git show HEAD~N:scripts/qa/run_corpus_qa.py` would settle it, but history is out of scope for this check.          |
| 9   | It now passes and exits 0 unless a block finding or an unknown severity is present (fail closed)                                                                                    | VERIFIED          | `is_failing` is true for any severity other than advise; `_verdict` returns EXIT_ISSUES only if `is_failing`. Tests pass.                             |
| 10  | CLAUDE/QA.md was updated to match                                                                                                                                                   | VERIFIED          | QA.md:801-808                                                                                                                                         |
| 11  | Advise findings never fail in the release gate or `qa.yml`                                                                                                                          | VERIFIED          | Both use `llm_qa.py` `plan_qa`/`docs_qa` (qa.yml:216-218), which run `run_corpus_qa.py` (llm_qa.py:806,811)                                           |
| 12  | release-gate.yml already carries `concurrency: {group: release-gate-<PR or ref>, cancel-in-progress: true}`                                                                         | VERIFIED          | release-gate.yml:26-28                                                                                                                                |
| 13  | That concurrency block comes from Plan 00476                                                                                                                                        | VERIFIED          | release-gate.yml:3 and :186 cite Plan 00476 as the origin of the workflow. The block itself is not individually attributed, which is acceptable.      |
| 14  | A test now asserts the concurrency block                                                                                                                                            | VERIFIED          | TestASupersededRunIsCancelled at test_release_gate_layout.py:107; passes                                                                              |
| 15  | The run_corpus_qa tests cover advise-only pass, block fail, unknown-severity fail                                                                                                   | VERIFIED          | test_run_corpus_qa.py passes (41 passed across the three files)                                                                                       |
| 16  | RELEASING.md has the "Hotfix fast path" section and the state-file `mode` field                                                                                                     | VERIFIED          | RELEASING.md:79-83 and :271                                                                                                                           |
| 17  | SKILL.md updated                                                                                                                                                                    | VERIFIED          | SKILL.md:4, 39, 51-52, 66                                                                                                                             |
| 18  | The release-notes holding-area file 013-hotfix-release-fast-path.md exists                                                                                                          | VERIFIED          | The file is tracked and its content is a callout citing Plan 00576                                                                                    |
| 19  | The invoke.sh hotfix tests exist (`tests/integration/test_release_skill_hotfix_mode.py`)                                                                                            | VERIFIED          | The file is tracked and passes                                                                                                                        |

## REFUTED

None.

## Drift check: RELEASING.md fast-path list vs invoke.sh output

The two agree on every step they share:

- 1a: `--accept`, report shown, state file `"mode": "hotfix"`.
- 1H and 1c skipped.
- Step 7 Opus review skipped, with a short changelog and release-notes entry.
- Step 6 unchanged.
- Step 10 limited to the hotfix range.
- Step 12 is 12.0 plus targeted tests.
- Kept gates: PR, Step 8c, Step 8b, freeze, Steps 9 and 11, Step 13, Steps 14-15.

Minor gaps, none contradictory:

1. RELEASING.md says Step 15.1 (post-release housekeeping) is skipped with 1H. invoke.sh does not mention this, and says only "publishing (Steps 14-15)" is kept. This is an omission in the prompt, so a model following only the printed prompt might run 15.1.
2. RELEASING.md says "X.Y.Z must be a patch bump of the last tag". invoke.sh only refuses the keywords `major`/`minor` and accepts any explicit X.Y.Z, so nothing enforces the "must be a patch bump" rule. This is not a plan claim, but the plan's "the bump is a patch" is only enforced for keywords.
3. The RELEASING.md table row for 1c says no `claude-code-versions.yaml` entry is required. invoke.sh does not say this. The row is consistent with the Step 7 checklist at RELEASING.md:725, which requires the entry.

Other note: the PLAN.md Success Criteria checkboxes are all unticked although Tasks 1.1-3.4 are ticked. This is a bookkeeping point, not a codebase claim.
