# Callout: a wait loop can no longer watch for itself

**Plan**: 00363
**Audience**: everyone

The Bash tool runs every command through `bash -c "<command>"`, so a
`pgrep -f "my-job"` always finds at least one process: the shell asking the
question. A reported waiter spent an entire night sleeping on exactly that,
and two hand-run checks with the same pattern each confirmed the wrong
answer. The new `self_matching_process_probe` handler denies `pgrep -f`,
`pkill -f` and `ps … | grep` whose literal pattern is in the calling
command's own argv -- wherever they appear, because an advisory inside a
background waiter is read by nobody -- and the block message carries the
rewrite for the pattern you actually typed. Two advisories sit beside it: an
uncapped `while`/`until` wait on a process, and a pattern built by expansion
that the daemon cannot read. Waiting on an artefact
(`until grep -q "PLAY RECAP" run.log; do sleep 10; done`) is never flagged --
that is the shape the block message asks for.
