# Callout: `mkplan.bash --journal` stamps journal entries in UTC

**Plan**: 00427
**Audience**: everyone

`mkplan.bash` now accepts `--journal <plan-number> <category> <body-file> [--ref R] [--title T]` to append a journal entry to an existing plan. The
script reads the clock itself and normalises it to UTC, so the agent never
types (or estimates) a timestamp -- closing the first of the two failure modes
measured on issue #45, an agent's guessed time drifting from real elapsed time.
The second (a naive future-dated check misreading an entry written in a
different zone) needed the reader to change too; see the next callout.

A day-file the scaffolder creates carries one sentinel line in its preamble
naming the writer and the zone; a day-file with no sentinel predates this
system and is left exactly as it is -- no migration, no rewrite of the
existing 2,207 entries across this project's own history. Hand-authored
entries (`Write`/`Edit`/a heredoc) are unaffected and still carry no zone.
