# Callout: a team coordinator's waiting stop must first tell the owner on the bus

**Plan**: 00636
**Audience**: operators

New Stop handler `owner_wait_stop_guard` (priority 3, enabled by default). In a teamchat team where the role probe says this session is the `coordinator`, a stop that waits on a human (a `STOPPING BECAUSE:` line waiting on someone, or the awaiting-human mode) is refused until every open owner-facing thread the seat asked or owns got a notifying post from it, with a real body, within `options.window_minutes` (default 30). The refusal names the threads and the `pingbus thread ... --ask` commands to post, then says to stop again; a re-entered stop is always allowed. Workers, an unknown role and sessions in no team are untouched.

**Expect one refusal per waiting coordinator stop on pingbus v1.** `options.on_unreadable_bus` defaults to `refuse`: a wait the bus cannot confirm is refused once, saying why. The v1 adapter cannot read the notify flag, so until a v2 adapter lands every waiting coordinator stop is refused once. Set `on_unreadable_bus: allow` to fail open with a WARNING instead.
