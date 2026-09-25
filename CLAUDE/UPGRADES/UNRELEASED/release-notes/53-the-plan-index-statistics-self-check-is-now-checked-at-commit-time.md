# Callout: the plan index's statistics self-check is now checked at commit time

**Plan**: 00466
**Audience**: everyone

The `plan-stats-arithmetic` rule is now a plan QA check. It verifies that the
closing self-check of the plan index's reconciliation bullet (`N + M = T. ✅`)
agrees with the figures stated above it. The commit gate blocks a commit that
stages the index with a new disagreement, and the message names the line to
fix. `plan-qa --sweep` reports it, and an edit to the index gets it as an
advisory only, because updating those figures takes more than one edit. It used
to run only in full QA, so a wrong closing line could reach main with every
fast gate green. An index without the bullet, which is every client project's
default, reports nothing.
