# Callout: handler config reaches every wired event

**Plan**: 00362
**Audience**: operators

A `handlers.<event>:` section for any of the 31 wired events is now honoured.
Previously the config model declared only 13 event sections, so an
`enabled: false` or `options:` under any other event (`post_compact`,
`subagent_start`, `elicitation`, ...) was silently discarded at daemon start;
the model now refuses to import unless it covers the event registry exactly.
A plugin may also target `worktree_create` and `worktree_remove`, which
`config-validate` used to reject.
