# Callout: `verdicts.jsonl` now records the rule ID of a handler's decision

**Plan**: 00474
**Audience**: operators

The `rule` field of each line in `verdicts.jsonl` was null for most handlers, including the usage-pause gate and the failsafe-cron suppressors, so a dropped tick (`R-FAILSAFE-CRON-SUPPRESSED`, `R-DECLARED-CRON-SUPPRESSED`, `R-FAILSAFE-CRON-BACKED-OFF`, `R-USAGE-PAUSE-PROMPT`) could not be counted from the log.

The field now carries the rule ID the handler's result names. A deny, ask or defer that names none takes the ID of the handler's rule when the handler declares exactly one. A handler that declares several rules and names none still records null, as does an allow.

`hooks-daemon verdicts` reads the same field and is otherwise unchanged. Lines written before the upgrade keep their null.

Nothing to do on upgrade.
