# Callout: team guards arm only on evidence of a seat, and team-only guidance is opt-in

**Plan**: 00474
**Audience**: operators

The team handlers (`host_seat_lane_guard`, `human_approval_check`, `owner_wait_stop_guard`, `coordinator_board`, `ci_state_reading` and the rest that read a teamchat seat) now act only when there is evidence of one. In a bare Claude Code session, with no teamchat runtime or a probe that has never resolved a seat, they deny nothing, add no text and spawn no process. A teamchat probe that stops answering keeps a guard armed only in a session that has already resolved a seat, per session runtime; a definitive "no team" answer clears that memory.

A seat's duty is an optional teams field. A null, absent or unreadable duty is undeclared and arms nothing: only a declared `host` duty arms the host seat lane guard, and a host in one team is not disarmed by a null duty in another. A seat counts as coordinator when its role is coordinator and its duty is not `host`; it does not need a declared duty. A host seat's sub-agents are judged on the declared duty only and are advised, never denied.

Every team handler shares one seat resolver, so a session runs at most one `teamchat whoami` per `team_seat.resolve_ttl_seconds`. The handlers' rule text names no bus program; the runtime messages still print the adapter's own commands.

New key `team_seat.teams_in_use` (default `false`). It is read only by the generated CLAUDE.md guidance and the `optimise` review: with `false`, the team-only rules are left out of the generated block and the review calls those handlers not applicable. The handlers stay enabled either way. Set it to `true` in a project that runs teamchat teams; the generated block refreshes on the next daemon restart.
