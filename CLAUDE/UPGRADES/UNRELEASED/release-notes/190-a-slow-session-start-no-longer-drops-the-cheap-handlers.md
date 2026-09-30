# Callout: a slow SessionStart no longer drops the cheap handlers

**Plan**: 00474
**Audience**: operators

A SessionStart that overran its dispatch budget used to reply only "Chain
skipped: exceeded its 20.00s dispatch budget" and lose every handler, including
`persistent_cron_assertor`, so a session started on a loaded host was never told
which declared crons to create. Measured on a host with a load average of about
33, no single handler overran: the handlers that walk the repository
(`gitignore_safety_checker`, `secret_file_hygiene_checker`, `docs_qa_sweep`,
`plan_qa_sweep`, `git_upstream_checker`) took about 30 s of a 33 s chain between
them, while the assertor needed half a second.

Two changes. A new handler tag, `slow-sweep`, orders a handler after every
untagged handler in its chain whatever its priority, and those six handlers
(the five above plus `reference_repo_sweep`) now carry it, so the cheap ones run
first. And when a chain with no SAFETY+BLOCKING handler overruns its budget, the
output of every handler that had already finished is kept, with a line saying
the chain was cut short, instead of being thrown away. A chain holding a
SAFETY+BLOCKING handler still fails closed, as before. A project handler can
carry `slow-sweep` in its own `tags` to be ordered the same way. The dispatch
budget itself is unchanged.
