# Callout: a duration that states a behaviour parameter is no longer a plan time estimate

**Plan**: 00474
**Audience**: everyone

The plan time-estimate rule (R-PLAN-TIME-ESTIMATE) flagged a duration such as "needs about 8 minutes" in a sentence like "a session switches sign-in after a cooldown that needs about 8 minutes", although it states what the code must do, not when work will be done. The rule now reads the clause around each duration: a duration whose clause carries a parameter word (timeout, cooldown, window, interval, TTL, delay, limit, expiry, retry, backoff, period, debounce, grace, heartbeat, jitter, poll) and no effort or schedule word (takes, estimate, effort, ETA, deadline, sprint, days of work) passes. "This will take 3 days", "estimated effort: 2 weeks" and dated completion targets still block.
