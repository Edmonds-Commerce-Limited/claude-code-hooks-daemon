# Callout: `journal-entry-future-dated` judges a day-file by the clock that wrote it

**Plan**: 00427
**Audience**: everyone

`journal-entry-future-dated` compared every journal entry against a naive local
clock. Once `mkplan.bash --journal` began stamping entries in UTC, that made
the check wrong on correct data for a whole class of hosts. Measured at one
instant, against the check's 30-minute tolerance:

| host zone           | entry looks ahead by | advisory fires? |
| ------------------- | -------------------- | --------------- |
| UTC                 | -1 min               | no              |
| Europe/London       | -61 min              | no              |
| America/New_York    | +239 min             | YES             |
| America/Los_Angeles | +419 min             | YES             |

The check now picks its clock from the day-file itself. A file carrying the
scaffolder's sentinel (`timestamps in this file are UTC`) is judged against
UTC; a file without one is legacy -- its times really are local -- and the
local-clock behaviour is unchanged. Nothing is migrated, and no existing
day-file is touched.

If you saw this advisory on entries that looked perfectly correct, that was
this defect, and it is gone.
