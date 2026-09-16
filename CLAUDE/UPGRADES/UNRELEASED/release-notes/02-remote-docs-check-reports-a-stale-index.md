# Callout: `remote-docs check` reports a stale generated index

**Plan**: 00425
**Audience**: operators

Deleting a vendored capture with `rm` never regenerated `.claude/REMOTE-DOCS.md`
— it kept naming a file that was gone, and `check` said everything was fresh.
`check` now compares the index against the tree and reports a disagreement as
a finding, with exit `1`, the same as staleness and licence drift. This can
turn a previously-green CI run red the first time it runs after a deletion.
The fix is the new `remote-docs index` command, which re-renders the file
without touching the network.
