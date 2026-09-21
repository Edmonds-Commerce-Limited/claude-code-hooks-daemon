# Callout: `remote-docs add` refuses an existing capture

**Plan**: 00424
**Audience**: operators

`remote-docs add <url>` now refuses when a capture of that URL already
exists, naming the existing file's `fetched_at` and `source_sha256` and
pointing at `refresh` or `--force` rather than silently overwriting it. If
you relied on a bare `add` to re-derive frontmatter after declaring
`documentation.remote.known_sources` — the licence-drift remedy `check`
prints — use `add --force` instead, which replaces the capture and prints
both the old and new `source_sha256`.
