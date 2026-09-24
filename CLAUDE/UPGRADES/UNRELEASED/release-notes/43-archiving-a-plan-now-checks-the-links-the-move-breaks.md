# Callout: archiving a plan now checks the links the move breaks

**Plan**: 00408
**Audience**: client projects

Archiving a plan moves it one directory deeper, so every relative link in it
shifts by a level, and until now nothing looked. Archived plans are exempt
from the link sweeps on purpose, because an archived plan is a record. The new
plan-QA commit check `archival-links-resolve` runs only on the archival
commit, the one commit still writing that record. It blocks a link the move
broke and names the repoint that restores it. `JOURNAL/` day-files are
skipped, because they are append-only.

Four smaller fixes ship in the same plan:

- a `bash -c "mkdir <plan-dir>/NNNNN-x"` or a quoted plan-folder path is now
  redirected to `mkplan.bash` like the plain spelling;
- `env VAR=1 ./job & wait $!` no longer draws a wrapper-pid advisory, because
  GNU `env` execs in place (`env sh -c '…'` still does);
- the post-merge docs report no longer builds the docs index from nothing
  inside a hook;
- `hooks-daemon restart` no longer ends with a traceback if unlocking the QA
  lock fails, and still warns when a QA run holds that lock but its pid
  cannot be read.
