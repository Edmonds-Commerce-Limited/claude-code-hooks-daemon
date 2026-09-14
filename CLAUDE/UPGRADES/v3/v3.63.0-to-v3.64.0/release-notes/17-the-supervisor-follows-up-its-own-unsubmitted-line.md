# Callout: the supervisor follows up a line it typed but did not submit

**Plan**: 00366
**Audience**: operators

The ccy supervisor pastes its injections (`/goal`, `continue`, `/effort`)
into the Claude Code input box and presses Enter. When that Enter does not
submit the line, which happened to an armed `/goal` typed while the agent was
mid-turn, the supervisor had no record it had typed anything: its own text
is kept out of the input-box model so a human's half-typed line is never
typed over. The `/goal` sat in the box for eight hours until a human pressed
Enter, and `decision.log` showed a successful injection followed by silence.

A submitted injection is now remembered as the supervisor's own line. At the
next lull (human idle, no human text in the box, child quiet) it presses
Enter for it, at most twice, fifteen seconds apart, and logs each press as
`own line may still be unsubmitted ... -> pressing [enter]`. A human Enter
clears the record without a keystroke, as does the session going busy after
a follow-up. While the line is pending, the goal, goal-clear and
standing-authorisation families wait rather than paste on top of it, and
say so in the log.

The goal injection cap is also a rolling one-hour budget now, not five per
process lifetime: a session that lived for thirteen hours had met the old
cap and was silently refusing every later plan flip.

The change is worker-side only, so a running supervised session picks it up
by the normal worker hot-reload with no restart.
