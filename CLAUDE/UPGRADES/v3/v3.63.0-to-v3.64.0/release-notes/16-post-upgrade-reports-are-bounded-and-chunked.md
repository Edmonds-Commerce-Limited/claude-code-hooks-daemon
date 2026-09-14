# Callout: the post-upgrade reports are bounded, offloaded to files, and chunked for subagents

**Plan**: 00329
**Audience**: everyone

A canary upgrade across the whole v3 span showed the project agent receiving
143 KB of `upgrade.sh` stdout, of which 90 KB was `check-truth-changes` and
51 KB was `check-config-migrations`. Both commands exit 1 precisely when they
have something to say, and Claude Code delivers an exit-1 command result
head-and-tail with the middle dropped past roughly 10,000 characters, with no
file to go back to. On the full span roughly sixty of seventy-three
truth-change entries never reached the agent, and nothing in the delivered
text said so. The step was not being skimmed; it was being truncated.

Both commands now write their full text to a file under the project's
`untracked/` and print a summary bounded at 8,000 bytes, a constant that does
not grow with the number of releases crossed. `check-truth-changes` also
writes one `chunk-NN-<topic>.md` file per topic beside the report, each a
self-contained subagent brief, and step 4 of the upgrade skill now dispatches
one subagent per chunk in parallel. Chunks are built after superseded chains
are collapsed and are disjoint in the documents they touch, so parallel
subagents cannot race for a file, and each returns only the files it changed.
Every shipped truth-change entry carries a `topic` to make that real. The
exit-code contract is unchanged, `--full` restores the inline form, and
`upgrade.sh` inherits the bounded output for the copy it embeds.
