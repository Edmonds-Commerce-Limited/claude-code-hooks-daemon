# Callout: SessionEnd hooks can tell a supervisor restart from a real exit

**Plan**: 00539
**Audience**: operators

When a supervisor plugin asks for a restart, the ccy supervisor now writes a private `restart-pending.json` record before it types `/exit`, and removes it once the child has exited or the request is abandoned. The child gets the record's path in `CCY_SUPERVISOR_RESTART_PENDING`. A SessionEnd hook can now skip announcing a departure that is really a restart. It treats its session as restarting only when the file exists, names the hook's own session id, and its `deadline` has not passed. The full reader contract is in `CLAUDE/development/CcySupervisor.md`, "Exit for restart". A restart held because focus may be on a sub-agent writes no record, and the change starts working at the next ccy relaunch. (reported as issue #127)
