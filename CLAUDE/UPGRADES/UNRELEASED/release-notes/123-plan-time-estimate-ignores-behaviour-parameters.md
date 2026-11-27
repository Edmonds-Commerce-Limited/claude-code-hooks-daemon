# Callout: the plan time-estimate rule passes a short parameter duration such as "cooldown of about 8 minutes"

**Plan**: 00474
**Audience**: everyone

The plan time-estimate rule (R-PLAN-TIME-ESTIMATE) flagged "a cooldown of about 8 minutes" and "needs about 8 minutes of cooldown", although they state what the code must do, not when work will be done. A second, minute or hour figure now passes when its own clause carries a parameter word (cooldown, window, interval, TTL, backoff, jitter, timeout, debounce, grace, expiry, period) and no effort word (takes, estimate, effort, ETA, deadline, work, phase, total). A day, week, month, year, sprint or person-day figure is never excused by a parameter word, and a table row or heading is never excused. Everything else blocks as before.
