## 14:56 · decision · — — Q4/Q5 proposed defaults behind switches; two open design points

Q4 and Q5 implemented as PROPOSED defaults behind switches; owner ruling pending on both. Neither is settled.

- Q4 (how the cite reaches the guard): a trailing shell comment on the Bash command, `# human-approval team=<T> id=<$id>`. A comment is never expanded, which matters because the id starts with `$`. Lives in the Unit 2 handler, not in utils/human_approval.py.
- Q5 (who is armed): `is_armed(..., coordinator_seats_only=True)`. Default arms the main thread when some held team declares coordinator or a role is unreadable (unknown never disarms). `False` arms every main-thread seat. Arming never eases a pass: check_approval still requires coordinator in the cited team.

Open design points (not settled, raised for the owner):

1. Under the Q5 default a coordinator's SUB-AGENT is not armed, so a sub-agent can push/delete/merge unguarded. Arming sub-agents instead would deny every such act from a sub-agent, because check_approval never passes a sub-agent. No switch was added to "close" this; it is the owner's call.
2. Replay: one verified human line authorises any act of the cited classes for the same cite until its in-memory approval record lapses (default TTL 300s). Nothing binds the line's text to the specific act.

Also unverified here: the event id grammar `$[A-Za-z0-9._~+/=-]{1,255}` excludes `:`; if real ids carry a server suffix every real cite is refused (fails closed). Recorded beside the unverified issue 369 verify contract.
