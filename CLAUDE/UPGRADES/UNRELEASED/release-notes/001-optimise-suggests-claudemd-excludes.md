# Callout: optimise now suggests `claudeMdExcludes` for worktrees under your project

**Plan**: 00563
**Audience**: client projects

`/hooks-daemon optimise` now checks for git worktrees kept under the project root (`untracked/worktrees/`, `.claude/worktrees/`, or any path `git worktree list` reports inside the root). When no `claudeMdExcludes` glob in `.claude/settings.json` or `.claude/settings.local.json` covers them, it prints an unscored suggestion with the exact globs to add (for example `**/untracked/worktrees/*/CLAUDE.md`). Without them a sub-agent working in such a worktree loads your root `CLAUDE.md` twice, up to about 30k tokens (reported as issue #156). It only suggests: nothing writes the setting unless you confirm at the apply prompt, and it stays silent when the globs are already present or no worktree lives under the root.
