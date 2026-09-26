# Callout: dispatch-declaration recognises more report-destination phrasings

**Plan**: 00466
**Audience**: operators

The dispatch-declaration advisory (Plan 00307) used to require a fixed
"verb + to/in/under/into + path" grammar to recognise a declared report
destination. A brief phrased as a label — "File to write to: <path>" —
was missed: the colon after "to" broke the required whitespace, and
"file" as a noun was not in the recognised keyword list at all. The
advisory then nagged on a correct dispatch.

The check now recognises any destination keyword ("write"/"save"/"report"/
"output"/"store"/"file") paired with a path-shaped token in the same
clause, not only the old fixed phrasing — while still refusing to count a
bare plan-folder mention in one sentence as a declaration when the actual
verb is in the next (Plan 00460 review finding m4's distinction is
unchanged).
