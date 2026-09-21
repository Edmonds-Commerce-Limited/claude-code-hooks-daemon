# Callout: the documented priority bands now match the shipped constants

**Plan**: 00435
**Audience**: handler authors

The priority band table said two things that were no longer true, on every
surface that carries it — the agent guide, `CONTRIBUTING.md` and the
configuration guide, which quote it verbatim and so all said the same wrong
thing together.

**The `0-9` band is not empty.** It said "no built-in handlers ship here"; three
do, and they are there deliberately. A terminal Stop handler that matches an
ordinary stop ends the chain, so anything registered after it never runs on the
common path — `cron_stop_enforcer`, `cron_subagent_stop_enforcer` and
`teammate_reap_advisor` sit below it for that reason. An author following the
old table would put a new Stop handler in the Safety band at 10+ and get one
that silently never fires. The row now names them and says why.

**The Advisory band is `56-73`, not `56-69`.** `PriorityRange.ADVISORY_MAX` has
been 73 since the session-actions directive shipped; four handlers were living
in a range no documented band covered.

A test now compares the table against `PriorityRange` and checks that every
shipped handler priority falls inside a documented band, so the guidance cannot
drift from the code again without failing. The `hooks-daemon` skill's own
paraphrase (which stated a third value, `56-65`) agrees with the table now.
