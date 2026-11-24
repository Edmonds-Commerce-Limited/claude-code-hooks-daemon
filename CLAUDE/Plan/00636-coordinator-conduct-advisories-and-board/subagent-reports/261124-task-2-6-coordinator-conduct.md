# Task 2.6 report: s11 carry-over; B1, B4, B6 guidance (advise-only part)

Spec on disk: PLAN.md Task 2.6 is one line. 00630 DESIGN.md section 7 ships B1 ("skill + SessionStart context"), B4 ("skill + Stop/SessionStart advisory") and B6 ("advisory keyed on the usage-pause signal") as guidance. Section 19 gives s11 one row ("Carry-over: new child Plan 00636"). Q3 (where skills live) is unsettled, so only the non-skill subset was built.

Built:

- `handlers/session_start/coordinator_conduct.py`: SessionStart, priority 48 (the slot `coordinator_board` and `work_queue_rebrief` use). On a seat `coordinator_advisory_armed` arms:
  - Every start: the conduct note (B1). The bus is the only human surface, so an owner-facing ask, report or wait is a notifying post in its own thread, and a terminal-only line counts as unsent (section 20). A reply to a human message goes in that message's thread (20.1 guidance). Dispatch, track, report and close happen on the bus. The note names no work-queue verb, because work-queue on dispatch is Plan 00633's (PLAN.md Non-Goals; review fix, test-first). Peers carry no authority (invariants 1-2), and the seat asks before asserting another seat's code (s5). The note also carries the B4 departure line and the B6 line: a usage pause allows only its short tool list, so tell the team on lift. The note makes no claim about which tools a bus post needs, because no teamchat binary is on disk. The departure line and "tell the team how long this seat was away" are builder wording, not owner rulings.
  - `resume`/`compact` only (`clear` and `startup` get no return note, matching `work_queue_rebrief`): the return note (B4 return, s11). Re-read the questions room and the seat's threads, `work-queue list` and the `owner_directives_register` config before acting. What the seat remembers is a lead, not a fact.
- Fixed text. It relays nothing from the bus, adds no store and names no teamchat verb whose syntax is not on disk (`bump`, `history`, `pingbus` and `--re` are pinned absent by a test). It is not on Stop, because an ALLOW with context there continues the turn (Task 2.4). No options.
- Shared gate: `team_role_gate.probe_coordinator_advisory_armed`, which checks the main thread before the probe and treats a raising probe as armed with a WARNING. `coordinator_board` now uses it too, so there is no third copy of `_armed`. The board's own tests still pass unchanged.
- Paperwork: HandlerID, Priority, session_start `__init__`, init_config, both yaml files, HANDLER_REFERENCE, config-changes v3.77.0 under `added:`, release note 100, a guidance-coverage T4 exemption, one acceptance test (silent without a team seat), the PLAN.md tick and a Success Criteria line. `.claude/HOOKS-DAEMON.md` was regenerated.

Open, not built (owner):

- Q3: where the skills live, so no skill was built.
- B6 at pause entry: a "tell the team" step is not possible. The usage-pause tool gate allows only the cron tools, ToolSearch, SendMessage and TaskStop, and denies Bash, so the step could not be carried out and would contradict the directive. Allowing a post means loosening that guard, which is an owner decision (Q16, Plan 00523).
- s11: what coordinator state to carry beyond the existing stores (work queue, directives register, bus), and who may write it. An agent-written store is the forgery path Task 2.2 declined.
- The directives register replays up to `prompt_interval - 1` human prompts late after a compaction. Its counter is per session and held in memory, and a compaction keeps the session id. This was read from the code, not tested.
- The Task 2.5 startup-timing item applies here too: if `whoami` exits 69 at a `startup` SessionStart, both notes are silent on startup.

Tests: `tests/unit/handlers/session_start/test_coordinator_conduct.py` and `tests/unit/utils/test_team_role_gate_probe_armed.py` were red first (import error), then green. They cover the conduct and return notes and the source split. The gate cases are: coordinator, coordinator duty, unknown role and unresolved probe are armed; worker, no team and sub-agent are silent, and the sub-agent never probes; RuntimeError, RecursionError and ValueError are handled. Real dispatch through `register_all` covers a coordinator on compact (only `whoami` runs, zero `open` calls), worker, exit 69, empty `teams` and no signals.
