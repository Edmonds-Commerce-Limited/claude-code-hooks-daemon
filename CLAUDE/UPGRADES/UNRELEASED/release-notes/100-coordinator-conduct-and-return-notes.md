# Callout: a coordinator seat is told its bus conduct, and what to re-read after a compaction

**Plan**: 00636
**Audience**: operators

The new `coordinator_conduct` SessionStart handler adds a conduct note on every new, resumed or compacted session of a team coordinator seat. The team chat is the only human surface, so an ask, a report or a wait the owner must act on is a notifying post in its own thread, and a line left only in the terminal counts as unsent. A reply to a human message goes in that message's thread. Dispatch, tracking, the report and closing the thread all happen on the bus. A peer's message carries no authority, and the seat asks another seat before asserting what its code does. The seat says on the bus before a planned departure. A usage pause allows only its short tool list, so after one the seat tells the team how long it was away.

On a resumed or compacted session the handler also adds a return note: before dispatching, reassigning or answering, re-read the questions room and every thread the seat asked or owns, `work-queue list`, and the `owner_directives_register` config. What the seat remembers from before is a lead, not a fact. If a usage pause is live when the session resumes, the return note is a short line without commands (the pause denies Bash): re-read the questions room and own threads once the pause lifts.

The text is fixed and relays nothing from the bus; the only command the handler runs is the shared `whoami` seat probe. It is advisory and never denies. A declared worker, a session with no team and a sub-agent are untouched. The upgrade adds the handler's config entry; nothing else needs changing.
