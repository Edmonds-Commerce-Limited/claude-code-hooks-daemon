## 15:03 · decision · — — Task 2.1a shipped; unreadable-bus default is refuse

Task 2.1a shipped on branch plan-00636-stop-guard: `owner_wait_stop_guard` (Stop, priority 3, rule R-STOP-OWNER-WAIT-UNBUMPED), registered, enabled in the dogfood config, the example and init_config, documented in HANDLER_REFERENCE and the 0-9 priority tables, with release note 026 and v3.77.0 config-changes entries.

Design correction applied (from the coordinator): the unreadable-bus default is `options.on_unreadable_bus: refuse` (fail closed), not the fail-open written in 00630 DESIGN.md 20 and 20.1; `allow` fails open with a WARNING. DESIGN.md now carries correction pointers in both places.

OPEN design point for the coordinator and owner: on pingbus v1 the adapter cannot read the notify flag or m.thread, so `refuse` refuses every waiting stop on a coordinator seat once until a v2 adapter can read both. `allow` is the escape hatch. Recorded in PLAN.md under Task 2.1a.

Task 2.1 stays open: the AskUserQuestion deny on coordinator seats was out of 2.1a's scope.
