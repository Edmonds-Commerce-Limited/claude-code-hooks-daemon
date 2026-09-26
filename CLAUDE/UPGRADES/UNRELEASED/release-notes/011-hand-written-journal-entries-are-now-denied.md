# Callout: hand-written plan journal entries are now denied

**Plan**: 00461
**Audience**: client projects

A plan `JOURNAL/` entry must now be appended with
`mkplan.bash --journal <plan-number> <category> <body-file>`. The new
`plan_journal_guard` handler denies, in every checkout including git worktrees,
an `Edit`/`Write` that adds any line to a day-file or creates one, and a Bash
command that writes into one by any route: a redirect, `tee`, a heredoc, a
copy or link, an in-place editor, a patch, an interpreter program (inline, on
a heredoc, or behind a wrapper such as `timeout` or `uv run`), or a file name
the shell builds at run time. The deny prints the exact command for that plan,
with absolute paths into that checkout. The reason is the clock: `--journal`
stamps the real UTC time, while hand-typed stamps have landed 40 minutes in
the future, and an append-only journal cannot correct one until the clock
passes it. The new two-step habit is to write the entry body to a fresh file
under `untracked/scratch/` and then run the command. Update any agent briefs
that say "append with Edit and `date -u`". The journal QA remediations now name
the same command. `mkplan.bash --help` now documents `--journal`, and a
day-file that `--journal` opens no longer starts with a spurious "plan
scaffolded" entry. The guard is active only where the tool exists: plan
workflow and journalling enabled, the default `JOURNAL` directory name, and a
plan directory holding `_JOURNAL_TEMPLATE_.md` and a `mkplan.bash` that offers
`--journal`. Otherwise it is inert and logs why, once. Disable it with
`handlers.pre_tool_use.plan_journal_guard.enabled: false`.
