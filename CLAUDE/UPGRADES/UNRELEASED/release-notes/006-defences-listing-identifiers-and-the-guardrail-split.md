# Callout: the defences listing carries defect classes, and more denials print an identifier

**Plan**: 00484
**Audience**: everyone

`hooks-daemon defences --json` now lists only the content and commit gates, which are the Defence Before Fix Defences, with a `defect_class` on every row, and `explain-rule` and `explain-handler` say whether a rule is a Defence or a guardrail instead of calling every rule a defence. Five more handlers (`dispatch_declaration` in strict mode, `subagent_report_size_blocker`, `subagent_report_path_verifier`, `cron_stop_enforcer`, `cron_subagent_stop_enforcer`) print a `BLOCKED [R-...]` identifier, `explain-rule` resolves the plan-QA and docs-QA check IDs such as `plan-doc-size`, and `explain-rule --list` ends with a line pointing at `explain-rule <ID>`, so a script that reads that listing as tab-separated rows should skip its last line. The generated CLAUDE.md block also ends each promoted handler's section with an `IDs:` line.
