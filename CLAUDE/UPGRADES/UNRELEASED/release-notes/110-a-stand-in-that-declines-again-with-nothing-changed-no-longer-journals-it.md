# Callout: a stand-in that declines again with nothing changed no longer journals it, and repeats back off

**Plan**: 00639
**Audience**: operators

The one-off `[tick:stand-in]` cron told its sub-agent to record every choice or decline in the plan journal, with no exception for a decline that repeated unchanged. A session left awaiting a human therefore wrote one journal entry per tick, and one project collected about 37 such entries in five days. Two changes follow. The stand-in directive now says a repeat decline with the question unchanged since the last journalled one gets no new entry, while a ruling that changes anything is always journalled. And any stop that declares `[awaiting-human]` with no human message since the previous such stop now schedules its stand-in twice as far out as the gap since that previous stop (3h, 6h, 12h, never past 23h, and never below `auto_continue_stop`'s `stand_in_delay_hours`). The daemon cannot tell a repeated question from a new one, so a new question raised after the stand-in let work continue also waits longer than the base delay; a human message ends the wait, and the next stop starts again at the configured delay.
