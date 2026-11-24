# Coupling audit: hooks daemon versus ccy and ccy teams

Read-only audit asked for by the project owner: "we cant assume duty is
defined - that is only a teams thing, standalone seats or sessions that have
nothing to do with ccy at all will not have duty. review in general how coupled
we are to ccy and ccy teams? Ideally we do not create hard coupling".

Method: source read with file:line citations, plus one in-memory probe run
(`.venv/bin/python -I -`, script on stdin, nothing written to disk) that drove
the real handler classes with a fake `whoami` runner injected through each
handler's `_resolver` seam. No teamchat binary was run, no seat store, run
directory or secret file was opened, no git or bus write was made.

## Verdict

1. **There is no HARD coupling.** No daemon module needs the teamchat binary,
   the `.claude/ccy/` files or any `TEAMCHAT_*` / `CCY_*` variable to import,
   start or answer an event. A plain Claude Code session (no ccy, no teamchat,
   no variables) gets silence from every team handler at about one microsecond
   per call and no subprocess.
2. **The owner's concern is real in one narrower place: "unknown" is treated as
   "armed", and three different situations are folded into "unknown".** One of
   them is a correctly resolved team seat whose `duty` is simply `null`. The
   probe run shows a declared **worker** with `duty: null` gets its `pytest`
   refused by `host_seat_lane_guard` (denied under `mode: block`).
3. **Arming keys on one environment variable, not on positive team evidence.**
   `TEAMCHAT_RUNTIME` present on the payload plus any probe failure
   (`TEAMCHAT_KIT` unset, binary missing, timeout) arms every team guard. The
   daemon cannot tell "a seat in a team whose probe broke" from "a session that
   merely inherited the variable and has no team".
4. **Team-only handlers ship enabled by default and print team-only rule rows
   into the generated guidance of every client project**, including projects
   that will never hold a team seat.
5. The ccy (supervisor) side is in better shape: everything supervisor-facing
   is either opt-in or goes quiet on a file-existence check, and a relevance
   predicate already exists for it. It is the model the teams side should copy.

## Coupling table

Columns: coupling class; behaviour in a bare Claude Code session (no ccy, no
teamchat binary, no variables); behaviour in a team seat whose `whoami` answers
with `duty: null` (or the `duty` key absent, which parses identically); fix
(numbers refer to "Recommendations").

| Handler / module                                                                                                                          | Coupling          | Bare session                                                             | Team seat, duty null                                                                                                    | Fix        |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ---------- |
| `utils/teamchat_seat.py` (probe, resolver)                                                                                                | SOFT              | ABSENT on one string check, nothing run or logged                        | RESOLVED, `duty=""`; `duty_unknown()` True; a coordinator row is downgraded to role UNKNOWN                             | R1, R2, R4 |
| `utils/team_role_gate.py`                                                                                                                 | SOFT              | NOT_APPLICABLE                                                           | `duty_gate` gives ROLE_UNKNOWN for every duty asked about                                                               | R1         |
| `pre_tool_use/host_seat_lane_guard`                                                                                                       | SOFT              | silent, no probe                                                         | **ARMED**: worker's `pytest` gets the refusal (advise: context; block: DENY)                                            | R1         |
| `pre_tool_use/human_approval_check`                                                                                                       | SOFT              | silent, no probe                                                         | worker: silent. coordinator or role null: **ARMED**, and no cite can ever pass                                          | R1, R2     |
| `stop/owner_wait_stop_guard`                                                                                                              | SOFT              | silent (`matches` False before any probe)                                | coordinator with null duty reads as role unknown: unconfirmed wait under `on_unreadable_bus` (`auto` allows + advisory) | R2         |
| `session_start/coordinator_board`                                                                                                         | SOFT              | matches, emits nothing                                                   | worker: silent. coordinator or role null: board note shown                                                              | R3         |
| `post_tool_use/ci_state_reading`                                                                                                          | SOFT              | silent                                                                   | worker: silent. coordinator or role null: reading shown                                                                 | R3         |
| `user_prompt_submit/owner_directives_register`                                                                                            | SOFT              | silent (and silent anywhere with no `directives`)                        | same gate as the board                                                                                                  | R3         |
| `stop/auto_continue_stop` wind-down note                                                                                                  | SOFT              | not added                                                                | added for coordinator or role null, only onto a refusal already being given                                             | R3         |
| `stop/auto_continue_stop` stand-in / persistent crons                                                                                     | NONE (teams, ccy) | off unless `persistent_crons.enabled`                                    | unchanged by duty                                                                                                       | none       |
| `daemon/server.py` signal stamping                                                                                                        | SOFT              | one peer-environment read per event, stamps nothing                      | stamps both fields                                                                                                      | R4         |
| `daemon/team_seat_cli.py` (`team-seat` command)                                                                                           | SOFT              | prints no seat                                                           | prints duty unknown                                                                                                     | none       |
| `utils/human_approval.py`, `utils/owner_wait_bus.py`                                                                                      | SOFT              | never reached                                                            | verifier refuses every cite; bus adapter runs nothing                                                                   | R6         |
| `user_prompt_submit/standing_authorisations`                                                                                              | SOFT (ccy)        | hook-context replay only; supervisor channel off                         | no team dependency                                                                                                      | none       |
| `usage_pause_gate` + tool/stop gates, `utils/usage_pause*.py`                                                                             | SOFT (ccy)        | inert unless `hosts:` sets a `usage_ceiling`                             | no team dependency                                                                                                      | none       |
| `post_tool_use/goal_injection`, `pre_compact/compaction_signal`, `session_start/session_actions_directive`, `status_line/context_sidecar` | SOFT (ccy)        | shipped `enabled: false`                                                 | no team dependency                                                                                                      | none       |
| `session_start/ccy_supervisor_integrity`, `status_line/supervisor_indicator`, `post_tool_use/model_downgrade_recorder`                    | SOFT (ccy)        | shipped on; silent / renders nothing / writes a signal file nobody reads | no team dependency                                                                                                      | R5         |
| `stop_failure/stop_failure_recorder`                                                                                                      | NONE              | records regardless                                                       | no team dependency                                                                                                      | none       |
| `install/ccy_supervisor.py`                                                                                                               | SOFT (ccy)        | deploys nothing unless `.claude/ccy/` exists                             | not applicable                                                                                                          | none       |
| `.claude/ccy/claude-supervise.py`                                                                                                         | reverse           | not present in a client without ccy                                      | not applicable                                                                                                          | none       |

`coordinator_conduct`: no handler of that name exists in `src/` or in
`.claude/hooks-daemon.yaml`. Plan 00636's conduct advisories were built as
`ci_state_reading`, `owner_directives_register`, `coordinator_board`,
`owner_wait_stop_guard` and the wind-down note inside `auto_continue_stop`.

## Probe results

Fake runner, real handlers, `_resolver` injected. `advise` and `block` are the
handler's `mode`. "refusal" means ALLOW with the refusal as context under
`advise` and DENY under `block`.

| Environment                                  | `host_seat_lane_guard` on `pytest tests/unit` | `human_approval_check` on `git push origin feature` | `coordinator_board` |
| -------------------------------------------- | --------------------------------------------- | --------------------------------------------------- | ------------------- |
| bare (no fields on the payload)              | no match                                      | no match                                            | silent              |
| `TEAMCHAT_RUNTIME` set, `TEAMCHAT_KIT` unset | refusal ("duty cannot be read")               | refusal ("no well-formed cite")                     | note shown          |
| runtime + kit, binary missing                | refusal                                       | refusal                                             | note shown          |
| `whoami` exit 69                             | no match                                      | no match                                            | silent              |
| resolved, role worker, duty null             | **refusal**                                   | no match                                            | silent              |
| resolved, role worker, duty worker           | no match                                      | no match                                            | silent              |
| resolved, role null, duty null               | refusal                                       | refusal                                             | note shown          |

Gate verdicts from `parse_whoami` on one row:

| `whoami` row                    | role kind | `duty_gate(host)` | `role_gate(coordinator)` | advisory armed |
| ------------------------------- | --------- | ----------------- | ------------------------ | -------------- |
| worker, duty null or key absent | declared  | role_unknown      | not_applicable           | no             |
| worker, duty worker             | declared  | not_applicable    | not_applicable           | no             |
| coordinator, duty null          | unknown   | role_unknown      | role_unknown             | yes            |
| coordinator, duty coordinator   | declared  | not_applicable    | applies                  | yes            |
| role null, duty worker          | unknown   | not_applicable    | role_unknown             | yes            |
| `teams: []`                     | (absent)  | not_applicable    | not_applicable           | no             |

Cost measured: bare `matches()` is about 1.0 microsecond for
`host_seat_lane_guard` and 0.7 for `human_approval_check`. An armed
`human_approval_check` on a push costs 6 to 8 ms (git reads for the default
branch). The fake runner was called once per handler instance, not once per
session: see finding F5.

Caveats: the runner was fake, so real subprocess timing and the binary trust
check were not exercised; `owner_wait_stop_guard`, `ci_state_reading` and
`owner_directives_register` were judged by reading, not by this run.

## Findings

### F1. Duty null in a resolved seat arms the host lane guard (the owner's point)

- `SeatContext.duty_unknown()` returns True for any seat with an empty duty:
  `utils/teamchat_seat.py:303-307`.
- `duty_gate` turns that into `ROLE_UNKNOWN` for whatever duty is asked about:
  `utils/team_role_gate.py:100-104`.
- `host_seat_lane_guard` treats every verdict except `NOT_APPLICABLE` as armed
  (`handlers/pre_tool_use/host_seat_lane_guard.py:260-263`) and has a dedicated
  message for this exact case, "The teamchat probe answered, but the seat's
  duty is not declared" (`:135`, `:292-295`).
- The tests pin it: `test_unknown_duty_is_armed` and
  `test_null_duty_does_not_claim_the_probe_gave_no_answer`
  (`tests/unit/handlers/pre_tool_use/test_host_seat_lane_guard.py:264`, `:363`),
  `test_duty_gate_unreadable_duty_is_role_unknown`
  (`tests/unit/utils/test_team_role_gate.py:142`).

Where it was decided: nowhere as an owner ruling that this audit could find.
The recorded owner decision is "An unreadable `whoami` means role unknown and
the guards stay armed" (`00635 PLAN.md:30`, repeated at `:54` and in
`00630 DESIGN.md:402-404`). The 00635 journal entry
`JOURNAL/2026-11-23/220032Z-decision-68a54a.md` extends it to
"APPLIES and ROLE_UNKNOWN both refuse", choosing the settled text over the
design's own recommendation that "B7 goes quiet with the advisory"
(`00630 DESIGN.md:127-129`). The null-duty wording was then added during the
PR 233 review (`JOURNAL/2026-11-23/224428Z-decision-795544.md`). So "duty null
arms the lane guard" is an implementation reading of a ruling about an
unreadable probe, not a ruling about an undeclared duty.

The code does follow the DESIGN, though: the design itself defines a null duty
as unknown, symmetrically with role ("`null` means unknown",
`00630 DESIGN.md:24-25`; `00631 PLAN.md:30`). The plan lines that say an
"unknown duty switches nothing on" (`00631 PLAN.md:119`,
`00630 DESIGN.md:28-29`, `:261`) are about an unrecognised duty NAME such as
`reviewer`, not about null, and the tests keep the two apart
(`tests/unit/utils/test_team_role_gate.py:142` versus `:146`). The "has no
duty, so it is outside this guard" sentence (`00630 DESIGN.md:397-399`) is
about a session with no team. So the thing the owner's statement conflicts with
is the design's definition "null duty = unknown", and accepting D1 is a
redefinition of it, not a bug fix.

The design does give a positive default that makes null safe to ignore: "A
host-kind member defaults to duty `host`" (`00630 DESIGN.md:25`). If teamchat
honours that, a host seat never has a null duty, so null means "not a host as
far as anybody declared".

Does the ruling conflict with the owner's statement? **Yes for null duty, no
for a broken probe.** "An unreadable role stays armed" is defensible when the
probe FAILED in a session that is positively in a team: the guard cannot see,
so it does not disarm. It is not defensible when the probe SUCCEEDED and the
team simply declared no duty: nothing is unreadable there, the field is
absent, and duty is optional by the owner's own statement.

### F1b. The three sessions the owner named, answered directly

- **Plain Claude Code, no ccy, no teamchat, no variables:** every team handler
  is silent, nothing errors, no subprocess runs, about a microsecond per call.
  Supervisor-facing handlers are off or quiet (F8).
- **ccy session with no team:** identical to the plain session on the teams
  side PROVIDED `TEAMCHAT_RUNTIME` is not in the session's environment, or
  `whoami` answers exit 69 or an empty `teams` list. If the variable is set and
  the probe fails any other way, both guards arm and the coordinator advisories
  speak (F3). Whether ccy sets the variable without a team is the hinge this
  repository cannot answer.
- **Team seat, `whoami` answers, duty null or role unknown:** nothing errors.
  Duty null arms the host lane guard for every role; role null (or coordinator
  with duty null) arms the human-approval check and the coordinator
  advisories. One `whoami` subprocess per handler per 60 seconds (F5).

### F2. A coordinator with null duty can never be a coordinator

`_merge` downgrades `role: coordinator` to role UNKNOWN unless the duty is
readable and not host: `utils/teamchat_seat.py:398-400`
(`coordinator_unproven = role == ROLE_COORDINATOR and duty in ("", DUTY_HOST)`).
Consequences in a team that declares roles but no duties:

- `human_approval_check` arms (`utils/human_approval.py:326-328`) and then
  refuses with ROLE_UNKNOWN (`:376-378`); no cite can pass even once the verify
  contract exists.
- `owner_wait_stop_guard` treats the seat as an unconfirmed wait, never as a
  coordinator whose bus is read (`handlers/stop/owner_wait_stop_guard.py:577-578`).
- All coordinator advisories still speak (they arm on unknown).

This makes `duty` a REQUIRED field for the coordinator role, which is the
assumption the owner rejected. The intent (a host is never a coordinator) only
needs `duty == host` to block it, not `duty == ""`.

### F3. One environment variable is the whole "is this a team seat" test

`probe_seat_context` returns ABSENT only when `TEAMCHAT_RUNTIME` is empty,
detection is off, `whoami` exits 69 or `teams` is empty
(`utils/teamchat_seat.py:708-711`, `:652-653`, `:484-485`). Everything else
with the variable set is UNRESOLVED, including `TEAMCHAT_KIT` unset
(`:683-684`) and a missing binary (`:644-645`), and UNRESOLVED arms:

- `human_approval.is_armed`: `utils/human_approval.py:324-325`.
- `duty_gate` via `duty_unknown()`: `utils/teamchat_seat.py:305-306`.
- `coordinator_advisory_armed`: `utils/team_role_gate.py:119-121`.
- `owner_wait_stop_guard._armed_teams`: `handlers/stop/owner_wait_stop_guard.py:567-571`.

The probe run confirms a refusal from both PreToolUse guards with only the
runtime variable set. No subprocess is involved in the kit-unset case, so this
is not a cost problem; it is a false-positive problem.

**Hinge this repository cannot answer:** does ccy, `cc-run` or any launcher
export `TEAMCHAT_RUNTIME` for a session that holds no team (a standalone seat),
or can the variable leak into a child shell, tmux pane or nested session? If
yes, standalone sessions are armed today whenever the kit is missing or the
binary does not answer 69. If the variable is exported only once a seat link
exists, this finding is about robustness, not about a live defect. The stamp
is taken from the hook process's own environment
(`daemon/server.py:345-373`), so whatever the session inherited is what the
daemon sees.

### F4. The settled "unreadable stays armed" rule has no positive-evidence precondition

The three states in the module docstring (`utils/teamchat_seat.py:16-25`) are
right, but UNRESOLVED mixes two populations:

- (a) a session that was proven to be in a team at some point and whose probe
  now fails;
- (b) a session that only carries the variable and has never produced one
  successful `whoami`.

The resolver keeps a per-session cache (`:747`) but no memory of "this session
resolved a seat before", so it cannot tell (a) from (b).

### F5. No shared resolver: each handler builds and caches its own

Every team handler constructs a private `SeatContextResolver`:
`host_seat_lane_guard.py:218-224`, `human_approval_check.py:364-370`,
`coordinator_board.py:82-88`, `ci_state_reading.py:114-120`,
`auto_continue_stop.py:990-996`, `owner_wait_stop_guard.py:417-421`,
`owner_directives_register.py:135-138`. The probe run logged one fake `whoami`
call per handler instance for the same session. In a real seat that is up to
seven `whoami` subprocesses per session per TTL (60 s,
`utils/teamchat_seat.py:78`), and with a hanging binary up to seven 2-second
timeouts (`constants/timeout.py:175`) on hook hot paths per TTL instead of
one. Bare sessions pay nothing (`:768-769` returns before the cache).

Two handlers also read the `team_seat` block by a second route
(`owner_wait_stop_guard.py:373-387`, `owner_directives_register.py:121-133`)
instead of the registry injection (`handlers/registry.py:914-917`) the other
five use, so `team_seat.detection: off` reaches them through a different code
path.

### F6. Team-only handlers ship on, and their rules are printed for every project

Shipped `enabled: true` in both the example and `init_config`:

- `human_approval_check` and `host_seat_lane_guard`, `mode: advise`:
  `.claude/hooks-daemon.yaml.example:207-218`, `daemon/init_config.py:317-320`.
- `coordinator_board`: example `:743-745`, init_config `:492`.
- `ci_state_reading`: init_config `:438`.
- `owner_directives_register`: example `:983-985`, init_config `:473`.
- `owner_wait_stop_guard`: example `:1036-1038`, init_config `:525`.

Runtime cost in a project with no teams is negligible (F5, probe). The
standing cost is guidance: the CLAUDE.md injector lists every handler that has
prose or rules unless it `is_dormant()`
(`core/claude_md_injector.py:1184-1193`), and dormancy for the two guards means
only `mode: off` (`host_seat_lane_guard.py:214-216`,
`human_approval_check.py:360-362`). So every client project's generated
guidance carries `R-HOST-SEAT-LANE`, `R-HUMAN-APPROVAL-MISSING` and
`R-STOP-OWNER-WAIT-UNBUMPED` rows that speak of teamchat seats, questions rooms
and `pingbus thread`. This repository's own generated block shows all three in
"All other enforced rules". `ci_state_reading` also has `get_claude_md` prose
that opens "On a coordinator seat" (`ci_state_reading.py:159-174`); which tier
it lands in was not checked. The same holds on the ccy side: the default-on
`ccy_supervisor_integrity` and `model_downgrade_recorder` advisory lines and the
three `R-USAGE-PAUSE-*` rows appear in this repository's generated block, and
by the same injector rule would appear in a client that has no ccy and no
`usage_ceiling`.

### F7. A capability seam already exists, but only for the config review

`Handler.get_relevance(context)` (`core/handler.py:434`, types in
`core/relevance.py`) answers "does this handler apply to this project", and the
ccy side uses it through one shared predicate, `supervisor_relevance`
(`utils/ccy_supervisor.py:268-281`), from `goal_injection`,
`compaction_signal`, `model_fallback_detector`, `tool_disable_advisor`,
`plan_status_snapshot` and `session_actions_directive`. Its only caller is the
config-optimisation checklist (`config_optimisation/checklist.py:143`). It does
not gate registration or guidance, and no team handler declares one. The
decoupling design below is therefore an extension of an existing mechanism, not
a new subsystem.

### F8. ccy supervisor coupling is soft and mostly opt-in

- All daemon to supervisor traffic is one-way signal files; nothing in `src/`
  imports from or executes `.claude/ccy/`. The lockstep is by test (for example
  the fingerprint length, `utils/ccy_supervisor.py:45-48`, and the usage-pause
  record, `utils/usage_pause.py:12-15`), not by import.
- Supervisor-only handlers ship off: `goal_injection`
  (example `:654-655`), `session_actions_directive` (`:811-812`),
  `compaction_signal` (`:927`), `context_sidecar` (`:1133`).
- Shipped on but quiet without ccy: `ccy_supervisor_integrity` returns early
  when `ccy.env` is not armed
  (`handlers/session_start/ccy_supervisor_integrity.py:318`);
  `supervisor_indicator` renders nothing with no status file
  (example `:1169-1171`); `standing_authorisations` routes to the supervisor
  only when its channel option is on and `armed_supervisor_live` holds
  (`standing_authorisations.py:417-423`, default off at `:208`).
- `usage_pause_*` is keyed on the `hosts:` config, not on ccy
  (example `:940-941`); the record it writes is also read by the supervisor,
  and a session without one resumes through its own cron.
- `model_downgrade_recorder` ships on and writes a signal only the supervisor
  consumes (init_config `:432`). Harmless, but it is the one supervisor-only
  writer that is on by default and declares no relevance.
- Installer: `ccy.deploy_supervisor` absent means deploy and arm, but only
  when `.claude/ccy/` already exists in the target (`config/models.py:2924-2930`).
  A client with no ccy gets no supervisor files.
- Residual naming coupling: the automated-prompt detector knows the
  supervisor's typed-line marker (`utils/automated_prompt.py:15-24`,
  `utils/ccy_supervisor.py:59`). Absent a supervisor it never matches.

### F9. Adapter seam: mostly honoured, three leaks

`utils/teamchat_seat.py` states it is "The ONE module that knows where seat
facts come from" (`:3-5`), and the binary is only ever run through
`run_kit_command` (`:670-687`). Leaks:

- The environment variable names are repeated in `daemon/server.py:339-342`
  instead of imported from `teamchat_seat.RUNTIME_ENV_VAR` / `KIT_ENV_VAR`.
- `owner_wait_bus.py:34-36` and the guard's rule text
  (`owner_wait_stop_guard.py:221-222`, `:757-758`) name `pingbus thread`, a v1
  verb, against the ruling quoted at `00630 DESIGN.md:32-35` that nothing is
  designed for v1.
- `utils/long_running_command.py:138` lists `pingbus` as a known program.
  That is a classification list, not a dependency.

### F10. No test runs the whole handler set in a bare environment

Each team handler has its own absent-team unit case, and
`tests/unit/daemon/test_event_socket_teamchat_signals.py` covers stamping. No
test file was found (by name) that loads every registered handler with default
config, feeds each a payload with no team fields and no ccy files, and asserts
no context, no deny and no subprocess. The per-handler cases cannot catch a new
handler that forgets the absent path.

### Not verified

- Whether `process_environ` (used by `daemon/server.py:364` on every event of
  every session) is cached or shares its read with the hostname stamp. The
  lookup was refused by the symbol-search guard and not pursued.
- The real `teamchat whoami` contract: no binary is present here. The latest
  00634 commit records the fedora-desktop reply as peer-relayed and unverified.
- Any launcher behaviour for `TEAMCHAT_RUNTIME` (the F3 hinge).
- The per-prompt cost of `usage_pause_gate` when no `usage_ceiling` is set
  (its `matches` returns True for every prompt,
  `handlers/user_prompt_submit/usage_pause_gate.py:206-208`; the body was not
  read).
- The bodies of `stop_failure_recorder` and `model_downgrade_recorder`. Their
  rows in the coupling table rest on a reference search (no ccy or teamchat
  reference in the first; a shipped comment naming the supervisor as the
  reader of the second), not on a read of what they do.
- `tests/` and `docs/` references to a `coordinator_conduct` name (the wide
  search was refused; only `src/` and the project config were searched).

## Recommended rule

Arm on evidence, not on absence of evidence. Four cases, kept apart in the
types:

| Case                                                           | Evidence of a team  | Guards (deny-capable)                                  | Advisories |
| -------------------------------------------------------------- | ------------------- | ------------------------------------------------------ | ---------- |
| A. No runtime signal, exit 69, empty teams                     | none                | silent                                                 | silent     |
| B. Runtime signal only; this session has never resolved a seat | weak (one variable) | silent; one log line; one advisory at most per session | silent     |
| C. Seat resolved; a field is null or the key is absent         | positive            | the field is UNDECLARED: switches nothing on           | silent     |
| D. Seat resolved earlier in this session; the probe now fails  | positive            | stay armed (the settled ruling)                        | armed      |

Applied:

- **Duty null or absent is "undeclared", not "unknown".** `duty_gate(host)`
  answers NOT_APPLICABLE. Only a declared `host` arms the lane guard.
- **Role null stays "unknown"** in a resolved seat, because role is a required
  part of a seat and the wire defines null as "not yet known"
  (`00630 DESIGN.md:18-19`). The human-approval check may stay armed there.
- **A coordinator needs `duty != host`, not a declared duty.**
- **"Unreadable stays armed" applies to case D only.** It needs the resolver
  to remember, per session, that a seat was once resolved.

## Recommendations, in priority order

**R1. Split "undeclared" from "unreadable" for duty.** Behaviour change; owner
ruling needed (D1).
Files: `utils/teamchat_seat.py` (`duty_unknown` counts only UNRESOLVED, or
gains an `undeclared` twin), `utils/team_role_gate.py` (`duty_gate`),
`handlers/pre_tool_use/host_seat_lane_guard.py` (drop the `_NULL_DUTY` branch
and the "an unreadable duty keeps it armed" guidance sentence), the three
pinned tests in F1, `.claude/hooks-daemon.yaml.example:216`, the rule text in
`constants/rule_ids.py:230`.

**R2. Stop requiring a duty for the coordinator role.** Behaviour change; owner
ruling needed (D2).
Files: `utils/teamchat_seat.py:398` (`duty == DUTY_HOST` only), module
docstring `:32-35`, `tests/unit/utils/test_teamchat_seat.py`,
`tests/unit/utils/test_team_role_gate.py:116`.

**R3. Require positive team evidence before an UNRESOLVED probe arms
anything.** Behaviour change; owner ruling needed (D3).
Files: `utils/teamchat_seat.py` (resolver records "resolved once" per session
and exposes it on `SeatContext`, for example a `team_confirmed` flag),
`utils/team_role_gate.py:119-121`, `utils/human_approval.py:324-325`,
`handlers/stop/owner_wait_stop_guard.py:567-571`. Until the F3 hinge is
answered, this is the change that protects standalone sessions.

**R4. One shared resolver, owned by the adapter module.** No behaviour change.
Files: `utils/teamchat_seat.py` (a module-level `shared_resolver(config)`),
the seven handlers in F5 (replace the private `_seat_resolver` bodies; keep the
`_resolver` test seam), `handlers/registry.py:914-917` (inject the resolver
instead of the config block), and drop the second config route in
`owner_wait_stop_guard.py:373-387` and `owner_directives_register.py:121-133`.
Also import the two variable names into `daemon/server.py:339-342`.

**R5. Make capability a declared property, and let it gate guidance.** Guidance
change only; owner ruling on defaults (D4).
Reuse `get_relevance` (F7). Add a `team_seat_relevance` predicate beside
`supervisor_relevance`, declared by the seven team handlers, and have
`core/claude_md_injector.py:1184-1193` skip a handler whose relevance is
absent, the same way it skips a dormant one. The project-level signal has to be
static, since guidance is generated at daemon restart with no session: an
explicit config key is the honest choice (for example `team_seat.detection: off | auto | on`, where a project that has never had a seat stays quiet in
guidance until one is seen or the key says `on`). Add the same declaration to
`model_downgrade_recorder`. Files: `core/relevance.py`,
`utils/teamchat_seat.py` or a small `utils/team_relevance.py`,
`core/claude_md_injector.py`, `config/models.py:3491-3513`, the seven handlers.
Not registering the handlers at all is the stronger form; it is not needed for
correctness because the absent path already costs about a microsecond, so it is
left as an option, not a recommendation.

**R6. Finish the adapter seam.** No behaviour change.
Files: `utils/owner_wait_bus.py:34-36` and
`handlers/stop/owner_wait_stop_guard.py:221-222`, `:757-758` (the v1
`pingbus thread` wording moves behind the adapter's `notify_commands`, so the
handler and its rule text name no bus program);
`handlers/session_start/coordinator_board.py:44-51` (the `teamchat status`
literal comes from the adapter).

**R7. A bare-environment contract test.** No behaviour change.
One test that builds the registry from default config, sends every event type
a payload with no team fields from a project root with no `.claude/ccy/`, with
a command runner that fails the test if called, and asserts: no deny, no
context from any handler tagged as team or supervisor relevant, no subprocess.
A second parametrised pass over cases B and C from the rule table pins R1 to
R3. Files: new `tests/integration/test_bare_claude_code_environment.py`,
`tests/support/teamchat.py`.

**R8. Tighten the shipped comments.** Documentation only.
`.claude/hooks-daemon.yaml.example:209` and `:216` say "Silent for a session
with no team seat"; after R1 to R3 that sentence becomes true without the
"unreadable duty keeps it armed" qualifier. `00630 DESIGN.md:24-25` and
`00631 PLAN.md:30` ("`null` is unknown" for duty) need the matching rewording
if D1 is accepted.

## Owner decisions needed

- **D1. Does a null or absent duty in a resolved seat arm the host lane
  guard?** Recommended: no; only a declared `host` duty arms it.
- **D2. May a seat be coordinator with no duty declared?** Recommended: yes;
  only `duty: host` blocks the coordinator role.
- **D3. Does "unreadable stays armed" need positive team evidence first?**
  Recommended: yes; arm on a failed probe only after this session has resolved
  a seat once, otherwise stay quiet with one log line.
- **D4. Should team-only handlers stay enabled by default, and their rules
  listed, in projects that have no team?** Recommended: keep them enabled
  (they cost nothing), but leave them out of generated guidance until the
  project declares or shows a team.
- **D5. Role null in a resolved seat: keep the human-approval check armed?**
  Recommended: yes. Today the design defines null as unknown for role and
  duty alike; D1 changes that for duty only, because duty is optional and role
  is not.
- **D6. Ask fedora-desktop whether `TEAMCHAT_RUNTIME` is ever exported without
  a seat, and whether a host-kind member always carries duty `host`.**
  Recommended: ask; both answers decide how much of D1 and D3 is live today.
