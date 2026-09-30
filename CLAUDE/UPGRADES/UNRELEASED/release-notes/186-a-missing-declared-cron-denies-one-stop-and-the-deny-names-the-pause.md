# Callout: a missing declared cron denies one stop per chain, and the deny names the pause

**Plan**: 00470
**Audience**: operators

`cron_stop_enforcer` (and its `SubagentStop` twin) denied every stop while a declared `persistent_crons` job was missing, so a session that could not or must not create the job was denied for ever, and the deny never said how to get out. The first stop with a missing job is still denied, now with the `hooks-daemon cron-pause <job> --reason "..."` escape named in the reason. A stop that re-enters after that deny (`stop_hook_active`) is allowed and logged as a warning, matching the other one-shot Stop blocks; the next fresh stop is checked again (reported as issue #60).
