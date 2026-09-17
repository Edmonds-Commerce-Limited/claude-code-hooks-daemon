# Fix: `format-markdown` no longer rewrites files in other repositories

**Plan**: 00429
**Audience**: everyone

`hooks-daemon format-markdown <dir>` walked the whole tree and formatted every
markdown file it found, with no exclusion of any kind. On a project that vendors
a dependency as a real git checkout, the documented `format-markdown .` therefore
rewrote files inside a DIFFERENT repository and left uncommitted changes there;
`--check` reported them too, so a CI gate could fail on a file the project does
not own.

Two things changed. A directory below the walk root that is itself a git
repository is now skipped, which needs no configuration and is why the default
case is safe. And `daemon.exclude_paths` is now honoured, matching what the
docs-qa and plan-qa CLIs already do, so your declared exclusions apply here too.
Exclusions resolve against the enclosing PROJECT root rather than the directory
you happened to point the command at — `format-markdown docs/` and
`format-markdown .` exclude the same files.

A file named explicitly on the command line is still formatted even if excluded:
you asked for that one.
