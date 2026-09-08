# Callout: the ccy supervisor announces every keystroke it sends

**Plan**: 00355
**Audience**: operators

Every key the supervisor injects (an escape to flush a stalled compaction,
an Enter to resubmit) now raises the status-line banner on the tick that
sends it, and repeats collapse to a tally such as `esc (20), compact (15)`.
An informational banner yields to a live host warning rather than replacing
it. The "random ESC presses" some operators saw were these flushes, now
visible.
