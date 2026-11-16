# Callout: daemon.omit_permission_surface drops the PermissionRequest hook and deny rules that keep the rm prompt on in bypass sessions

**Plan**: 00474
**Audience**: client projects

Claude Code keeps its critical-path removal prompt on, even with `CLAUDE_CODE_EVEN_MORE_DANGEROUSLY_SKIP_PERMISSIONS=1`, when a `PermissionRequest` hook or a Bash, Edit or Read deny rule exists. The daemon wrote both. The new `daemon.omit_permission_surface` key (default `false`, so nothing changes unless you set it) makes the daemon register no `PermissionRequest` hook and write no `permissions.deny` rules, and removes only the entries it wrote earlier, never your own. Turning it on lowers defence in depth for sessions that are not in bypass mode.

`hooks-daemon permission-surface` prints those entries as JSON for a user-level `settings.json`, and writes nothing.

Separately, a settings merge with the switch off now appends any missing daemon deny rules to an existing `permissions.deny`, where before they returned only when the whole `permissions` key was absent. Your own rules are kept.
