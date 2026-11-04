# Plan 00558 Task 3.1 step 4: integration lines in R-GIT-PUSH-DELETE-REMOTE

Branch `worktree-558-remote-lines` (cut from `worktree-558-cleanup` at 0e5c99d61), pushed, not merged.

## Commits

- `3d605ed7a`: the change, tests and release note.
- `5eaa2f6c3`: black formatting of the handler (QA `format`).

## What changed

`src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py`:

- `DestructiveGitHandler.__init__` declares `self._branches: BranchesConfig = BranchesConfig()`.
  The registry already injects the top-level `branches:` block onto any handler declaring
  `_branches` (`handlers/registry.py`, the same selection `branch_sweep` uses), so no other
  wiring was needed. With no config, the model defaults apply.
- `_remote_delete_note(command, cwd, branches)`; `handle()` passes `self._branches`.
- The default branch now comes from `resolve_default_branch(branches, directory)`
  (honours `branches.default`; `auto` falls back to the old `default_branch` lookup).
- `_merged_tracking_tip` (per-branch `rev-parse` x2 and `merge-base` x2) is replaced by:
  - `_named_ref_problem` / `_refusal`: literal-name checks, then outright refusal of the
    default, an integration line, an exempt name, a protected name, in that order, each
    reason naming which (`branches.integration_lines`, `branches.exempt`,
    `branches.protected_names`). Matching is `branch_safety.matches_any_glob`.
  - `_merged_tracking_tips`: ONE `for-each-ref` listing (`refs/remotes/<remote>`,
    `refs/heads/<default>`, `refs/tags/<name>` per name) gives tracking tips, tag
    ambiguity and the targets that exist; then ONE `for-each-ref --merged=<target>` per
    target over all the named tracking refs. Targets: `refs/remotes/<remote>/<default>`,
    `refs/heads/<default>` (kept from before), and every existing
    `refs/remotes/<remote>/<line>` matching `integration_lines`. All keyed by exact refname.
  - Any `for-each-ref` failure denies every branch of that push, naming each.
- `_live_remote_tips` / `_remote_tip_problems` (the batched `ls-remote`) are untouched.
- The verbose rule text, the CLAUDE.md row and the denial footer mention integration lines
  and exempt/protected names. The `_RULE_DEFINITIONS` tuple wording was left as it is.

Behaviour change worth flagging: protected names were not checked here before, so a remote
`develop` (model-default protected) that was merged and deletable is now refused.

## Tests

- New `tests/unit/handlers/pre_tool_use/test_destructive_git_remote_delete_lines.py`
  (8 of 10 RED before the change): merged only into `release/x` allowed; same branch denied
  without the line configured; `release/x` refused; exempt and protected refused; default
  refused; `_branches` default; 40 branches = one `ls-remote`, no `rev-parse`/`merge-base`,
  and the same 4 `for-each-ref` calls as 2 branches; a `--merged` failure denies; a listing
  failure denies.
- `test_destructive_git_remote_delete_batched.py`: its git stub answers `for-each-ref`
  instead of `rev-parse`/`merge-base`, and stubs `resolve_default_branch`. Its ls-remote
  assertions are unchanged.
- All 572 `destructive_git` tests pass.

## QA

Run on `5eaa2f6c3`: `QA: 41/42 PASSED, 1/42 FAILED`. The only failure is the `changed_tests`
"too-broad" unmapped notice (375 tests passed, 0 failed). The `changed_tests` "too-broad" unmapped notice
(destructive_git.py and the two branch files inherited from the base branch) is the
accepted non-blocker.

## Not done

Nothing from the brief. PLAN.md, DESIGN.md, the repo yaml and the journal were not touched,
as instructed. No config-changes manifest entry: no new key or default was added.
