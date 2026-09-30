# Callout: two `hooks-daemon` skill changes the last release notes left out

**Plan**: 00408
**Audience**: operators

Both shipped in v3.64.0 without appearing in its notes. The `hooks-daemon`
skill's description now lists `optimise` (tune the configuration) and
`bug-report` (file a local bug report), so asking for either routes to the
skill. The skill's `regen-docs` page now says what a `restart` really does: it
refreshes only the `<hooksdaemon>` block in `CLAUDE.md`, never
`.claude/HOOKS-DAEMON.md`. After you add or remove a handler, run
`regenerate-docs`, which refreshes both.
