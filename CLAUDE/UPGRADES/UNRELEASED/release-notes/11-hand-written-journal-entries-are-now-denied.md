# Callout: hand-written plan journal entries are now denied

**Plan**: 00461
**Audience**: client projects

A plan `JOURNAL/` entry must now be appended with
`mkplan.bash --journal <plan-number> <category> <body-file>`. The new
`plan_journal_guard` handler denies an `Edit`/`Write` that adds an entry or
creates a day-file, and a Bash command that writes into one (a redirect,
`tee`, a heredoc, a copy, an in-place editor, an interpreter one-liner). The
deny prints the exact command for that plan. The reason is the clock:
`--journal` stamps the real UTC time, while hand-typed stamps have landed 40
minutes in the future, and an append-only journal cannot correct one until
the clock passes it. The new two-step habit is to write the entry body to
`untracked/scratch/` and then run the command. Update any agent briefs that
say "append with Edit and `date -u`". `mkplan.bash --help` now documents
`--journal`, and a day-file that `--journal` opens no longer starts with a
spurious "plan scaffolded" entry. The guard is active only where the tool
exists: plan workflow enabled, a `mkplan.bash` that offers `--journal`,
`_JOURNAL_TEMPLATE_.md` present, and the default `JOURNAL` directory name.
Disable it with `handlers.pre_tool_use.plan_journal_guard.enabled: false`.
