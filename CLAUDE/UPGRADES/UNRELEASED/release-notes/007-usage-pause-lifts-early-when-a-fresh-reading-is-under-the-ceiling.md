# Callout: a usage pause lifts before its resume time when a fresh reading is under the ceiling

**Plan**: 00479
**Audience**: operators

A session paused on one account's usage window used to hold until that window's reset even after it moved to an account with plenty of headroom, because every resume tick before the recorded resume time was dropped unread. The resume cron's early tick (it fires every ten minutes) now reads the daemon's usage snapshot, which costs no model turn: a reading seen within the last 15 minutes that is under the ceiling lifts the pause, one that is still over on a different window silently moves the recorded resume time, and a stale or missing reading drops the tick as before. It trusts the same host-wide snapshot a held prompt already does. Behaviour at or after the resume time, the owner's `usage-pause clear` override and the tool and stop gates are unchanged. (reported as issue #132)
