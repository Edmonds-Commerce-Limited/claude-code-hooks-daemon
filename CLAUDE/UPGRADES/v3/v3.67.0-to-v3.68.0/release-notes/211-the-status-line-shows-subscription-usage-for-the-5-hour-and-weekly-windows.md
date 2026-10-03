# Callout: the status line shows subscription usage for the 5-hour and weekly windows

**Plan**: 00479
**Audience**: operators

Claude Code sends `rate_limits` on the status payload, and nothing read it until now. The new `usage_indicator` segment renders it compactly as `📈 5h10%|7d5%`: one chip per window, its background coloured by that window's usage, green below 60%, yellow from 60%, orange from 80% and red from 90%. Every window shows its percentage; below 60% the label and number run together. From 60% a window is spaced out and adds the time to its reset, as in `📈 5h 67% 3h 20m|7d5%`, and percentages round down. The segment is hidden when there is no usage data, as on an API-key session or before the first response, and a window past its reset is dropped.

On a host whose `hosts:` entry sets a usage ceiling, the segment ends with `⛔ 80%` (`⛔ 5h 80% 7d 95%` when the two windows have different limits). It is absent when no ceiling applies.

The daemon now keeps the latest reading: one account-wide snapshot in memory, mirrored to `usage-snapshot.json` in the daemon's untracked directory, so a restart does not lose it. Other handlers read it with `latest_usage()`. The segment is on by default; the thresholds are the options `warn_pct`, `high_pct` and `critical_pct`, and `handlers.status_line.usage_indicator.enabled: false` removes it.
