# Callout: branches now sit in three pools (open, parked, merged), each with its own cap and age

**Plan**: 00571
**Audience**: client projects

Parked and merged-but-undeleted branches no longer count against `branches.wip.cap`: each is its own pool with a cap (`branches.parked.cap`, `branches.merged.cap`, both defaulting to `wip.cap`) and a maximum age (defaulting to the dormancy preset's `block_days`), and branch creation is denied while a pool is full or holds a stale member (`R-BRANCH-PARKED-POOL`, `R-BRANCH-MERGED-POOL`), naming that pool's own way out. An unkept merged branch is cleanup debt at once; `branch-sweep --clean` clears it, and the new `branch-keep <name> --reason "<text>"` keeps one you still need for the merged pool's age, as a git note every clone sees. `branch-sweep --clean --remote` fetches those keeps first and refuses the remote half if it cannot, re-parking needs a new reason, and `branches.bot_owned` (default `dependabot/*`) branches are never counted or cleaned (reported as issue #165). A merged branch whose worktree is under `.claude/worktrees/` (Claude Code's own) is still skipped by `--clean`; its skip line now names `worktree-reap --reap --only <name>`, which removes the worktree first.

The creation guard makes one more git call to find merged branches, so the client-side wait `init.sh` allows a WorktreeCreate hook is now 90 seconds (was 85); a project that pins or wraps that wait should allow the extra five seconds.
