# Callout: format-markdown no longer crosses repository or exclusion boundaries

**Plan**: 00429
**Audience**: operators

`hooks-daemon format-markdown <dir>` (write and `--check` modes both) now
skips any directory below the walk root that is itself a git repository, and
honours `daemon.exclude_paths` the same way the docs-qa and plan-qa CLIs do.
Previously, running it from a project root that vendors dependencies as real
git checkouts (the documented `format-markdown .` invocation) could rewrite
and leave uncommitted changes inside a repository you do not own. A file you
name directly is still formatted regardless of exclusions, because naming it
is explicit consent — only the directory walk filters.

Exclusions resolve against the enclosing PROJECT root rather than the directory
you point the command at, so `format-markdown .` and `format-markdown docs/`
exclude the same files.
