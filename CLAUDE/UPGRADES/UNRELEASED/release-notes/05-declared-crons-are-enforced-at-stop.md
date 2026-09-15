# Callout: a declared persistent cron is now enforced, not just announced

**Plan**: 00416
**Audience**: everyone

Claude Code crons do not survive a session, so a project that needs recurring
work declares it under `persistent_crons` and the SessionStart advisory asks
the agent to reconcile with `CronList`. That advisory was routinely read and
routinely ignored, and nothing noticed — a project could go a whole session
believing its hourly job was running when it had never been created.

The daemon could not check at SessionStart because `session_crons` is not
delivered to that event. It IS delivered to `Stop` and `SubagentStop`, and two
new handlers use it: `cron_stop_enforcer` and `cron_subagent_stop_enforcer`
compare what the project declared against what the session actually has, and
block the stop naming the exact `CronCreate` — id, schedule and full prompt —
for anything missing.

**An absent `session_crons` field means "no information", never "no crons
exist", and can never block.** The field is conditional in the hook contract,
so treating absence as emptiness would block every session on a Claude Code
build that does not send it.

Matching is on schedule plus prompt, never on `id` — nothing guarantees a
session's own `CronCreate` echoes a declared id back. The prompt comparison
ignores layout, and that is load-bearing rather than lenient: a declared prompt
reaches `CronCreate` only by being rendered into an advisory and retyped by an
agent, and that round trip re-flows it. Measured on a real payload, this
project's own declaration arrived four characters longer with blank lines
inserted between paragraphs, and the three crons in one session disagreed with
each other about it. Comparison is therefore on the words, with blank lines and
line-trailing spaces normalised away; truncation at the 1000-character wire cap
is handled on top of that.

Both handlers are silent unless `persistent_crons` is enabled with at least one
declared job, so a project that declares no crons sees no change at all.
