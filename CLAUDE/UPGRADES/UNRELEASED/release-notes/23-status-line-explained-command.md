# Callout: `status-line-explained` explains every status-line icon

**Plan**: 00369
**Audience**: everyone

`hooks-daemon status-line-explained` (alias `explain-status-line`; skill:
`/hooks-daemon status-line-explained`) answers "what does this icon mean,
and what does its current value mean?" for every status-line segment in your
project, one section per segment: its glyph(s), what it is in general, how
to read it, and what it currently shows (or why it is not shown right now).
Disabled handlers are listed separately. `--format json` for scripting.

This closes a real gap `explain-rule`/`explain-handler` could not: a
status-line segment is advisory-only and declares no blocking rule, so
neither of those commands could ever find it — there was previously no way
to ask what an icon meant except reading the handler's source.
