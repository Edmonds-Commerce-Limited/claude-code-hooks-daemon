# Callout: the `optimise` report is scored by the registry's own gates

**Plan**: 00364
**Audience**: handler authors

`/hooks-daemon optimise` decided which handlers were enabled with its own
copy of registration's rules, and the copy was already incomplete: it missed
the registry's runtime disable, and it required `enable_tags` to be a list
where registration accepts any truthy value. A scalar `enable_tags: safety`
therefore took an event dark in the daemon while the report called every
handler on it enabled. Both now call one shared predicate in
`handlers/registry.py`, pinned by a test that registers handlers for a config
and asserts the report agrees with what registration did, handler by handler.

A handler whose constructor raises no longer aborts the whole verb either. It
appears in the report as `could not be assessed` with its error, so the other
handlers keep their verdicts and the broken one is visible rather than
absent. The JSON output gained `unassessed` in the summary and
`construction_error` on each item.
