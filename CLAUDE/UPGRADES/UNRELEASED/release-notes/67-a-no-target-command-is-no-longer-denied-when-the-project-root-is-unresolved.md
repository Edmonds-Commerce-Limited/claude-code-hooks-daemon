# Callout: a no-target command is no longer denied when the project root is unresolved

**Plan**: 00466
**Audience**: operators

`project_containment.matches()` resolved `ProjectContext.project_root()`
before checking whether the command named any write target at all. If the
root could not be resolved -- `ProjectContext` not yet initialised -- that
raised ahead of the check, and the surrounding fail-closed handling denied
EVERY command, including one that writes nothing. `_offending_targets()` now
returns early when `_named_targets()` is empty, before the root is ever
resolved, so a command naming no write target is judged on that fact alone.
A command that does name a target is unaffected: the root is still resolved,
and the handler still fails closed if that raises.
