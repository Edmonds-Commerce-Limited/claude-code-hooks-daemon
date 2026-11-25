# Callout: `check-config-migrations` no longer recommends handlers that have since gone

**Plan**: 00586
**Audience**: operators

`check-config-migrations` reads every release manifest between the version you upgrade from and the one you upgrade to, and suggests the new options each one added. An upgrade across many releases therefore met entries for handlers a later release retired, relocated or moved to another event, such as `plan_completion_advisor` or `task_tdd_advisor`, and recommended adding a key the daemon now rejects as unregistered. A suggestion under `handlers.<event>.<name>` is now dropped when that name is retired, relocated, or registered under a different event, and the same applies to a default-flip entry. A handler name the daemon does not recognise at all is still suggested, because it may be your own project or plugin handler.
