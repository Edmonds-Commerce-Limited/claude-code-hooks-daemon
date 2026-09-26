# Callout: a slow `secret_file_guard` or `enforce_llm_qa` scan is no longer a fail-open

**Plan**: 00466
**Audience**: client projects

A verification review of Plan 00466's own prior fixes found that the timing
fix itself, and two of the new checks it added, each independently
reintroduced the SAME defect they were meant to close: a scan slow enough to
exceed the client's PreToolUse budget is an ALLOW for the whole chain, so a
slow SAFETY-guard scan is a bypass, not a nuisance. A `{a,b}`-style brace
alternation could still blow up exponentially before any deadline check ever
ran (the deadline was consulted only after the full token list — including
every brace spelling — had already been built), and a `/**/`-style
filesystem glob could walk an unbounded number of directories, because a cap
on matches FOUND never trips when the final component matches nothing and
the walk simply runs to completion. `enforce_llm_qa` carried an independent
copy of both defects, plus its own catastrophically-backtracking word-finder
regex.

Both guards now share one bounded expansion primitive
(`utils/shell_expansion`): a brace expander built as a lazy generator capped
via `itertools.islice`, and a filesystem walker that counts directory
entries VISITED rather than matches found, refusing outright to walk a
broad pattern rooted at the filesystem root. Past either cap, the primitive
raises rather than silently degrading to a smaller-but-still-eager
computation — a signal both guards treat as "cannot rule out a match",
denying rather than allowing. `secret_file_guard`'s own token-list
construction is now itself lazy, so its existing per-token deadline check
bounds brace expansion too, not just the ordinary tokens built before it.
