# Callout: an unattended project still lets a question through when a human has just typed

**Plan**: 00474
**Audience**: operators

A project running `ask_user_question_blocker` with `mode: unattended` denied
every `AskUserQuestion`, including one asked straight after the owner typed a
message into the session ("human here - take me through decisions one at a
time"). The declared mode describes the project, and nothing on the hook event
says whether a person is reading right now, so the handler never looked.

The handler now reads the tail of the session transcript and, when a genuine
human prompt arrived in this session within `human_presence_minutes` (default
30), treats the session as attended for that window: the question is judged by
the ordinary rules (every question prefixed `ASKING BECAUSE:`), not denied as
unattended. Cron ticks (`[tick:...]`), `ccy-supervisor` lines,
teammate messages, task notifications and another session's prompts do not
count, using the same classification as the skill-opportunity scan plus the
transcript's own `origin.kind`. Thirty minutes rides out a meeting without
leaving an owner who has walked away treated as present overnight; set
`human_presence_minutes: 0` to keep unattended absolute. The unattended deny now
says what it judged: no genuine human prompt in the last N minutes. Strict and
advisory modes are unchanged.
