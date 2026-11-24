# Task 2.5 report: s7 board and B5 liveness (advise-only part)

Spec on disk: PLAN.md Task 2.5 is one line; the Goals line says the board comes "from `teamchat status` and fedora-desktop Plan 00251, never from teamchat's files". 00630 DESIGN.md has the B5 row (section 7: "advisory from `teamchat status` or fedora-desktop Plan 00251; Q6"), section 3 (`teamchat status` as a signal) and the s7 row (section 19). Nothing on disk records the `teamchat status` output contract, no teamchat binary is in this checkout (`TEAMCHAT_KIT` unset), and the fedora-desktop vet says `status.json` covers only this session's own teams. So only the non-parsing subset was built.

Built:

- `handlers/session_start/coordinator_board.py`: SessionStart, priority 48 (shares the slot with `work_queue_rebrief`; both re-brief a coordinator on a new, resumed or compacted session). On a seat `coordinator_advisory_armed` arms, it adds one fixed note: the board is `teamchat status`, run by the seat; teamchat's files (`status.json`, run directory, seat store) are not it; a seat the board does not show, or whose state cannot be read, is unknown, not down, so ask it on the bus before reassigning. It names no restart.
- The handler runs no teamchat command, opens no teamchat file and relays no status text, so no peer-controlled label reaches the context. A raising resolver counts as armed (the note only adds text). No options.
- Not on Stop: Task 2.4 found that Stop ALLOW context makes Claude Code continue.
- No resident CLAUDE.md guidance (T4 row in the guidance coverage table): the note reaches the coordinator each session, and resident text would reach every non-team project.
- Paperwork: HandlerID, Priority, session_start `__init__`, init_config, both yaml files, HANDLER_REFERENCE, config-changes v3.77.0 under `added:`, release note 099, one acceptance test (silent without a team seat), PLAN.md tick and Success Criteria line, `.claude/HOOKS-DAEMON.md` regenerated.

Open, not built (owner or fedora-desktop):

- The `teamchat status` output contract, and whether it covers other seats or only this session's teams. Until it is on disk, a reader would invent its format.
- What fedora-desktop Plan 00251 supplies.
- Q6: advisory only, or a supervisor action for a down seat.
- Startup timing: DESIGN section 3 says `whoami` exits 69 "before the seat link". If the link is not there at a `startup` SessionStart, the note is silent on startup and appears only on resume and compact. This is unverified here: there is no binary.

Tests: `tests/unit/handlers/session_start/test_coordinator_board.py`, red first (import error), then green. Covered: coordinator, coordinator duty, unknown role and unresolved probe are all armed; declared worker, no team and sub-agent are untouched; RuntimeError, RecursionError and ValueError from the resolver.

A second, real-dispatch class covers the handler as `register_all` builds it (`_team_seat` injected), with the real `SeatContextResolver` and `whoami` parser on a payload carrying the stamped `teamchat_runtime`/`teamchat_kit` fields. Only the subprocess is faked, with `tests/support/teamchat.py` outputs. Results: a coordinator gets the note; a worker or exit 69 gets nothing; with no signals nothing runs. Only `whoami` is ever run, and no file at all is opened (invariant 5, asserted as zero `open` calls, not a filename check). A sub-agent never runs the probe: the main-thread check comes before it (added after review, red first). The server stamps the seat fields on every event, SessionStart included (`server._stamp_teamchat_signals`).

Review fix commit: the sub-agent probe ordering, the real-dispatch tests, and this open item.
