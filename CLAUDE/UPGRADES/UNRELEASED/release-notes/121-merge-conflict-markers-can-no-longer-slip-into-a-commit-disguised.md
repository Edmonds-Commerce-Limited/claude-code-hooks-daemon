# Callout: merge-conflict markers can no longer slip into a commit disguised

**Plan**: 00466
**Audience**: operators

Editing a markdown file that still had merge-conflict markers in it ran the
markdown formatter over the whole file. The formatter turned the opener into
an escaped heading and the closer into a seven-deep blockquote, and after
that no check recognised either as a conflict marker. Two of them reached a
committed file in this project that way.

The formatter now leaves a conflicted file untouched and names each marker
line instead. `format-markdown` reports such a file as an error, and the
CLAUDE.md injector writes it unformatted. A new PreToolUse handler,
`conflict_marker_commit_gate`, denies a `git commit` (and a `--continue` of a
merge, cherry-pick, revert or rebase) when a line it adds carries a marker in
either spelling, and names each file and line. A line of seven `=` counts only
between an opener and a closer, so a setext heading underline is not
affected. It is on by default.
