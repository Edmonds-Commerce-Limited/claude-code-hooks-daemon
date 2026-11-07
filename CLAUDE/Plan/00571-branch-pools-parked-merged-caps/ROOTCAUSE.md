# Branch hygiene dogfood: root causes of three suspected defects

Read-only investigation, 2026-11-07. Not plan work yet. No tracked file was edited, no ref changed, no full suite run.
One scratch reproduction repo was created at `untracked/scratch/bundle-repro/` (safe to delete).

---

## 1. `delete-branch` overwrites its recovery bundle: CONFIRMED DEFECT

### Root cause

- `src/claude_code_hooks_daemon/daemon/cli.py:12996-13001`: `--bundle` defaults to the fixed path
  `untracked/deleted-branches.bundle`.
- `src/claude_code_hooks_daemon/daemon/cli.py:6609`: `bundle_path = None if args.no_bundle else Path(args.bundle)`. The path is the same on every call.
- `src/claude_code_hooks_daemon/daemon/branch_safety.py:741-760` `write_recovery_bundle`: runs
  `git bundle create <bundle_path> refs/heads/<names of THIS batch>`. `git bundle create` replaces an existing file rather than appending to it.
- `src/claude_code_hooks_daemon/daemon/branch_safety.py:889-891`: the bundle holds only this call's `classifications`.
- `src/claude_code_hooks_daemon/daemon/cli.py:6761-6763`: prints `Recovery bundle: <path>` / `restore with: git fetch <path> <branch>:<branch>` every time. After the next call, that instruction is false for every earlier branch.

I reproduced the git behaviour (scratch repo, branches `a` and `b`): `git bundle create x.bundle refs/heads/a`, then `git bundle create x.bundle refs/heads/b`, then `git bundle list-heads x.bundle` shows only `refs/heads/b`.

There is a second way to lose it, made worse by the overwrite. `branch_safety.py:934-937` (`_discard_unused_bundle`, `:763-783`) **unlinks** the bundle when classification passed but git then refused every delete. With the fixed path, the old contents were already overwritten when the bundle was created. The unlink then deletes the only file at that path, so the run leaves nothing behind at all.

### Precedent in the same codebase

`branch-sweep --clean` does not have this problem. `core/branch_cleanup.py:574-592` writes
`untracked/branch-cleanup/branch-cleanup-<UTC %Y%m%dT%H%M%SZ>.bundle` (`_BUNDLE_STAMP`, `branch_cleanup.py:74`; dir `cli.py:6560`), one file per run, and prints a per-branch `git fetch <bundle> refs/heads/<n>:refs/heads/<n>` line. `delete-branch` is the odd one out.

### Same branch name deleted twice

- Today the second deletion overwrites the first, so the first tip is gone from the bundle (and from the file entirely).
- With a single accumulating bundle (rebuilt as old heads plus new heads), both entries would be named `refs/heads/<name>`. Either one tip silently replaces the other, or the bundle carries two heads with the same name, and `git fetch <bundle> <name>:<name>` then becomes ambiguous or fetches the wrong one. That is why one accumulating file is the wrong design.
- With one timestamped file per deletion, each file holds one `refs/heads/<name>` and the two tips never collide. The restore line names the exact file, so it stays true.

### Proposed fix

1. Change the default to a per-call file: `untracked/deleted-branches/<UTC stamp>-<pid or 4 random hex>.bundle`. The suffix is needed because `_BUNDLE_STAMP` only has 1-second resolution, and two calls in the same second would collide. The same weakness exists in `branch-sweep --clean` (unverified that it is ever hit). An explicit `--bundle PATH` stays as the caller asked: refuse if the file already exists, or document that it is overwritten.
2. Print the restore line per deleted branch with the exact file and full refs, as `branch_cleanup.py:590-592` does: `git fetch <file> refs/heads/<n>:refs/heads/<n>`. The current generic `<branch>:<branch>` form (`cli.py:6741`, `:6763`) uses a short name. Unverified: the tag/branch ambiguity of Plan 00254 may apply to it.
3. Optional: append one line per deleted branch (time, branch, tip sha, bundle file) to an index such as `untracked/deleted-branches/INDEX.jsonl`, so "where did branch X go" has one place to look. This works even when the same name was deleted twice.
4. `_discard_unused_bundle` then only ever removes this run's own file, which is correct.
5. Migration: leave the existing `untracked/deleted-branches.bundle` in place. It holds the last-deleted branch.

### Minimal reproduction for a test (`tests/unit/daemon/test_branch_safety.py` style, real repo)

```python
_merged_branch(repo, "one"); _merged_branch(repo, "two")
bundle = repo.parent / "deleted.bundle"          # what the CLI default does
delete_branches(repo, ["one"], bundle_path=bundle)
delete_branches(repo, ["two"], bundle_path=bundle)
heads = _git(repo, "bundle", "list-heads", str(bundle)).stdout
assert "refs/heads/one" in heads   # FAILS today: only refs/heads/two
```

At the CLI level, call `cmd_delete_branch` twice with the default `--bundle`. Then assert that the restore line printed by the first call still fetches `one`.

### Test coverage

Not covered. The bundle tests (`test_branch_safety.py:444-463`, `:491`, `:992-1033`, `:1448`) each do one deletion into a fresh `tmp_path` bundle. `test_cli_delete_branch.py:93-94` uses `no_bundle: True`. No test runs two deletions against the same path.

---

## 2. `worktree-reap --reap-branches` skipped `worktree-issue-174-screen-arch`: INTENDED BY DESIGN (naming/provenance scope), with a reporting gap

### Root cause: a naming or provenance requirement, not ordering

Orphan pruning only considers branches the daemon or agent dispatch created:

- `core/worktree_reaping.py:564-573` `is_daemon_created_branch`: `name.startswith("agent-") or is_worktree_create_name(name)`. The WorktreeCreate shape is `<slug>-<8 hex>` (`core/worktree_naming.py:78-87`).
- `core/worktree_reaping.py:614-630` `_prunable`: after the policy check, an `agent-*` name qualifies. Anything else qualifies only if its creator record `branch.<name>.hooksDaemonRoute == worktree_create` (`core/branch_records.py:36-40`, `:140-147`).
- `core/worktree_reaping.py:663`: `collect_orphaned_branches` keeps only names that pass both.

`worktree-issue-174-screen-arch` fails both tests. It starts with `worktree-` (`WORKTREE_BRANCH_PREFIX`, `utils/git_repo.py:79`, which is documented there as "a work branch made by hand or by the coordinator", CLAUDE/Worktree.md). It does not end in 8 hex, and a coordinator-made branch has no `worktree_create` route. So it never enters `orphans`, and `prune_branch` never sees it. It is not printed even as `ORPHAN`, and the "N branch(es) have no worktree" hint (`cli.py:9637-9641`) does not count it.

Ordering is not the cause. `orphans` is computed at `cli.py:9579-9587`, before the reap loop at `:9600`, but that does not matter here: the branch had no worktree before the run either. `integration-174` was deleted for a different reason. `reap_worktree` (`worktree_reaping.py:450-561`) deletes whatever branch is checked out in a reaped worktree with `git branch -d`, whatever its name. The two paths therefore treat names differently: an attached branch with any name is deleted, but an unattached branch must have a daemon-shaped name.

### Evidence that it is intended

- The `is_daemon_created_branch` docstring (`worktree_reaping.py:565-572`): "Scoped on purpose: Plans 00349 and 00048 declined a general branch-pruning policy, so only names the daemon or agent dispatch generate are eligible."
- Plan 00558 `DESIGN.md:301` widens the scope from `agent-*` only to `worktree_create`-recorded branches, and no further.
- `cli.py:12629`, the `--reap-branches` help text: "Also delete **agent** branches that have no worktree".
- The test `tests/unit/core/test_orphaned_branches.py:250-258` (`test_a_worktree_create_name_is_an_orphan_and_a_hand_name_is_not`) asserts that the hand-made name `feature-x` is excluded. `:276-278` asserts that hex-shaped ordinary names are excluded.
- The tool that is meant to handle such branches is `branch-sweep --clean` (`cli.py:6563-6588` → `branch_cleanup.clean_sweep`). It deletes every merged or patch-equivalent local branch behind a timestamped bundle. The branch-sweep summary does point there (`core/branch_sweep.py:450-454`).

### Verdict

The skip itself is intended, not a defect. The defects are in how it is presented:

- `worktree-reap` is silent about merged unattached branches it chose not to touch. A user who runs `--reap-branches` reasonably expects every merged branch with no worktree to go.
- The `OrphanedBranch` docstring (`worktree_reaping.py:586`, "An `agent-*` branch") and the help text are stale since 00558 widened the scope to `worktree_create`.
- `CLAUDE/development/IssueSdlc.md:458` tells the loop to run `worktree-reap` after merge. It does not say that a coordinator `worktree-*` branch whose worktree carried an `integration-*` branch is left for `branch-sweep --clean` or `delete-branch`.

### Proposed fix (UX, not a scope change)

1. In `cmd_worktree_reap`, when `--reap-branches` is given, also list merged local branches that have no worktree and are out of scope ("not daemon-created; delete with `delete-branch <name>` or `branch-sweep --clean`"). Alternatively, print one line pointing at `branch-sweep --clean` whenever the branch-sweep inventory has merged branches.
2. Fix the help text and docstring to say "agent-\* or WorktreeCreate-recorded branches".
3. Possible change to discuss, not recommended without an owner ruling because it reverses Plans 00349/00048: add `worktree-*` (WORK_BRANCH_PREFIXES) to orphan-pruning eligibility. Every delete there is a `git branch -d` of a merged branch, so the risk is low.

### Minimal reproduction for a test

Build a repo with `main` and a branch `worktree-foo` merged into main, no worktree, no creator record. `collect_orphaned_branches(repo, "main", config=BranchesConfig()) == ()` passes today, which is the intended behaviour. The UX test would assert that `cmd_worktree_reap(--reap-branches)` output mentions `worktree-foo` and names the tool that deletes it. That assertion fails today.

### Test coverage

The scope is covered and asserted as intended (above). Nothing tests that out-of-scope merged branches are reported.

---

## 3. `work-queue done` suggests the issue it just delivered: CONFIRMED DEFECT

### Root cause

- `daemon/work_queue_cli.py:146-150` `_cmd_done` closes the record, then prints `_next_issue_line(args)`.
- `daemon/work_queue_cli.py:126-143` `_next_issue_line` calls `refresh_workable_cache` (`:138`), then returns `f"next workable issue: #{numbers[0]} - start it now"` (`:143`).
- `utils/workable_issues.py:166-172` `refresh_workable_cache` runs `service.check_open_issues` (one `gh issue list --state open`) and keeps `workable_numbers(reports)`.
- `utils/workable_issues.py:60-66` `workable_numbers` is where the filter falls short. It keeps every open issue that is `Verdict.VALID` (author whitelist only) and not labelled `agent-needs-human`. It has no notion of `agent-working`. The string `agent-working` does not appear anywhere in `src/` (it exists only in the runbook `CLAUDE/development/IssueSdlc.md:121`). It also has no notion of "the issue this queue entry belonged to".
- `utils/work_queue.py:75-86` `WorkRecord` stores name, worktree, branch, brief, sha and status, but **no issue number**. `done` therefore cannot exclude its own issue, except by parsing `issue-174-...` out of the name or branch.
- `CLAUDE/development/IssueSdlc.md:458-460` puts `work-queue done` at Step 7, straight after merge. Step 8 then waits for CI, closes the issue and removes `agent-working` (`:463-485`). At `done` time the delivered issue is therefore always still open and labelled `agent-working`, so it is always suggested whenever it ranks first.

### Two further problems in the same path

- **Order is newest first.** `check_open_issues` (`utils/github_issue_validity.py:484-519`) keeps `gh issue list` order, which defaults to newest created first. The live cache `untracked/workable-issues.json` currently reads `{"numbers": [174, 173, 172, ..., 163]}`, which is descending. `numbers[0]` is therefore the newest issue. The runbook's selection rules (`IssueSdlc.md:132-140`) are "oldest first" after "recover stalled". That is why #174, the newest, was picked. Taking the head of this list is not the runbook's selection rule.
- **The Stop gate inherits it.** `handlers/stop/idle_workable_issue_stop_gate.py:180` reads the same cache, and `:240-243` denies an idle stop with "Issue #{numbers[0]} is workable and nothing is in flight". Right after `done`, the queue has no running entry, so a session correctly waiting on CI for #174 is told to start #174. Unverified live, but it follows directly from the code.

### Proposed fix

1. `workable_numbers`: exclude `agent-working` as well as `agent-needs-human`. Add an `IN_FLIGHT_LABEL = "agent-working"` constant next to `NEEDS_HUMAN_LABEL`. Stalled-issue recovery (runbook rule 1, start comment older than 2 h) stays the issue-sdlc tick's job, because the tick reads gh directly. This cache cannot see comment age, and it should not push a session into an issue another tick may own.
2. Give `WorkRecord` an optional `issue: int | None`, set by `work-queue add --issue N` (and later inferable from a branch matching `issue-(\d+)`). `done` then excludes that number from the suggestion and calls `remove_workable(cache, N)` (`workable_issues.py:140-157`, already used by `--park` at `issue_validity_cli.py:197`). This is defence in depth for the window before the label is removed.
3. Sort the workable numbers ascending, or follow the runbook's precedence, before taking `[0]`, in both `_next_issue_line` and the Stop gate. Ideally make it one shared function so the two cannot drift apart.
4. Optional: make the `done` line say "after #N closes", or skip the suggestion while the closed record's issue is still open.

### Minimal reproduction for a test (`tests/unit/utils/test_workable_issues.py`)

```python
service = _service([_issue(174, labels=["agent-working"]), _issue(170, labels=["agent-triaged"])])
reports = service.check_open_issues([AuthorWhitelistCheck(APPROVED)])
assert workable_numbers(reports) == [170]       # FAILS today: [174, 170]
```

At the CLI level (`tests/unit/daemon/test_work_queue_cli.py`, which has an `_issue(number, *labels)` helper at `:49`): list `#174 agent-working` and `#170`, run `done issue-174-x`, and assert the output does not contain `#174`. An order test lists `#174`, `#170` (newest first, as gh returns them), both workable, and asserts that the suggestion is `#170`.

### Test coverage

Not covered. `test_workable_issues.py:54-67` tests only `agent-needs-human` and the author rule. `test_work_queue_cli.py:245-254` asserts that the first listed issue is named. No test covers `agent-working`, the record's own issue, or ordering.

---

## Other things that look wrong (UNVERIFIED unless stated)

- **UNVERIFIED: `reap_worktree` skips the branch policy check.** It deletes any branch attached to a reaped worktree (`worktree_reaping.py:539`) without `policy_refusal` (protected names, integration lines, exempt globs), which orphan pruning does apply (`:623`). `git branch -d` still refuses an unmerged branch. But a merged integration line or exempt branch checked out in an agent worktree would be deleted. `integration-174` went this way today. Whether that was wanted depends on whether `integration-*` is meant to be a configured integration line. In this repo's `branches:` config (`.claude/hooks-daemon.yaml:1568`) it is not.
- **Ordering latent gap.** `orphans` is collected before the reap loop (`cli.py:9579` vs `:9600`). Suppose a worktree is removed in this run but git keeps its branch (`reap_worktree` "git kept the branch" path, `:540-549`). That branch is now orphaned but is not offered for `--reap-branches` until the next run. This was not the cause today.
- **Bundle stamp resolution.** `branch-sweep --clean` names bundles to the second (`branch_cleanup.py:74`). Two runs in the same second would overwrite each other, the same defect class as item 1. Unverified that it occurs in practice.
- **Restore-line inconsistency.** `delete-branch` prints `git fetch <bundle> <branch>:<branch>` (`cli.py:6741`, `:6763`). `branch-sweep --clean` prints full `refs/heads/...` refspecs (`branch_cleanup.py:591`). Unverified whether the short form misbehaves when a tag shares the branch name (the Plan 00254 class).
- **Stale doc.** `OrphanedBranch` docstring (`worktree_reaping.py:586`) and `--reap-branches` help (`cli.py:12629`) still say agent branches only (see item 2).
