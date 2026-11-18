## 10:30 · decision · — — Stand-in ruling: fix the two false allows

**Stand-in ruling, made by a fable sub-agent on the working session's behalf, not by the owner.**

Question: every open issue was `agent-needs-human`, so what should the session do next? The options were:

- A: fix the Plan 00610 follow-ups test-first.
- C: stay idle until the owner replied.

Ruling: option A, restricted to the two false allows, which are POSIX bracket classes and symlinked directories.

Reasons given:

- Both let a protected file be read past `secret_file_guard`.
- The work is ordinary test-first engineering.
- The globstar `**/` base-directory false deny is left for the owner, because an existing test asserts that behaviour.

A real owner message can overturn this ruling.

Note: the peer branch `agent-a1feef6afbe418af7-5a658292` holds a competing #204 fix, its Plan 00611, and is marked superseded by Plan 00610. Deleting it is the owner's call, and this plan does not touch it.
