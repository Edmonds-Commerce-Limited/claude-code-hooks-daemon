# Callout: sensitive_content no longer flags example values in faithful vendored docs

**Plan**: 00468
**Audience**: client projects

Vendored upstream documentation often contains example values that look like
your own, such as the UUIDs in Claude Code's hooks reference. `sensitive_content`
public patterns no longer judge the body of a `remote-docs` capture while that
body still matches the `source_sha256` recorded when it was fetched. You no
longer need an `exclude_paths` entry for each vendored page. This applies to
`Write`, to the `git commit` staged-content scan and to the whole-tree QA
check alike.

A vendored copy that has been edited since capture is scanned as normal, as is
any file outside the tree. The secret word list still applies to every file,
vendored or not.
