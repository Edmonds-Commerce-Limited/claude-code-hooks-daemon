# Callout: the stop guard follows the pools' `warn` mode and counts branches on one tip once

**Plan**: 00618
**Audience**: client projects

Both changes allow stops that the previous build denied. The project owner chose both after the release code review.

- **`warn` now warns at stop.** With `branches.wip.mode: warn` or `branches.dormancy.mode: warn`, a stop that leaves one of the session's own open branches over the open-work cap, or past the dormancy block stage, gets a context line and goes ahead. Before, the stop guard denied it in `warn` mode exactly as in `block` mode, although the branch-creation guard only warned. `block` still denies, `off` still reports nothing, and the other stop checks (dirty worktree, commits no remote holds, merged but not deleted) still follow `branches.stop_guard.mode` alone.
- **One tip, one branch.** At stop, open branches that point at the same commit now count once against `branches.wip.cap`, as they already did in the open-work count, the pool count and the creation guard. Example: branches `a` and `a2` on the same pushed commit with `wip.cap: 1` no longer refuse the stop of the session that touched `a`.

No configuration change is needed. If you relied on `warn` to refuse stops, set the pool's mode to `block`.
