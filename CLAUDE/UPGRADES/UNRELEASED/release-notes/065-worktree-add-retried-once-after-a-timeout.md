# Callout: a worktree add that times out under host load is retried once, and its budget is configurable

**Plan**: 00474
**Audience**: client projects

On a heavily loaded host `git worktree add` could still time out even on its load-scaled budget, and the agent dispatch then failed outright with no retry. The handler now undoes the timed-out add and, when the undo left nothing behind, attempts the add once more on a budget scaled from a fresh load reading. Only a timeout is retried; an existing branch or path, a refused hook or any other git error is deterministic and fails at once. If the retry fails too, the deny says that one automatic retry was already made.

Because the event can now make two adds and two undos, the `WorktreeCreate` event deadline grows and the client wait in `init.sh` moves from 230 to 450 seconds. The hook is registered without a short timeout, so nothing else changes.

The `worktree_create` handler gains two options, `add_base_seconds` (default 30) and `add_ceiling_seconds` (default 120). Both are positive numbers, the base may not exceed the ceiling, and the ceiling may not exceed 120 because the event deadline is sized for it. The defaults are the previous constants, so behaviour is unchanged until a project sets them. An invalid value is reported at session start and that option runs on its default.
