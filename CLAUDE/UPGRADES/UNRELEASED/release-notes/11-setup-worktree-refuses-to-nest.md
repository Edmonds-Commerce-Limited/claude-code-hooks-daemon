# Callout: setup_worktree.sh refuses to create a worktree inside a worktree

**Plan**: 00433
**Audience**: operators

A worktree carries the whole tree, `scripts/` included, so running the copy that
is right there is the natural thing to do — and `PROJECT_ROOT` comes from the
script's own location, so the new worktree lands under the INNER checkout. An
agent dispatched with `isolation: worktree` already has an isolated checkout and
cannot tell it apart from a normal one, so a brief that also says "create a
worktree" nests them.

`scripts/setup_worktree.sh` now detects this before creating anything, refuses,
names the enclosing checkout, and prints the command to run there instead.

The overlong socket path is only the visible half of the cost, and the
AF_UNIX pre-flight already catches that. The expensive half is that work
committed in the nested tree lives on a branch inside a tree the coordinator may
later reap, and its QA is graded against whichever daemon that tree resolves.

The documented CHILD worktree workflow is unaffected: a child is created from
the main checkout with a parent base branch, so the refusal never fires for it.
A directory git cannot answer for fails open with a warning, as the socket
pre-flight does — a broken check must not block worktree creation.
