# Callout: private lint output directory, and a hook that no longer stalls on a wide character range

**Plan**: 00364
**Audience**: everyone

The Kotlin and Rust lint strategies used to write compiler output to a fixed,
guessable path in the shared temp directory. On a multi-user host another user
could pre-create that name as a symlink and steer the output through it, and two
concurrent lint runs shared the directory regardless. Both now write to one
unguessable per-process directory created 0700, resolved by a single helper so a
third strategy cannot reintroduce a literal. Nothing to configure; if you had
excluded the old paths from a backup or a cleanup job, those entries can go.

`secret_file_guard` also stops paying for a bracket range it was always going to
reject. Its expansion cap bounded the result but was checked only after the range
had been built, so a Write whose content carried a wide literal character range
cost 650 ms per token and over 13 seconds for twenty of them, on a PreToolUse hot
path. The cap now applies before the range is materialised. No verdict changes:
an over-cap token was left unexpanded before and still is.

Running the acceptance playbook takes eight more blocks for `pipe_blocker`, one
per language blacklist. Those probes existed but were declared where nothing ran
them.
