# Plan 00558 Phase 2 review: Tasks 2.0 and 2.1 (branch `worktree-558-inventory`)

Scope: `git diff main...worktree-558-inventory` (commits 2544db8d2, 6ee91c83b, 81c09cd73). Paths below are in the worktree `/workspace/untracked/worktrees/worktree-558-inventory`. Line numbers are on the branch tip.

Probe evidence (keep it with the plan when these become tasks): `untracked/scratch/558-review/probe.bash` builds the repo `untracked/scratch/558-review/repo/clone`, and `untracked/scratch/558-review/run_inventory.py <repo>` prints the verdicts. Run it with the worktree venv and `PYTHONPATH=src`. Findings 1, 2 and 3 were reproduced on it. The others come from reading the code.

## Blocking (fix before Phase 3 consumes these verdicts)

### 1. HIGH: one record per name is classified by the LOCAL tip only, so a remote copy with unique commits is reported as merged

- Location: `src/claude_code_hooks_daemon/core/branch_inventory.py:610` (`chosen = local or remote_row`), and `_classify` at `:655` and `:667`, which test only `chosen.refname` and `chosen.sha`.
- Failure scenario: local `divergent` is merged into `main`. `origin/divergent` has one more commit that was pushed from another clone, or left behind when the local branch was reset. The record's `state` is `merged` and `merged_into` is `main`, even though `remote_tip != local_tip` and the remote tip is not in `main`. Probe output: `divergent state='merged' local=1a84c6af remote=a041dc98 merged_into=main ahead=0`. Section 7 cleanup and `branch-sweep --clean` act on "merged". If either deletes the remote copy on this verdict, `unique remote-only work` is lost.
- Related point at the same lines: `merged_default` is the union of `--merged=refs/remotes/<remote>/<default>` and `--merged=refs/heads/<default>` (`:597-601`). `merged_into` records only the name `main`, not which ref proved it. A branch merged into an UNPUSHED local `main` therefore looks the same as one merged into `origin/main`. A later remote delete of that branch leaves its commits only in a local, unpushed `main`.
- Remediation:
  - Classify each existing tip, local and remote. A record is merged, patch-equivalent or same-tip only when EVERY copy is. Otherwise, use the weaker state, or add a `DIVERGED` state that is never a cleanup candidate.
  - Record the proving ref in `merged_into` (e.g. `origin/main` vs `main`) so that remote deletes can require a remote-default proof.
  - Add a fixture branch whose local copy is merged and whose remote copy is one commit ahead, and assert that it is not merged.

### 2. HIGH: "patch-equivalent" ignores content that exists only in a merge commit

- Location: `branch_inventory.py:683-687`, with `branch_safety.cherry_unique_shas` (`daemon/branch_safety.py:426`). `git cherry` never lists merge commits.
- Failure scenario: branch `evil` holds `y1` and a merge commit that adds `evil.txt`, either as a conflict resolution or as an "evil merge". `y1` is cherry-picked into `main`. `git cherry` prints only `- y1`, so the record is `patch-equivalent` with `merged_into=main`. But `git diff origin/main...evil` still shows `evil.txt | 1 +`, which is not in `main`. Probe output: `evil state='patch-equivalent' ... ahead=2`. DESIGN section 2 calls states 3-5 "done, not deleted". Section 3 lists them first as the cheapest to delete, so the evil-merge content is one `delete-branch` away from loss. Conflict resolutions in merge commits are routine on long-lived agent branches.
- `classify_branch`'s patch-equivalent tier has the same blind spot. It is also fail-open on a cherry failure: author note 2, `_unique_commit_count` returns 0.
- Remediation:
  - Confirm patch-equivalence by merging. `git merge-tree --write-tree <target> <tip>` must yield exactly `<target>^{tree}`, and if the trees differ the branch is not equivalent. As a cheaper partial alternative, refuse equivalence when the range `target..tip` contains any merge commit whose tree differs from what its parents' merge produces.
  - Add a fixture with an evil merge and assert `LIVE`.

### 3. HIGH: a branch whose tip commit has a folded (multi-line) trailer value disappears from the inventory

- Location: `branch_inventory.py:221-224`. Records are split on `"\n"`, and any row without exactly 7 fields is dropped with `continue`.
- Failure scenario: the tip message carries `Parked-Reason: waiting on\n the owner to decide`. That is a valid folded trailer, and `branch-park --reason` with a long or multi-line reason will produce one. `%(trailers:...valueonly)` keeps the newline because the format has no `unfold`. Probe `od -c` shows `waiting on\n the owner`. The row splits in two, both halves fail the length check, and the branch is silently absent from `records` (probe: `multiline present: False`).
- An absent branch is uncounted by the WIP cap, invisible to the duplicate and stop guards, and missing from the "LOST WORK RISK / contained nowhere" listing. That listing is the one place an unpushed branch is supposed to be loud. Any newline in any field causes the same loss.
- `test_old_git_without_ahead_behind_leaves_behind_unknown` (`tests/unit/core/test_branch_inventory.py:443`) feeds a "malformed line" and only asserts that the rest still parse, so the silent drop is pinned as intended behaviour.
- Remediation:
  - Add `unfold` to the trailers atom.
  - Delimit RECORDS with a character that cannot appear in a field, e.g. end the format with `%00%00` or `%1e` and split on that, not on `"\n"`.
  - Make an unparseable row an error (raise `BranchInventoryError`, or emit an `UNCLASSIFIED` record keyed by the refname, which is always the first field). Never drop it.
  - Test with a folded `Parked-Reason`.

### 4. HIGH: twin branches each report the other as their containment, so both are "cleanup candidates"

- Location: `branch_inventory.py:384-391` (`containment_of`: `others = [ref for ref in refs if ref != own]`).
- Failure scenario: `a` and `b` are dormant, both pushed, and share a tip (or `b` was pushed as a backup of `a`). Containment of `a` is `REMOTE_REF origin/b`, and containment of `b` is `REMOTE_REF origin/a`. DESIGN section 4 reports "in another remote ref" as "cleanup candidate". A sweep that deletes candidates removes both remote refs and the work with them. The same cycle happens with any set of refs that contain each other only through work branches that are themselves candidates.
- The fixture covers only the one-sided case. `dormant-other-ref` is checked, but `backup-copy`'s own containment is never asserted (`tests/unit/core/test_branch_inventory.py:321`).
- Remediation:
  - Count a containing ref as "another remote ref" only when it is the default, an integration line, or a ref whose tip is NOT equal to this tip and that is not itself dormant or a candidate.
  - Alternatively, compute containment after same-tip grouping and mark exactly one member of each group `OWN_REMOTE`.
  - Assert both sides of a twin pair.

### 5. MEDIUM-HIGH: a failed `git worktree list` reports every branch as having no worktree

- Location: `branch_inventory.py:262-266`. On failure it returns `{}`. `test_worktree_listing_failure_means_no_paths` (`tests/unit/core/test_branch_inventory.py:452`) asserts this as correct.
- Failure scenario: `worktree list` times out under load, which `Timeout.GIT_CONTEXT` makes possible on a busy host. Every record then has `worktree=None`, which cannot be told apart from "not checked out anywhere". The guards in sections 3, 6, 8 and 13 and `worktree-reap` key on the worktree path. Local `git branch -d` still refuses a checked-out branch, but the remote delete, the evacuation check and the "dirty worktree" checks do not get that backstop.
- Remediation:
  - Raise `BranchInventoryError`, or return a sentinel (e.g. `BranchInventory.worktrees_known=False`) that consumers must check before acting.
  - Change the test to assert the fail-closed signal.

## Important

### 6. MEDIUM: the inventory ignores `protected_names`, and an unresolved or misnamed default turns the default branch into a work branch

- Location: `branch_inventory.py:649-654` (only `exempt`, `== default` and `integration_lines` are non-work), and `:588`.
- Failure scenario: `branches.default: origin/main` (a plausible user value that the model does not reject: `config/models.py`, `default` has only `min_length` and blank checks). Another case is `auto` in a clone with no `origin/HEAD` and no local `main` or `master`, e.g. a repository whose default is `trunk`.
  - `main` or `trunk` is then classified as a work branch: `LIVE`, or `DORMANT` once it is old enough. It is counted against the WIP cap, and a quiet `trunk` older than 30 days reaches `DormancyStage.BLOCK`. Section 4 says that denies every creation route.
  - `test_a_named_default_that_does_not_exist_merges_nothing` (`tests/unit/core/test_branch_inventory.py:467`) asserts `main != DEFAULT` and nothing more.
- Remediation:
  - Treat any name in `protected_names` as non-work in `_classify`, in the same tier as DEFAULT.
  - When `default` is set but `_default_ref` finds no ref, put that fact on `BranchInventory` (e.g. `default_ref=None`) so the sweep reports a config problem instead of classifying.
  - Optionally reject `default` values that start with `refs/` or `<remote>/` in the model.

### 7. MEDIUM: `delete-branch` still deletes exempt and integration-line branches

- Location: `src/claude_code_hooks_daemon/daemon/cli.py:6518-6519`. `protected_names = (*branches.protected_names, protected_ref)`.
- Failure scenario: DESIGN section 1 (migration table, `DEFAULT_PROTECTED_NAMES` row) says "the default branch, every integration-line match and every exempt match are added at runtime". Only the default is added here. With `exempt: ["users/*"]`, `hooks-daemon delete-branch users/alice/x` deletes the branch once it is merged, although the config says exempt branches are "never deleted by an agent". `release/*` lines behave the same way.
  - `classify_branch` matches `name in protected_names` exactly (`daemon/branch_safety.py:550`), so globs cannot simply be appended.
- Remediation:
  - Pass the `integration_lines` and `exempt` globs through and match them with the same `fnmatchcase` the inventory uses. A shared helper avoids a second definition.
  - Add a CLI test with an exempt glob that is refused.

### 8. MEDIUM: `resolve_default_branch("auto")` is weaker than the old literal `main` in clones without `origin/HEAD`, so `delete-branch` and `worktree-reap` exit 2 where they used to work

- Location: `src/claude_code_hooks_daemon/utils/git_sync.py:402-415` (delegates to `default_branch`, `:376-399`), and the call sites `cli.py:6510` and `:9418`.
- Failure scenario: a repository made by `git init` + `git remote add origin` + `git fetch` (no `origin/HEAD`), or a worktree-only setup with no local `main`. Before this change, `--protected-ref main` was a bare name that `_protected_base_ref` (`daemon/branch_safety.py:502-527`) let git resolve to `origin/main`, and the command worked. Now `default_branch` probes only `origin/HEAD`, `refs/heads/main` and `refs/heads/master`, returns None, and both verbs exit 2. `housekeeping`'s `worktree-reap` step (`daemon/housekeeping.py:116`) then reports a failure on those clones.
- `default_branch` also hard-codes `origin`, so `branches.remote: upstream` with `default: auto` reads the wrong remote's HEAD.
- Remediation:
  - In `resolve_default_branch`, after `default_branch`, also probe `refs/remotes/<config.remote>/main` and `refs/remotes/<config.remote>/master`.
  - Pass `config.remote` instead of assuming `origin`.
  - Test a clone with `origin/main` and no `origin/HEAD` and no local `main`.

## Lower

### 9. LOW: `branch_count_advisor` still measures "behind" against `git_sync.default_branch`, not `resolve_default_branch`

- Location: `src/claude_code_hooks_daemon/handlers/session_start/branch_count_advisor.py:135`.
- Failure scenario: with `branches.default: develop`, the advisor reports branches as behind `main`, while the CLI and the inventory use `develop`. DESIGN section 1: "Every caller moves to the new function." `self._branches` is already injected.
- Remediation: call `git_sync.resolve_default_branch(self._branches, root)`, and add a test.

### 10. LOW: a cache entry computed for an integration-line target is reused for the default target with `lines=None`

- Location: `branch_inventory.py:516-530`. The key is `tip:target.sha`, but `want_lines` depends on `target.is_default`.
- Failure scenario: an integration line and the default point at the same commit, e.g. `release/x` was just cut from `main`. The entry is cached with `lines=None` and then read for the default target, so `record.lines` is None on a fully classified branch.
- Remediation: put `is_default` (or `want_lines`) in the key, or always compute `lines`.

### 11. LOW: an unparseable committer date becomes epoch 0, so the branch looks about 20,000 days dormant (stage BLOCK)

- Location: `branch_inventory.py:234` (`int(date) if date.isdigit() else 0`).
- Failure scenario: any parse slip, such as a field shift from finding 3, turns into the strongest dormancy verdict, which denies creation routes. It does not land on "unknown".
- Remediation: treat the row as unparseable (finding 3's path), or make `committed_at` optional with no stage.

## Tests that assert too little (all in `tests/unit/core/test_branch_inventory.py`)

- `:452` `test_worktree_listing_failure_means_no_paths` pins the fail-open behaviour of finding 5.
- `:430` the "malformed line" case pins the silent drop of finding 3.
- `:467` asserts only `!= DEFAULT` for the misnamed-default case (finding 6). It should assert what `main` IS.
- `:363` `test_cache_is_written` asserts only that `pairs` is non-empty.
- Missing cases: a divergent local and remote copy (finding 1), an evil merge (finding 2), a folded trailer (finding 3), the second side of a twin's containment (finding 4), and a protected name that is not the default (finding 6).

## Checked and not a defect

- Config validation errors make `delete-branch` and `worktree-reap` exit 1. That is not new: the CLI validates the config before dispatch on `main` too (`cli.py` install check, "Invalid configuration in ..."). The new `_branches_config` adds no new failure mode.
- `_merged_refs` failing returns an empty set, and step 5 then decides. The test at `:408` covers this.
- The target ref is dropped from the `--merged` listing. The other copy of the default or line (local vs remote) can appear in the listing, but it is classified DEFAULT or INTEGRATION_LINE first, so this is harmless.
- `for-each-ref` root `refs/remotes/<remote>` matches only up to a slash, so `origin-fork/*` does not leak in.
- The park-commit rule requires the same tree as the parent plus a trailer, so it can only discount commits with no content.
- Dormancy presets validate the effective values. Inversions under either preset, `noisy == block`, and stages below 1 are rejected and tested.
- Budget exhaustion and a cherry failure both give `UNCLASSIFIED` with `ahead=None`. Tested.
