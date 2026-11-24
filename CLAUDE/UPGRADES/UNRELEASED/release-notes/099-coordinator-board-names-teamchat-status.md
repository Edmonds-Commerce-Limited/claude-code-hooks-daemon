# Callout: a coordinator seat is told where the board is, and that an unreadable seat is not down

**Plan**: 00636
**Audience**: operators

The new `coordinator_board` SessionStart handler adds one note on every new, resumed or compacted session of a team coordinator seat: peers' state in one view is `teamchat status`, which the seat runs itself; teamchat's files (`status.json`, the run directory, the seat store) are not the board; and a seat the board does not show, or whose state cannot be read, is unknown, not down, so the seat asks it on the bus before reassigning its work or telling the team it has gone.

The handler runs no teamchat command, opens no teamchat file and relays no status text. It is advisory, never denies and restarts nothing. A declared worker, a session with no team and a sub-agent are untouched. The upgrade adds the handler's config entry; nothing else needs changing.
