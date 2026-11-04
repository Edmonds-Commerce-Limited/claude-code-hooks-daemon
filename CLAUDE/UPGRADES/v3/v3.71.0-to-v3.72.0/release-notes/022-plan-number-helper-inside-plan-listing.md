# Callout: listing inside an existing plan folder is no longer denied as plan-number discovery

**Plan**: 00474
**Audience**: operators

`plan_number_helper` denied a read-only command as "a discovery scan for the next plan number" when it listed a path inside an existing plan, such as `ls CLAUDE/Plan/00554-x/JOURNAL/`, and the same command also carried a `grep` with a digit pattern. Nothing in such a command looks for a number.

A path inside one numbered plan folder (`NNNNN-name/…`, also under `Completed/`) now names a single plan and is ignored by the discovery rules, for the configured plan directory. Listings of the plan root that read folder names off it, such as `ls CLAUDE/Plan | sort | tail -1` or `find CLAUDE/Plan -maxdepth 1 -type d`, are still denied. The handler guidance in `CLAUDE.md` states the distinction.

Nothing to do on upgrade.
