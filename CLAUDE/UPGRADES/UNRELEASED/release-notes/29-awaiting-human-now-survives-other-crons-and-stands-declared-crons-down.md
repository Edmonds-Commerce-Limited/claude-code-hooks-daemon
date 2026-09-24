# Callout: `[awaiting-human]` now survives your other crons, and stands declared crons down too

**Plan**: 00388
**Audience**: client projects

In a session running more than one cron, the `[awaiting-human]` marker never
suppressed anything: every tick except the failsafe one was read as the owner
replying, and it wiped both the marker and the failsafe cadence backoff. Every
cron prompt the daemon supplies now starts with a sentinel line:
`[tick:failsafe]`, `[tick:watchdog]` or `[tick:job:<id>]`. A prompt carrying
one is never mistaken for you. For this to work, `background_process_tracker`
now hands you its watchdog prompt to paste verbatim. `persistent_cron_assertor`
and the `cron_stop_enforcer` block message render each declared job's prompt
with its sentinel. While the marker is live, a declared `persistent_crons` job's
tick is now also dropped at zero token cost (`R-DECLARED-CRON-SUPPRESSED`); the
watchdog's tick is always delivered. A real message from you still clears the
marker and resumes every cron. Crons that already exist in a running session
keep their old prompts: they still match their declarations, but they still
read as the owner until the next session re-creates them. Paste daemon-supplied
cron prompts verbatim, first line included.
