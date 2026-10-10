# Callout: the usage-pause owner override is now visible to the session and the status line

**Plan**: 00479
**Audience**: operators

`bin/hooks-daemon usage-pause clear` records an override that suppresses the usage pause until the latest reset among the windows over the ceiling. Until now it was silent: usage could climb from the ceiling to the account's hard limit with nothing telling the model or the person watching. Two signals now show it, and neither changes any decision (the override still suppresses every pause).

While an override is in force and at least one usage window is over its ceiling, each prompt carries a `USAGE CEILING SUPPRESSED` line naming each over-ceiling window, its percentage, the ceiling and the override's end time in UTC (with the date when it is not today). The status line's usage segment shows `override until HH:MM` (local time, with the month and day when it is not today) whenever the override is valid: red while a window is over the ceiling, yellow otherwise. Missing or stale usage data, or an unreadable override marker, says nothing. No configuration change is needed.
