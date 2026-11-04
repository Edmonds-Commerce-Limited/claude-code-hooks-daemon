# Handoff: Plan 00558 Task 3.1 steps 2 and 3 and wrap-up (second agent)

Brief: `/workspace/untracked/scratch/brief-558-cleanup-2.md` (and the original
`brief-558-cleanup.md`). Worktree `/workspace/untracked/worktrees/worktree-558-cleanup`,
branch `worktree-558-cleanup`, head was 0e5c99d61 when this agent started. This agent wrote NO
code: it spent its context reading and stopped at the soft budget. Everything below is the
design it settled on, with the facts that drove it, so the next agent can start at RED tests.
Step 4 (`destructive_git.py`) is another agent's; do not touch it.

## Facts established (read, or measured on this host)

- `branches.cleanup_after_merge.mode` (`act|advise|off`, default `advise`) ALREADY exists in
  `config/models.py` (`BranchCleanupAfterMergeConfig`), and the staged manifest
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml` already lists
  `branches.cleanup_after_merge`. Only a manifest entry for anything genuinely new is needed.
- This repo's `.claude/hooks-daemon.yaml` has NO top-level `branches:` block yet; add
  `branches: {cleanup_after_merge: {mode: act}}` (top level, beside `layout:` etc.).
- `classify_branch` refuses `REFUSAL_WORKTREE` before any proof, and ALWAYS falls through to
  the content-preserved tier (a walk of every reachable object) when merged and
  patch-equivalent fail. Too slow for a hook.
- A recovery bundle of one branch here: `git bundle create x refs/heads/main` took 8.2 s and
  wrote 51 MB. A full bundle per merge in a PostToolUse hook breaks the budget (HOOK_DISPATCH
  5 s per handler, chain deadline `Timeout.CHAIN_DEADLINE_DEFAULT` 20 s) and piles 51 MB files
  into `untracked/`.
- A linked worktree here is about 24k files including its venv; `Timeout.GIT_WORKTREE_REMOVE`
  is 300 s precisely because killing `worktree remove` part-way leaves a half-deleted prunable
  worktree (Plan 00474 N464). Never run it with a short timeout.
- After a SUCCESSFUL `git merge <branch>` the branch tip is an ancestor of HEAD, so the tier
  is always one of the merged tiers. Patch-equivalent only arises for branches merged some
  other way (the sweep's case).
- Parsing: `utils/git_commit_parsing.git_invocations(command)` gives `GitInvocation`
  (`subcommand`, `global_options`, `arguments`, `directory`); `utils/merge_scope.merge_directory (command, cwd)` places the merge; `daemon_sync_after_merge.py` is the model PostToolUse
  handler (matches, `_is_foreign_repo`, guidance, acceptance tests with
  `harness_cannot_produce`).
- CLI: `cmd_branch_sweep` in `daemon/cli.py` (~line 6489), parser ~12923; `_branches_config`
  helper beside it; `delete-branch` bundle default `untracked/deleted-branches.bundle`.
- Inventory: `BranchRecord.state` in `MERGED_DEFAULT`, `MERGED_LINE`, `PATCH_EQUIVALENT` are
  the `--clean` candidates; `record.worktree` (Path|None), `worktree_known`, `local_tip`
  (None = remote-only: skip, nothing local to delete), `proven_by`.

## Design settled

1. `daemon/branch_safety.py`, two small keyword additions (RED tests first, in
   `tests/unit/daemon/test_branch_safety.py`):
   - `classify_branch(..., ignore_worktree: bool = False)`: skip ONLY the `REFUSAL_WORKTREE`
     check, used for the proof before a worktree is removed. `delete_branches` never passes it,
     so the delete re-classifies with the worktree gone (the handoff trap).
   - `classify_branch(..., content_tier: bool = True)` and passed through `delete_branches`:
     when False, a branch neither merged nor patch-equivalent returns `TIER_UNPROVEN` with a
     detail saying the content tier was not run. Cleanup and `--clean` pass False, so only
     merged/patch-equivalent can ever be deleted (DESIGN section 7: anything else is left
     alone), and `allow_unproven` stays False so unproven blocks.
2. New `core/branch_cleanup.py` shared by the handler and `--clean` (DRY):
   - `cleanup_targets(repo, config, default) -> list[str]`: the default (bare name, resolved by
     `_protected_base_ref`), `refs/remotes/<remote>/<default>`, and each integration-line ref
     local and remote, ONLY refs that exist (`show-ref --verify`), because the content walk and
     merge-base on a missing ref fail.
   - Refuse up front: default, `integration_lines`, `exempt` and `protected_names` matches
     (`branch_safety.matches_any_glob`).
   - Worktree: map branch -> path from `git worktree list --porcelain`; never the MAIN
     worktree (first entry); clean = `git -C <path> status --porcelain` empty; dirty is skipped
     and reported; removal `git worktree remove <path>` with no `--force`, timeout
     `Timeout.GIT_WORKTREE_REMOVE`; git's refusal is reported verbatim.
   - Result per branch: deleted / advised / skipped(reason), the worktree removed, the commands
     (advise mode prints `git worktree remove <path>` then the delete command), and the remote
     delete `git push <remote> --delete <name>` printed only when `refs/remotes/<remote>/<name>`
     exists, never run.
3. Handler `handlers/post_tool_use/cleanup_after_merge.py` (new HandlerID, Priority, registry,
   guidance via `get_claude_md`, acceptance test with `harness_cannot_produce`, and its
   `.claude/hooks-daemon.yaml` handler entry if the registry requires one):
   - Matches a Bash `git merge` that is not `--squash`/`--abort`/`--continue`/`--quit`, takes
     the branch operands (skip `-m`/`-s`/`-X` option values), placed with `merge_directory`.
   - Success: PostToolUse only fires on success, but also require the branch tip to be an
     ancestor of HEAD (the proof does that).
   - Current branch of that checkout must be the default or match `integration_lines`; targets
     = `HEAD`'s ref only.
   - Budget: a module constant (e.g. `Timeout.CLEANUP_AFTER_MERGE_BUDGET`, under the 20 s
     chain deadline). Act only on the MERGED tiers; in act mode delete with `bundle_path=None`
     because every commit is reachable from HEAD, and print the restore line
     `git branch <name> <sha>`. Report this as a deliberate deviation from "bundle" in the
     brief, with the 8.2 s / 51 MB measurement. Patch-equivalent: advise only
     (`bin/hooks-daemon delete-branch <name> --protected-ref <target>`).
   - Worktree removal in a hook: run the cleanliness scan first and time it; if the proof plus
     scan already used more than half the budget, advise instead of removing (a tree that is
     slow to scan is slow to delete). Never start a removal it might have to kill.
4. `branch-sweep --clean` / `--dry-run` in `cmd_branch_sweep` + `core/branch_cleanup.py`:
   candidates from the inventory (states above, `local_tip` not None), targets =
   `cleanup_targets`, one `delete_branches` batch with a bundle at a timestamped path under
   `untracked/branch-cleanup/` (a CLI may take the 8 s), worktrees removed first, dirty skipped
   and reported; prints removed names, the bundle path and restore command, and the remote
   deletes. `--dry-run` lists without touching anything. Note `delete_branches` is
   all-or-nothing: classify each candidate individually first and only batch the proven ones.
5. Wrap-up exactly as the brief lists (report `261103-task31-cleanup.md` covering steps 0-3,
   release note `025-...md`, `branches.cleanup_after_merge.mode: act` here, journal via
   mkplan.bash, targeted QA). Do not tick PLAN.md or edit DESIGN.md.

## Known caveat to put in the report

`git worktree remove` without `--force` still deletes IGNORED files (`untracked/`, venvs) in
the worktree; only modified and untracked files make it refuse. That is git's own safe remove,
as DESIGN section 7 specifies, but scratch notes kept in a worktree's `untracked/` go with it.
