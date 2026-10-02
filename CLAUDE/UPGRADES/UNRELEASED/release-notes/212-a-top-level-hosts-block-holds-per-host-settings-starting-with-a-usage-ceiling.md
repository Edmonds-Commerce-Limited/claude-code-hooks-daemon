# Callout: a top-level `hosts:` block holds per-host settings, starting with a usage ceiling

**Plan**: 00479
**Audience**: operators

The config gains an optional top-level `hosts:` block. Each key is a label; an optional `pattern` is a case-sensitive `fnmatch` glob matched against the session's effective hostname (`HOOKS_DAEMON_HOSTNAME`, then `CCY_HOST_HOSTNAME`, then the system hostname), and without one the label is the exact hostname. The first per-host setting is `usage_ceiling`: `max_used_percent` (greater than 0, at most 100) applies to both the 5-hour and 7-day windows, with optional `five_hour` and `seven_day` overrides. When several entries match, the lowest limit wins per window. Out-of-range percentages, a blank `pattern` and unknown keys are rejected at config load with a message naming the field. Nothing enforces a ceiling yet: this release adds the config model and the resolver (`utils.host_usage_ceiling.resolve_host_usage_ceiling`) the later usage-pause handlers will call, so a project that declares nothing sees no change.
