# Plan 00558 Phase 2: Tasks 2.0 and 2.1 (config block and branch inventory)

Worktree `worktree-558-inventory`. Brief: `untracked/scratch/brief-558-inventory.md`. Paths below are relative to `src/claude_code_hooks_daemon/` unless they start with `tests/`, `CLAUDE/` or `scripts/`.

## Task 2.0: the `branches:` block

- `config/models.py`: `BranchesConfig` and its sub-models (`BranchWipConfig`, `BranchDuplicatesConfig`, `BranchDormancyConfig`, `BranchStopGuardConfig`, `BranchForceRemovalConfig`, `BranchEvacuationConfig`, `BranchCleanupAfterMergeConfig`, `BranchSweepConfig`), all `extra="forbid"`, every DESIGN.md section 1 key at its stated default. `Config.branches` sits beside `worktree:`.
  - `BRANCH_DORMANCY_PRESETS` holds standard 7/14/30 and strict 3/3/7. `BranchDormancyConfig.effective_days` applies the preset, and a validator rejects effective values that break `advisory_days <= noisy_days < block_days`. Each stage must be at least 1 (`ge=1`). An inverted override fails `Config.load`.
  - `sweep.budget_ms` allows 0 (`ge=0`), because a zero budget is a real setting: classify only what the bulk steps prove.
  - `explicit_wip_cap()` and `explicit_behind_threshold()` return the value only when the config SETS the key (`model_fields_set`). They are the "unset" test the advisor fallback needs.
- `utils/git_sync.py`: `resolve_default_branch(config: BranchesConfig, repo) -> str | None`. A named branch is returned as written. `auto` calls `default_branch(repo)`.
- `daemon/cli.py`:
  - `delete-branch --protected-ref` and `worktree-reap --base-branch` now default to `None`. `None` resolves through `resolve_default_branch` using the project's `branches:` block (`_branches_config`). An explicit flag still wins.
  - If nothing resolves, the command exits 2 and names the flag. Before this change it silently used `main`.
  - `delete-branch` passes `protected_names` = the configured names plus the resolved default.
- `daemon/branch_safety.py`: `DEFAULT_PROTECTED_NAMES = tuple(BranchesConfig().protected_names)`. The model default is now the single source.
- `branch_count_advisor`: reads `branches.wip.cap` and `branches.sweep.behind_threshold` when they are set, and otherwise falls back to its own options. Its own defaults (3 and 50) are unchanged, so a project without a `branches:` block sees no change. No deprecation line was added.
  - The block is injected as `_branches` by `HandlerRegistry.register_all(branches=...)`, using the same declared-attribute selection as `_reference_repos`. It is plumbed through `daemon/controller.py` and `cli.py` (`branches=config.branches`).
- Manifest `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml`:
  - `added`: `integration_lines` and `exempt` (`recommended: true`), `dormancy.preset` (not recommended), and the other `branches.*` keys at sub-block level.
  - `renamed`: the two `branch_count_advisor` options.
  - No `changed` entry and no post-upgrade task: those belong to Task 2.3 and later.
- `daemon/init_config.py`: the full template ends with the `branches:` block at the model defaults. A test loads it and compares it to `BranchesConfig()`.
- `.claude/hooks-daemon.yaml` is untouched, as instructed.

## Task 2.1: `core/branch_inventory.py`

`build_inventory(repo, config, *, now=None) -> BranchInventory(default_branch, records)` returns one `BranchRecord` per branch name. A local branch and its remote copy are one record.

Each record carries: state, local and remote tip, upstream, worktree, ahead, behind, lines, committer date and age, park reason, plan, issue, merged_into, same_tip_as, dormancy_stage, containment and contained_in.

`BranchState` follows DESIGN.md section 2 and adds `UNCLASSIFIED` ("not yet classified").

Git commands (all through `utils/git_repo.run_git`, each with `Timeout.GIT_CONTEXT`):

1. One `for-each-ref` over `refs/heads` and `refs/remotes/<remote>`. The format carries `%(ahead-behind:<default-ref>)`, `%(trailers:key=Parked-Reason,valueonly,separator=%x1f)` and `%(contents:subject)`.

   - If that call fails while the atom is in the format (git older than 2.41), it is retried without the atom, and `behind` is None.
   - If the plain listing also fails, it raises `BranchInventoryError`.

2. `worktree list --porcelain`. If it fails, no record gets a worktree path.

3. `for-each-ref --merged=<target>` for each default ref (remote and local) and for each integration-line ref. The target itself is dropped from the result. If this call fails, it proves nothing: the per-branch step then decides.

4. Same-tip grouping in Python, among work branches only. Exempt branches, the default and integration lines are not grouped.

5. For each bulk-unmerged branch and each target, ahead, unique patches and lines are cached by `(tip sha, target sha)` in `untracked/branch-inventory/cache.json`. This step:

   - runs a `log --boundary` walk to find park commits;
   - runs `branch_safety.cherry_unique_shas`, a new public function that returns None when git fails (fail closed);
   - runs `diff --shortstat target...tip`, against the default target only.

   This step is cut off at `sweep.budget_ms`. A branch it does not reach is `UNCLASSIFIED`, with `ahead` set to None. Any git failure also makes the branch `UNCLASSIFIED`, never merged.

   The cache is written atomically and pruned to tips that still exist. A corrupt cache is logged and rebuilt.

- Park commits (DESIGN.md section 5 rule):
  - A park commit is a commit in the range whose tree equals its parent's tree and that carries a `Parked-Reason`, `Parked-By` or `Unparked` trailer.
  - It is not counted in `ahead` and is subtracted from cherry's unique set.
  - A range made only of park commits is `MERGED_DEFAULT` or `MERGED_LINE`, not patch-equivalent.
  - `lines` is a tree diff, so empty commits never reach it.
- Dormancy: the stage comes from `effective_days`. `mode: warn` caps it at noisy, and `mode: off` gives no dormant state.
- Containment (`containment_of`, public): in the default (by ancestry), in another remote ref, on its own remote only, or nowhere. It runs only for dormant branches and is cached by `(tip, sha256 of the remote refs, name)` inside the budget.
- Links:
  - From the branch name: `issue-N` or `gh-N` gives an issue. The first other 2-5 digit token gives a plan, zero-padded to 5 digits.
  - From the tip subject, only where the name gave nothing: `Addresses #N` gives an issue and `Plan NNNNN` gives a plan.
- Integration-line and exempt globs use `fnmatchcase`, so `*` spans `/`.

Tests: `tests/unit/core/test_branch_inventory.py`, 70 tests. Module coverage is 98.58%.

- The fixture is a bare remote plus a clone with: exempt, default and integration line; merged into default; merged only into `release/x`; cherry-picked; twins; parked; parked-then-merged; dormant at each standard stage with nowhere, own-remote and other-ref containment; live with a worktree; and two link cases.
- Budget 0 leaves unmerged branches unclassified. A second pass with `cherry_unique_shas` stubbed to raise gives identical states, and budget 0 still classifies from the cache. A cherry failure is unclassified, and a `--merged` failure still classifies correctly through step 5.

## Red-run evidence

- 2.0: `untracked/scratch/red-2.0.txt` shows 4 collection errors (`BranchesConfig` did not exist). Green: 231 passed across the touched suites, then 9/9 for the CLI defaults file.
- 2.1: `untracked/scratch/red-2.1.txt` shows an ImportError (`core.branch_inventory` did not exist). The first green run had 4 failures, all on park commits. The cause was a real bug (below). After the fix: 53 passed, then 70 passed with the edge-case tests.

## Findings and deviations from DESIGN.md

1. **`str.splitlines()` splits on `\x1c`, `\x1d` and `\x1e`.** It looks like a newline-only splitter but is not. A `%x1d` trailer-value separator broke the log parse. The module splits on `"\n"` only (`_lines_of`). Any later parser of git output that uses control-character separators needs the same care.
2. **The fail-open in `branch_safety._unique_commit_count`, left unchanged.** It returns 0 when `git cherry` fails, so `classify_branch` reports `patch-equivalent` on a git failure. That proof tier gates a deletion. I left it alone because the brief says `classify_branch` behaviour must not change for existing callers. Task 3.1, which reworks `classify_branch`, should switch it to `cherry_unique_shas`.
3. **"In the default branch" containment can never show for a dormant branch.** States 3-5 classify such a branch as merged or patch-equivalent first. `containment_of` implements the ancestry arm and is tested directly. The cherry arm is not repeated there.
4. **Park commits are excluded from ahead by a per-branch `log --boundary` walk, not by `%(ahead-behind:)`.** The atom counts every commit, park commits included. As a result `ahead` is only known for branches the step-5 pass reached. It is None for unclassified branches and for branches merged only into a line.
5. **Plan links are not resolved with `find-plan`.** The record carries the number only (`"00558"`). Resolving it to a path is left to the CLI and sweep tasks, which need the path.
6. **On git before 2.41, `behind` is None.** DESIGN.md's per-branch `rev-list` fallback for that case is not built (YAGNI on this host's 2.47.3).
7. **`delete-branch` and `worktree-reap` now exit 2 when the default cannot be resolved,** rather than assuming `main`.

## QA

`FULL_QA_LOCK_WAIT_SECONDS=5400 ./scripts/qa/llm_qa.py changed` was run twice.

- First run: `QA: 39/42 PASSED, 2/42 FAILED, 1/42 NOT MEANINGFUL`. There were three mypy errors in `core/branch_inventory.py`: a local variable reused the name of a set-typed loop variable. These were fixed in a follow-up commit, which also stopped the tests importing `run_git` through the module.
- Second run: `QA: 41/42 PASSED, 1/42 FAILED`. The one failure is `changed_tests`: 3522 passed, 0 failed, 5 skipped. Its only finding is the accepted "too-broad" unmapped notice for the hub files `config/models.py`, `daemon/branch_safety.py`, `daemon/cli.py`, `daemon/controller.py`, `daemon/init_config.py`, `handlers/registry.py` and `utils/git_sync.py`.
- The new modules map by name, so no `changed_tests_map.yaml` rule was needed.
- The brief's journal category `progress` is not valid for `mkplan.bash --journal`, so the entry was written as `action`.

## Review fixes (findings of `261103-phase2-review.md`)

Every finding was fixed test-first: a RED run showed 10 failures plus a collection error, before any source change. The review probe (`untracked/scratch/558-review/probe.bash`) now prints `divergent` and `evil` as `live` and `multiline` as `parked`, and the multiline branch is present.

01. **Both tips.** Each distinct tip of a name gets its own verdict (`_tip_verdict`). A name is merged, merged-into-line or patch-equivalent only when every copy is. When all copies are done, the weakest proof wins (`_weakest`), and a proof from a local ref ranks weaker than one from a remote ref. A new `BranchRecord.proven_by` names the proving ref: `origin/main` for the remote default, or `main` when the merge is only into the unpushed local default. When a copy is not done, it supplies the record's age, the park marker, ahead and lines, and the containment.
02. **Merge commits.** The step-5 log walk counts merge commits in `target..tip`. When there are any, the record is not patch-equivalent. The cache entry carries `merges`, and the cache version is 2. **`classify_branch` has the same gap**, because its cherry tier never sees merge commits. That gap is fixed in Task 3.1, together with the `_unique_commit_count` fail-open (finding 2 above).
03. **Folded trailers.** Both trailer atoms now use `unfold`. The listing is tokenised on NUL, and git refuses a NUL in a commit message. It is read as whole records of seven fields each, so a newline inside a value cannot split a record. A row with an unreadable sha or date becomes `UNCLASSIFIED` with a `reason`. A listing that does not align to records raises `BranchInventoryError`.
04. **Containment.** The only refs that vouch (`REMOTE_REF`) are a tag, the default, an integration line, an exempt branch or a protected branch. A tip held only by other work branches is reported as the new `Containment.OTHER_WORK_BRANCH`, or as `OWN_REMOTE` when its own remote copy holds it. Neither is a cleanup candidate. Tags are now listed alongside the remote refs. The containment cache key hashes the remote refs and the tags, so a deleted tag invalidates every verdict that cited it.
05. **Worktrees.** When `worktree list` fails, `BranchInventory.worktrees_known` and `BranchRecord.worktree_known` are both False.
06. **Never-work names.** Matches of `protected_names` get the new state `PROTECTED`, which is never counted and never grouped. `BranchInventory.default_ref` is None when the default resolves to no ref.
07. **`delete-branch`** passes the protected names, the integration-line globs, the exempt globs and the default. `classify_branch` matches them through `branch_safety.matches_any_glob`, which the inventory also uses. A literal name is still an exact match.
08. **`auto` resolution.** It reads `<branches.remote>/HEAD` (through the new `remote=` parameter on `default_branch`), then the local `main` or `master`, then `refs/remotes/<remote>/main` or `master`.
09. **`branch_count_advisor`** uses `resolve_default_branch`.
10. **Cache key** is `tip:target:lines|nolines`.
11. **Date**: see 3. An unreadable date is never read as epoch 0.
12. **Tests strengthened.** These tests were rewritten: the malformed-row test, the worktree-failure test (now fail-closed), the misnamed-default test (now asserts `PROTECTED` and `default_ref is None`), and the cache test (now asserts the exact entry). The fixture gains a divergent branch, an evil merge, a folded trailer, a protected `develop`, a tag, a twin pair and a merge into the local main only. Both sides of the backup pair are asserted.
