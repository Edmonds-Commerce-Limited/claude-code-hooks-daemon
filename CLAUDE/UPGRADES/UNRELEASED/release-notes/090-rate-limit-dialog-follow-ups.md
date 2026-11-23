# Callout: rate-limit dialog answerer: held-Enter take-back, retried resume, readable armed state

**Plan**: 00523
**Audience**: client projects

Follow-ups to the ccy supervisor's rate-limit dialog answerer. An Enter the focus model holds is now taken back like a vetoed one, and Enters taken back are capped at two per reset window. A resume `continue` vetoed because of a redraw is retried instead of the window being abandoned. A taken-over or key-capped state is no longer swept while its dialog is open. The supervisor now says whether the answerer is `ARMED`, `dry-run` or `OFF` (`CCY_RATE_LIMIT_DIALOG`) in the startup banner and as the first decision-log line. The worker half reloads by itself; the held-Enter take-back and the banner line need the next ccy relaunch.
