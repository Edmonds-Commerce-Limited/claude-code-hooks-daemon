# Callout: `secret_file_guard` and `project_containment` stay fail-closed past a real match

**Plan**: 00466
**Audience**: client projects

Both guards' fail-closed wrapper only covered reaching a verdict — once
`handle()` had a genuine match, building the deny message (the disclosure
tracker, the rule formatter, string assembly) ran unwrapped, so an exception
there escaped `handle()` uncaught and a non-strict chain treated it as "no
match": an ALLOW for a call that had a real protected-path mention or
out-of-root write target. `handle()`'s own body is now wrapped in the same
fail-closed net as evaluation, denying with the exception's type if anything
downstream of a real match raises.
