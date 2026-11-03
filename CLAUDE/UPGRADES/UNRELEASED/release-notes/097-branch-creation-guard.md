# Callout: a new branch is denied while the open work branches are at the cap

**Plan**: 00558
**Audience**: operators

The new `branch_creation_guard` PreToolUse handler (rule `R-BRANCH-WIP-CAP`) judges every git command that creates a branch (`switch -c/-C/--orphan`, `checkout -b/-B/--orphan`, `branch <name> [start]`, `worktree add -b/-B`, and a bare `worktree add <path>`) and every Agent dispatch with `isolation: "worktree"`. When the open work branches already number `branches.wip.cap` (default 10), the creation is denied; `branches.wip.mode: warn` only warns and `off` stops counting.

- Local and remote refs of one name, and branches at one tip, count once. The default branch, integration lines, protected and exempt names never count.
- A name already in `refs/heads` is a reset or a checkout, never a creation, so `checkout -B`, `branch -f` and switching to an existing branch are never denied. A name the shell builds (`$NAME`) cannot be read and is allowed.
- The deny lists every open branch with its age and worktree, merged and patch-equivalent branches first with their `bin/hooks-daemon delete-branch` command, ordered from the labels the SessionStart branch summary now writes to `untracked/branch-inventory/labels.json`.
- A new name that shares a stem or an issue number with an existing branch draws a warning naming that branch (`branches.duplicates.mode`); it never denies.
- WorktreeCreate applies the same verdict before its `git worktree add` and refuses the creation at the cap. Its event budget grows by two short git calls, so the `.claude/init.sh` client wait for WorktreeCreate is now 70 seconds.
- A git failure allows the creation with a "could not judge" line.

Enable it with `handlers.pre_tool_use.branch_creation_guard: {enabled: true, priority: 40}`.
