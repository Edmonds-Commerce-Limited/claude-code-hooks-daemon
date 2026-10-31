## 21:10 · decision · —

**This is the stand-in's ruling, not the owner's.** The stand-in cron `f1aef06e` fired while the session was still awaiting the owner. A Fable sub-agent then chose among the engineering options for Task 2.8. The full ruling is in `subagent-reports/261031-stand-in-ruling-2-fable.md`, and the owner may overturn it.

- **S2: option (a).** The SubagentStop counter is keyed by the payload's cleaned `agent_id`, falling back to the shared key. The reset removes every per-agent file.
- **S5: option (a).** Every blocking Stop/SubagentStop class counts toward the N=3 bound, except `invalid_hook_input` and `socket_timeout`. The test must use a connection reset.
- **S1: option (a), the union variant.** When the config file is strictly newer than the snapshot, or its stat fails, the judge keeps enforcing the old globs and also applies the `.claude/` lockdown. The deny reason names the staleness.
- **S4: option (a).** `git status` leaves the daemon-down allow-list, because it can write the index and run fsmonitor.

The ruling does not cover DBF-REPORT decisions 1–3, the question of client-install daemon logs, or Plan 00556. Those stay with the owner.

**Next:** build in a worktree with red tests first, run targeted QA, then merge.
