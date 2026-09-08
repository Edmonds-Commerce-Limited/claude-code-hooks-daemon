# Callout: a malformed glob no longer skips the quarantine artefact guard

**Plan**: 00357
**Audience**: everyone

A Bash command carrying a malformed recursive wildcard (such as `a**b.md`)
used to raise inside `quarantine_artefact_read_guard`, and the daemon's
fail-open policy then skipped that guard for the whole call. The expansion is
now guarded where it actually runs, so such a command is judged like any
other.
