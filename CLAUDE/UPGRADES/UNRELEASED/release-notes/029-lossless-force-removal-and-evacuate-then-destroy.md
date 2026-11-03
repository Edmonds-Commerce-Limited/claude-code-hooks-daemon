# Callout: a forced branch delete or worktree removal is allowed only when nothing is lost, and copying work out before destroying it is denied

**Plan**: 00558
**Audience**: operators

`destructive_git` now judges what a removal would lose instead of trusting a remote alone.

- `git branch -D` and `git update-ref -d refs/heads/<name>` are allowed when every named tip is reachable from ANY surviving ref: another local branch, a tag or a remote-tracking ref. Refs the same command deletes do not count. One `git rev-list <tips> --not --glob=...` call proves every tip at once. A denial names each branch with the number of commits it would lose. `branches.force_removal.mode: off` restores the remote-tracking-only check.
- `git worktree remove` is judged under the new rule R-GIT-WORKTREE-REMOVE-FORCE, with or without `--force`, because git deletes ignored files either way. It is allowed when every ignored entry matches `branches.cleanup_after_merge.regenerable`. A forced removal must also have a clean status and a HEAD that a surviving ref holds. A denial lists the paths that would be lost. With `branches.force_removal.mode: off` it is not judged.
- New rule R-GIT-EVACUATE-THEN-DESTROY: one command that writes a worktree's or branch's work to a file nothing tracks, then destroys that same worktree or branch, is denied. The copy is made with `git diff`, `format-patch`, `stash show -p` or `show`, through a redirect, `tee` or `-o`. The destruction is `worktree remove`, `branch -d/-D`, `update-ref -d` or `rm -r` of the worktree. The deny says to commit or push on the lane's branch, or to ask a human. `branches.evacuation.mode` is `block` (the default), `warn` (allow with the same text as context) or `off`.
- The same rule covers the destruction in a LATER command of the same turn. A new PostToolUse handler, `evacuation_recorder` (priority 41), records the worktree and branches of each evacuation in the session's spend-ledger state; `destructive_git` denies a `worktree remove`, `branch -d/-D`, `update-ref -d` or `rm -r` of recorded work under the same rule and mode. The main thread's turn is a counter that a new UserPromptSubmit handler, `evacuation_turn_marker` (priority 43), advances at each prompt, so a patch exported in an earlier turn never blocks later cleanup; a sub-agent's turn is its lifetime. The record keeps the current turn only, at most 50 evacuations.

Every one of these denials ends with the shared branch-limit principle.

Nothing to do on upgrade. Commands that used to be allowed and are now denied are commands that would have lost work.
