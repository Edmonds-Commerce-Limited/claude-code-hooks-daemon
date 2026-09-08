# Callout: the release now checks the slate is clean before it starts

**Plan**: 00359
**Audience**: everyone

`/release` opens with a slate-clean gate: `hooks-daemon release-slate-check`
confirms HEAD's exact sha is CI-green and lists mid-work plans, branches
ahead of main and live worktrees. Anything in flight stops the release for a
human decision; `/release accept-wip` proceeds with the report printed.
