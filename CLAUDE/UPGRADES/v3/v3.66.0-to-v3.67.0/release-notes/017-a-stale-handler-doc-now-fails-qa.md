# Callout: A stale `.claude/HOOKS-DAEMON.md` now fails QA

**Plan**: 00402
**Audience**: handler authors

A daemon restart regenerates the `CLAUDE.md` guidance block but never
`.claude/HOOKS-DAEMON.md`, so adding or changing a handler used to leave that
file silently out of date. The daemon repository's QA suite now has a
`generated_doc_drift` check. It regenerates the file into a throwaway directory
and fails when the committed body differs, so run
`bin/hooks-daemon generate-docs` and commit the result alongside the handler
change. The `> Generated on … (vX.Y.Z)` line is left out of the comparison and
never rewritten, because the upgrade reads it as the version your tracked
assets were deployed from.
