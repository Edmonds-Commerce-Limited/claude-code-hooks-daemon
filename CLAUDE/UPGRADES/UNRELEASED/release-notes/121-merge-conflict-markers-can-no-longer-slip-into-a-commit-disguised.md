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

The gate recognises an opener wherever the formatter folds it: mid-heading,
in a blockquote, a list item or a table cell, labelled or not. A deep
email-style quote is not mistaken for a closer. It honours a path's
`conflict-marker-size` attribute, and it reads a text file that
`.gitattributes` marks `-diff` or `binary`.

It follows `cd` and `git -C` to the repository the commit runs in, and it sees
a commit behind `sudo`, `env`, `eval`, `sh -c` or a subshell. Redirections,
heredocs and option values such as `-F` or `--author` are never read as
paths.

A commit it cannot check is **denied**, never allowed. The deny names the
reason and suggests `git -C /absolute/path/to/repo commit`. This covers a
directory built from a variable, `cd -`, `GIT_INDEX_FILE`,
`--pathspec-from-file`, `git am <patch>`, and a git error.

A file that must hold a documented marker example, even inside a fenced code
block, goes under the handler's new `exclude_paths` option. The project-wide
`daemon.exclude_paths` applies too.

The CLAUDE.md injector no longer auto-commits a CLAUDE.md it could not read.
It logs the real reason, which fixes a misleading "check file permissions"
warning when the file vanished mid-restart.
