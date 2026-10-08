# Callout: `hooks-daemon defences --json` lists every active defence

**Plan**: 00484
**Audience**: everyone

A new `hooks-daemon defences` command lists the defences that are switched on in your config, so a Defence Before Fix tool can read them without running anything. Each record carries the rule ID, the handler, its event and priority, the terse statement of what is blocked, the command that prints the full documentation (`explain-rule` or `explain-handler`) and the command that exercises it (`hooks-daemon probe <event>`). A blocking handler that declares no rule is listed with a null `rule_id`. The `defect_class` field is always null for now, because nothing maps a rule to a `CLAUDE/Security/` category. Pass `--json` for machine-readable output; the default is one tab-separated line per record. It reads the same config and handler data as `generate-docs` and `explain-rule`, so it does not change what any handler does.
