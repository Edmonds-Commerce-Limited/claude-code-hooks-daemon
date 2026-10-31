## 16:12 · decision · —

**STAND-IN RULING. This is not the owner's decision.** The stand-in cron `0f5a2d01` fired while the session was still awaiting the owner. Under that mechanism, a Fable sub-agent chose between the engineering options for Tasks 2.5 and 2.6 only. Its full ruling, including boundaries and required tests, is in `subagent-reports/261031-stand-in-ruling-fable.md`. The owner may overturn it.

- **Task 2.5, option (b).** While the daemon is down, the allow-list is widened to a fixed set of read-only diagnostics, plus `hooks-daemon diagnose` in the recovery subcommands of both `init.sh` and `cli_command.py`.
  - Allowed: Read of an in-repo regular file, and Bash `ls`, `cat`, `head -n`, `tail -n`, `git log` and `git status`, each with a fixed option set and no shell metacharacters.
  - Protected paths stay refused. A stdlib matcher checks the default globs plus a daemon-written snapshot, and fails closed when the snapshot is absent.
- **Task 2.6, option (a), N = 3.** Consecutive daemon-down stop blocks are counted by class, per session. The third block allows the stop, with a loud message and a log line. A `STOPPING BECAUSE: [awaiting-human]` stop is honoured at any count. The CI-enforced, invalid-input and needs-provision blocks stay unbounded.

**DBF-REPORT decisions 1 to 3 are not covered by this ruling.** They stay with the owner.

**Next:** build both in a worktree with red tests first, run targeted QA, then merge.
