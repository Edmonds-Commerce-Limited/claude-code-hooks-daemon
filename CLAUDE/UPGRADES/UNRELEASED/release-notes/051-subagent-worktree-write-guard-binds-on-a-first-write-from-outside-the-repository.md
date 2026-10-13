# Callout: subagent_worktree_write_guard binds an agent on a first write made from outside the repository

**Plan**: 00474
**Audience**: client projects

`subagent_worktree_write_guard` bound a sub-agent to the linked worktree of its first write only when the payload cwd was a checkout of the same repository. A first write made while the shared cwd was outside any git checkout, or in a different repository, was allowed but bound nothing, so a later write by the same agent into that same worktree was judged by whatever cwd the session then had: with the cwd in a sibling worktree it was denied naming the sibling, and the identical write from another cwd was allowed. Such a first write now binds the agent to the target's linked worktree exactly as a same-repository first write does, so later writes are judged against that binding. A first write with no `agent_id`, into a main working tree, or outside any checkout still binds nothing, and an unreadable git marker still fails open.
