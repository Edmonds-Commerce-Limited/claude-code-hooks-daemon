# Callout: the harvester's suggested kill can no longer name a protected group

**Plan**: 00438
**Audience**: operators

`hooks-daemon harvest-background` surfaces runaway processes and prints a
ready-to-run `kill -- -<pgid>` per process group the job spans. It never kills
anything itself — which is exactly why the command it prints has to be right.

Callers can declare groups off-limits (`exclude_pgids`); the only shipped caller
passes the harvester's own group, so that it cannot recommend killing the thing
producing the report. That exclusion was honoured when deciding what counts as a
breach, but not when building the group list for the kill command: a breaching
process with a descendant inside the excluded group would have that group
rendered into the suggestion.

Both halves now use the same excluded set. A tree whose every group is excluded
falls back to the breaching process's own group, which is always safe — a
process in an excluded group never becomes a breach in the first place.

The reported `tree_pcpu` is deliberately still unfiltered: it answers "is this
job actually doing anything", and work running in an excluded group is still
work.
