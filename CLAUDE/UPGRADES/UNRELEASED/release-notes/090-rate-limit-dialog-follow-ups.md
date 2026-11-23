# Callout: rate-limit dialog answerer: held-Enter take-back, retried resume, readable armed state

**Plan**: 00523
**Audience**: client projects

Follow-ups to the ccy supervisor's rate-limit dialog answerer. An Enter the focus model holds is now taken back like a vetoed one, and Enters taken back are capped at two per reset window; when the cap trips the status line says the dialog is left to the human. A resume `continue` vetoed because of a redraw is retried instead of the window being abandoned. A taken-over or key-capped state is no longer swept while its dialog is open and its Claude process still runs. The supervisor now says whether the answerer is `ARMED`, `dry-run`, `INERT` (no `hooks-screen` binary found) or `OFF` (`CCY_RATE_LIMIT_DIALOG`) in the startup banner and as the second decision-log line (after `supervisor active`). Only the state-file sweep rule reloads with the worker. The held-Enter and held-resume take-backs, the retried resume, the take-back cap and its status-line notice, and the armed-status line all depend on the host, which does not hot-reload: they take effect at the next ccy relaunch.
