# Callout: the dedupe scout's plan count is now checked from outside the agent

**Plan**: 00434
**Audience**: everyone

`hooks-daemon-plan-dedupe-scout` reports `Checked N live plans.` so a caller can
tell a real check from a guess. Until now the only thing N could be reconciled
against was the scout's own enumeration — which is no check at all when the
enumeration is what went wrong. Measured on this agent across real dispatches:
34, then 32, then 17 plans reported for the same unchanged tree of 34.

`mkplan.bash` now prints the number of plan folders in the plan root beside the
reminder to dispatch the scout, and says what to do when the report disagrees:
re-dispatch rather than act on the verdict. The number comes from the
filesystem, not from the agent, which is the whole point.

The agent itself is v1.2.0 and is redeployed on upgrade. It now treats a
caller-stated count as the one that settles a mismatch, and its archived-plan
step is written in terms of the Grep and Glob tools it actually has — it had
been instructed to run a `grep -ril` shell command while its frontmatter
declares `Read, Glob, Grep` and no Bash, in service of a section its own
contract makes compulsory. A local copy you have customised is untouched, as
always.

A test now fails when any shipped agent's instructions carry a shell fence its
frontmatter does not declare `Bash` for, so the next one cannot ship quietly.
