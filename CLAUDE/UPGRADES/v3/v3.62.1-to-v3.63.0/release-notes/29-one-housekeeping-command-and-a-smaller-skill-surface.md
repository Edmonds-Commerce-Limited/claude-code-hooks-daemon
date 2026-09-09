# Callout: one housekeeping command, and a smaller skill surface

**Plan**: 00330
**Audience**: operators

`/hooks-daemon housekeeping` runs the whole housekeeping pass in one go —
plan QA, docs QA, the daemon's own audits, the formatters, and `optimise` to
close — with report-only steps first, mutating steps after, and `optimise`
last because it restarts the daemon; only `format-markdown` and
`regenerate-docs` act on their own, every other mutating step is held until
you name it on `--apply <step>`, and each step's sub-agent reports what it
changed rather than what it read. The skill now routes only what a human
types (`install`, `upgrade`, `optimise`, `housekeeping`, `restart`, `health`,
`bug-report`, `report`); `logs`, `status`, `handlers`, `config-validate`,
`check`, `regen-docs`, `rule-explain`, `dev-handlers` and `release-notes` are
listed in the skill as CLI capabilities with the exact `bin/hooks-daemon`
verb, and block messages now point at `bin/hooks-daemon explain-rule <ID>`.
