# Callout: a truncated-to-nothing cron prompt no longer asserts every job

**Plan**: 00436
**Audience**: client projects

If your project declares `persistent_crons`, the Stop-event enforcement
compares each declared job against what `session_crons` actually delivers. The
delivered prompt is capped and marked as truncated, so an over-cap declaration
can only be compared by prefix — and prefix matching was deliberately limited
to deliveries that really were cut short, because otherwise a one-line cron
would match a ten-line declaration.

The empty prefix slipped through that limit. A delivered prompt consisting of
nothing but the marker (`... [+1200 chars]`) strips to an empty string, is
correctly identified as truncated, and every declaration on the same schedule
starts with it — so any declared job matched, and a cron that was never created
was reported as live.

That is the expensive direction of failure: a session running with no recovery
cron and nothing saying so, rather than a nag you can see. Prefix matching now
requires a non-empty prefix. Real truncated deliveries still match exactly as
before.
