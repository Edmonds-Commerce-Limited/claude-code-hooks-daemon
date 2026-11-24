# Callout: a coordinator team seat's push, delete, chmod or merge into main now asks for a human's cited approval

**Plan**: 00634
**Audience**: operators

The new `human_approval_check` handler (priority 21, `R-HUMAN-APPROVAL-MISSING`) watches sessions that hold a teamchat seat as coordinator, or whose role cannot be read. When such a session runs a `git push`, a forced branch, remote-ref or worktree delete, a world-writable `chmod`, or a merge into main, the command must cite a questions-room line a declared human of the team sent, as a trailing comment on its last line: `git push origin x  # human-approval team=<team> id=<$event-id>`. A peer agent's line never counts. A sub-agent of a declared coordinator seat is judged as the seat (see note 103). A session with no team seat is unaffected and never runs the probe.

It ships in `mode: advise`, which only adds the refusal as context. Keep it there: `advise` is annotation only, and the cite check (note 103) is coded against a `verify` contract not yet checked against a live teamchat. `coordinator_seats_only: true` (the default) arms only coordinator seats; it is a proposal awaiting the owner's ruling.
