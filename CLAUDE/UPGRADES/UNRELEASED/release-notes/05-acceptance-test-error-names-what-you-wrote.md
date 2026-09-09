# Callout: an acceptance test's contradiction names the field you declared

**Plan**: 00364
**Audience**: handler authors

Declaring both `hook_input` and `dispatch_as_bash` on an `AcceptanceTest` was
correctly refused, but the message read "hook_input and tool_payload are
mutually exclusive" — naming a field the author never wrote, because deriving
the Bash payload had already populated it. The pair is now checked before the
derivation runs, so the error names `hook_input` and `dispatch_as_bash`. The
invariant is unchanged; only the message is now about your declaration.
