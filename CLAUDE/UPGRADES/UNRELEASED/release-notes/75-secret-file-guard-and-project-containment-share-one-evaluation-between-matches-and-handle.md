# Callout: `secret_file_guard` and `project_containment` share one evaluation between `matches()` and `handle()`

**Plan**: 00466
**Audience**: client projects

`matches()` and `handle()` each independently re-evaluated the same call, so
a TRANSIENT exception `matches()` correctly turned into a deny could be
silently overwritten by a clean re-evaluation inside `handle()` moments
later — turning a correct deny into an allow for a call `matches()` itself
had already flagged. Both guards now evaluate once per dispatch and hand the
same result to `handle()`, so a raise `matches()` saw is the raise
`handle()` denies on.
