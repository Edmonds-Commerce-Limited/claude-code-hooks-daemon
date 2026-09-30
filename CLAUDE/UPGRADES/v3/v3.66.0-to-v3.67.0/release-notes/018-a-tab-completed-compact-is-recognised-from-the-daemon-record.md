# Callout: a Tab-completed `/compact` is recognised from the daemon's record

**Plan**: 00399
**Audience**: operators

The ccy supervisor could not see a `/compact` reached by typing `/comp` and
pressing Tab, because Claude Code expands it inside the input box and no
keystrokes spell it. The daemon's `compaction_signal` record now says whose
compaction started (`human`, `supervisor` or `auto`), and the supervisor names
it in `decision.log` (`compaction detected (human /compact)`) without widening
its keystroke match, which a false recognition would make costly. One limit
remains: a Tab-completed `/compact` queued behind a streaming turn is not seen
until it runs, so the supervisor may still type one duplicate `/compact` in
that window.
