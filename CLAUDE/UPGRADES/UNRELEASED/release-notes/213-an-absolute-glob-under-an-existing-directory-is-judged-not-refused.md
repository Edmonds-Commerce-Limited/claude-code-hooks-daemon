# Callout: an absolute glob under an existing directory is judged, not refused

**Plan**: 00474
**Audience**: operators

`secret_file_guard` and `quarantine_artefact_read_guard` denied an ordinary
command such as `cat /some/dir/*/*` with an evaluation error, because an
absolute glob with two or more wildcard segments was refused as a walk of the
filesystem root. That count ignored the literal directory in front of the
wildcards, which already confines the walk to one directory (GitHub #68,
ledger 00474 N293). `for x in a b; do cat "$x"/some/dir/*/*; done` hit the same
refusal, as did a single-wildcard glob such as `cat /some/dir/*/x` when one
sibling directory could not be searched.

The walk now starts at the longest existing literal prefix, so such a glob is
expanded and judged on what it reaches. A protected file it reaches is still
denied, at any depth. Two things are unchanged: a glob whose walk still starts
at the filesystem root (`/*/*`, `/**`, or a prefix such as `/usr/..` or a
symlink that resolves back to the root) is refused, and a `**` walk is still
capped on entries visited. A directory that cannot be listed still fails
closed, because the names inside it cannot be ruled out. A path inside a
sibling directory that cannot be searched is judged by its name, since the
wildcard has left only literal components to name.
