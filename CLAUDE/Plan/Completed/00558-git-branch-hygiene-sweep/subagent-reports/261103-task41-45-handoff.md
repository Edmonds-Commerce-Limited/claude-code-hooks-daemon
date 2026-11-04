# Handoff: Plan 00558 Tasks 4.1 (done) and 4.5 (not started)

Worktree `/workspace/untracked/worktrees/worktree-558-force`, branch `worktree-558-force`, pushed. Task 4.1 is commit `bcc1af48f`. This agent passed its context soft budget after Task 4.1; Task 4.5 and the wrap-up are left for a fresh agent.

## Task 4.1: done (commit bcc1af48f)

- `src/claude_code_hooks_daemon/core/force_removal.py`: `uncontained_tips(repo, tips, excluded_refs, namespaces)` and `lost_commit_count(...)`. A deviation from the brief, on purpose: the proof is ONE `git rev-list <tips> --not [--exclude=<ref>]... --glob=refs/heads --glob=refs/remotes --glob=refs/tags`, not `for-each-ref --contains`. `for-each-ref` with several `--contains` lists the refs that contain ANY tip, so it cannot say which tip is held. With `rev-list`, a tip some surviving ref reaches drops out of the output, so one call answers for every tip. Nested branch names are covered (tested). `ContainmentUnknown` is raised on a git failure, and the caller fails closed.
- `handlers/pre_tool_use/destructive_git.py`: a new pattern and rule R-GIT-WORKTREE-REMOVE-FORCE (every `git worktree remove`, forced or not), and `_LOSSLESS_WHEN_PROVEN` = {branch force delete, worktree remove}. `_ForceRemovalJudge` judges the whole command:
  - excluded refs are grouped by `--git-common-dir`;
  - `worktree_blockers` covers both forms;
  - the HEAD-held check runs for the forced form only;
  - each loss is stated with its commit count and paths (`preview_paths`, which `core/branch_cleanup.py` now exports).
- Every deny appends `BRANCH_LIMIT_PRINCIPLE`.
- `branches.force_removal.mode: off` keeps the old remote-only branch check and leaves worktree removal unjudged. The `force_removal` and `evacuation` config keys were ALREADY in `config/models.py`, so no config key or config manifest entry was added.
- `RuleID.GIT_WORKTREE_REMOVE_FORCE` and `RuleID.GIT_EVACUATE_THEN_DESTROY` (reserved for 4.5) were added. `bin/hooks-daemon explain-rule R-GIT-WORKTREE-REMOVE-FORCE` works. An acceptance test was added.
- Tests: `tests/unit/core/test_force_removal.py` and `tests/unit/handlers/pre_tool_use/test_destructive_git_force_removal.py`. Existing tests were updated: two `worktree remove --force` "not blocked" tests now assert that only the worktree rule matches, the rule-id set gains the new id, and the failing-query test patches `force_removal.run_git`.

## Task 4.5: left, with a suggested shape

- Same command: inside `destructive_git` (it already sees every git destruction; `rm -r` needs a matcher too). Use `utils.git_commit_parsing.simple_commands(command)`. Each `SimpleCommand` carries `words`, `directory` (cd chain), `redirects` ((op, target)), `operator` (`|` for tee) and `git` (`GitInvocation`).
  - Evacuation: git `diff`, `format-patch` (`-o`/`--output-directory`), `stash show -p`, or `show`, with the output landing in a target that is not a tracked file (`git ls-files --error-unmatch` fails, which also covers ignored and new paths) or that is outside the repo.
  - Destruction: the existing `_worktree_removals`, `_deleted_branches`, or `rm -r` of a worktree dir. Place `rm` paths with `utils.git_invocation_directory.placed_moves(step.directory, cwd)`.
  - Match on the worktree toplevel or the branch name. Deny with `RuleID.GIT_EVACUATE_THEN_DESTROY` (add a `_RULE_DEFINITIONS` row and a pre-check in `handle`), plus the right move (commit on the lane's branch or push, or ask a human) and `BRANCH_LIMIT_PRINCIPLE`.
  - `branches.evacuation.mode`: block | warn | off. `handle` currently only DENYs; warn needs an ALLOW with context.
- Same turn: a PostToolUse recorder (new file under `handlers/post_tool_use/`) and a lookup in the PreToolUse check. The spend-ledger state API and the turn counter were NOT located yet (grep `spend_ledger` and `turn` under `src/claude_code_hooks_daemon/core/`).

## Wrap-up still owed

- The report `subagent-reports/261103-task41-45.md`.
- Release note 098 (`# Callout:`, `**Plan**: 00558`) covering 4.1, and 4.5 once done.
- Manifest entries.
- `DestructiveGitHandler.get_claude_md` still describes only the remote-tracking condition. Update it to "any surviving branch, tag or remote-tracking ref" and add the worktree rule, then regenerate the guidance docs if docs QA asks for it.
- Targeted QA: a run on bcc1af48f was in progress when this handoff was written. Its result, if it finished, is in `untracked/scratch-qa.txt` in this worktree.
