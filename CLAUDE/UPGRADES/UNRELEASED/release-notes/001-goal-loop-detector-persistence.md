# Callout: the goal-loop detector no longer mistakes journal commits for progress, and reports a loop that persists

**Plan**: 00501
**Audience**: operators

The detector's repository fingerprint now hashes the committed tree by content, so a commit that touches only plan journals (or no file) no longer re-arms a loop; before, a stand-in's journal-only commit split one long goal loop into many `would-enter` records and, in `act` mode, would have ended the block. In `act` mode a loop is now entered once per fingerprint instead of on every threshold crossing (one goal clear and one notice, not several). A loop that stays latched or blocked now logs a `loop-persisting` transition every `persist_every_crossings` further crossings (new option, default 5) carrying its cycles, crossings and first-seen time, and the first one queues one line telling the agent to say plainly to the human that the goal is unsatisfiable and that `/goal clear` or `bin/hooks-daemon clear-goal` ends it. Modes, thresholds and the goal text are unchanged.
