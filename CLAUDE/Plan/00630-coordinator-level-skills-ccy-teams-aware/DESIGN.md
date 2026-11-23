# Plan 00630 design: coordinator-level skills, ccy-teams aware

The detail behind [PLAN.md](PLAN.md). PLAN.md holds the phases and criteria;
this document holds the evidence, the model, the behaviour matrix and the open
questions.

## 1. Terms

- **ccy-teams** means the pingbus agent-team bus that `ccy --teams` joins a
  session to. It is NOT Claude Code's own experimental agent teams
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, documented in
  [CLAUDE/AgentTeam.md](../../AgentTeam.md)). Both can be on in one session;
  nothing in this plan reads the Claude Code one.
- **Seat**: one ccy session's membership of one team. A session can hold seats
  in several teams.
- **Role**: what a team's record says a member is, PER TEAM. A session can be
  coordinator in team A and worker in team B, and that must work. Today's two
  roles are `coordinator` and `worker`; the owner floats more (deployer/host,
  reviewer, others; host seats are NOT workers) and fedora-desktop Plan 00207
  plans an outside collaborator and a deployer. So role is an OPEN set that
  this plan CONSUMES from whatever teamchat declares, never hard-codes: a role
  the daemon has no behaviour for means no change.
- **Seat kind**: where the seat runs, `host` or `container`. The order's
  "host" is a seat kind, not a third role: a host seat can be a worker or the
  coordinator. Role and seat kind are two independent axes. Under Plan 00207
  the host-side job may become the `deployer` ROLE. B7 is therefore keyed on
  whichever the Phase 0 spec names, and the resolver exposes both.
- **Bus generation**: this plan is designed for v2 `teamchat` ONLY (owner
  ruling Q66, 10:41Z: "we need to get rid of v1 ASAP now and definitely should
  not design for it anywhere else"). There is no v1 `pingbus` detection path,
  adapter or fallback anywhere in the plan. v1 appears below only as evidence
  of what a membership looks like today (section 3) and is never a code path.

## 2. Inputs and their provenance

The order named inputs in two other repositories. Neither has a local checkout
in this container (none under `/workspace`, `/mnt`, `/srv` or `/opt`). Over
`gh`:

- **lts-infra** Plan 00158 retro sections 2-3: NOT READ at the source (the
  contents API answers 404 to this seat), but their content now arrives as the
  lts-infra coordinator's two bus messages (part 1: the unattended-readiness
  protocol; part 2: the ad hoc list, the proposed first feature set, the
  lane guard, thread hygiene). Those messages are the Phase 0 inputs and are
  folded into sections 13-17. The readiness checklist's owner GO is still
  unread (Q8).
- **fedora-desktop** Plan 00263 decision D3 (the host-seat lane guard): NOT
  READ at the source. Its substance arrives via part 2: the owner ruling
  (lts-infra Q62) and the recommended design, with the choice itself still
  undecided (Q64). Section 15.
- **fedora-desktop issue 367**: READ. A human posts a top-level follow-up in
  the questions room, and the envelope suggests `pingbus thread --re <id>`,
  which also posts at the top level. So the coordinator scatters the
  conversation out of its `Q<n>` thread. The issue's expected fix is in pingbus
  itself: the envelope names the likely open `Q<n>`, and
  `thread --re` on a top-level message needs an explicit `--top-level`. It is
  a v2 (`teamchat`) acceptance item. v1 gets nothing (v1 is not designed for).
- **fedora-desktop Plans 00207 and 00209**: READ for context, not named by the
  order. 00207 (team roles, Not Started, awaiting owner decisions) adds roles
  beyond coordinator and worker. They are an outside collaborator and a
  **deployer**, which is "a host desktop session with the owner's permissions".
  00209 (agent bus v2, `teamchat`, In Progress) is the planned replacement for
  v1 `pingbus`. It uses a `TEAMCHAT_MEMBERSHIP` variable. This plan targets it
  alone.

So rows that depend on the unread documents are marked
**(spec from Phase 0)**. Nothing here claims what they say beyond the order's
summary.

What WAS read, and grounds the detection design:

- the pingbus Claude Code plugin the session runs (`--plugin-dir` under the ccy
  kit's `optional/agent-bus/plugin/pingbus`): its `hooks/hooks.json` and the
  `pingbus` skill, which already states the HUMAN, PEER and PING rules, the
  HUMAN-id check before a consequential act, and the coordinator/worker roles;
- the `pingbus` CLI (`pingbus --help`, `pingbus status`, both offline);
- the session environment and pingbus's on-disk state (shapes only, below);
- this repository: no handler or utility reads pingbus state today. The only
  mentions are the supervisor's docstrings noting a pingbus seat process is a
  sibling child of the ccy host (`.claude/ccy/claude-supervise.py`), and
  `pingbus` in the long-running-command allowlist
  (`src/claude_code_hooks_daemon/utils/long_running_command.py`).

## 3. Observed signals (shapes, not values)

No handle, team roster, homeserver address or room id is recorded here: the
tracker is public. Shapes only.

**Status of this table**: every `PINGBUS_*` row is what the live v1 seat shows
and is EVIDENCE of the kind of signal a membership carries. None is a
detection path (section 4a). The v2 probe reads teamchat state
(`TEAMCHAT_MEMBERSHIP` and what it points at); its exact shape is a Phase 0
input from fedora-desktop Plan 00209 and the role-probe child plan's first
task.

| Signal                                 | Where          | Shape                                                                                       | Notes                                                                                                                     |
| -------------------------------------- | -------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `PINGBUS_MEMBERSHIP`                   | session env    | a directory holding `membership.json`                                                       | Unset outside a ccy-teams launch                                                                                          |
| `membership.json`                      | that directory | `{v, session, kind, checkout, generation, written_ms, seats: [{team, seat}], farewell: []}` | Written by ccy at launch; `seats` lists this session's seats                                                              |
| `PINGBUS_HOME`                         | session env    | the member bundle root                                                                      | Holds `active` and one directory per team                                                                                 |
| `PINGBUS_TEAMS`                        | session env    | the active team name(s)                                                                     | Plural by name; separator to confirm (one team observed)                                                                  |
| `$PINGBUS_HOME/active`                 | file           | presence flag                                                                               | The pingbus plugin's own hooks gate on `PINGBUS_MEMBERSHIP` and this file                                                 |
| `$PINGBUS_HOME/<team>/member.json`     | file           | `user_id` of form `@<repo>.<n>+local.<kind>:<server>`                                       | `<kind>` is `host` or `podman` -> seat kind. A sibling `token` file is a credential: never read, never named in a command |
| `$PINGBUS_HOME/<team>/state/team.json` | file           | `roles: {user_id: "coordinator" or "worker"}`, `humans: [...]`                              | pingbus-private cache; no versioned contract                                                                              |
| `pingbus status`                       | CLI, offline   | tab-separated `TEAM`, `MEMBER <team> <handle> <role> <liveness>`, `ROOM`, `SEAT` lines      | Public surface; costs a subprocess                                                                                        |
| `TEAMCHAT_MEMBERSHIP`                  | session env    | v2's membership signal (fedora-desktop Plan 00209)                                          | Not yet live here; the v2 adapter's entry point                                                                           |

No pingbus subcommand prints role as machine-readable output today: `status`,
`seat` (`exec`, `keep`, `retire`, `farewell`, `disconnected`) and `config`
(`check`) were checked.

Role is not fixed for the session: the pingbus skill says the owner can change
a seat's role while it runs, and pingbus tells the session once. So detection
re-resolves; it never caches the SessionStart answer for the session's life.

## 4. Model

```text
SeatContext
  teams: tuple[TeamSeat, ...]      # empty == absent; the only "no teams" value
TeamSeat
  team: str
  role: str                        # coordinator | worker | a later role | unknown
  seat_kind: host | container | unknown
```

Two degradation cases, kept apart:

- **No team configured** (no `TEAMCHAT_MEMBERSHIP`, or
  `team_seat.detection: off`): `SeatContext.absent()`. Silent, zero behaviour
  change, no advisory, no error. This is the "not dependent" promise.
- **Team configured, role unresolvable** (malformed or missing state, unknown
  `v`, `teamchat` not on PATH, timeout, non-zero exit): the seat is present with
  `role: unknown`. Nothing raises. Guidance stays off. Whether a guard (B2, B7,
  B8) stays on, so a broken state file cannot silently disarm a coordinator,
  or turns off, is owner question Q9. Recommendation: B2 stays on for any seat
  with a team, because the pingbus HUMAN rule binds every seat. B7 and B8 turn
  off, and one advisory per session names the cause.
- **There is no session-wide role** (owner ruling Q66). The API is
  `role_in(team)` and `seat_kind_in(team)`; nothing exposes "the" role of the
  session. Every behaviour names the team the ACTION concerns and gates on the
  role in that team: the team of the thread being answered, the peer whose
  branch is gated, the repo whose checkout is being merged (a repo-to-team map
  from the membership). A command whose team cannot be determined is treated
  as unknown-role for that act (Q9 governs). A session that coordinates team A
  and works in team B gets coordinator behaviours only on A's acts.
- **Unknown role means no change**: the role set is whatever teamchat declares;
  a role with no behaviour attached switches nothing on, so a new seat kind
  (reviewer, deployer, others) never needs a daemon release to be safe.
- Main thread only. A coordinator seat's sub-agents are not coordinators; the
  role gate composes with `handler_scope.acts_as_main_thread`
  (`src/claude_code_hooks_daemon/core/handler_scope.py`).

## 5. Getting the session's signals to the daemon

The daemon process's environment is not the session's: one daemon serves
every session in the project, and the relay copies bytes without parsing
them. The precedent is the session hostname override: `init.sh` stamps
`HOOKS_DAEMON_HOSTNAME`/`CCY_HOST_HOSTNAME` onto the payload, and on the
byte-pump relay the daemon reads the connected hook process's environment
(`_stamp_session_hostname` in `src/claude_code_hooks_daemon/daemon/server.py`,
field `HookInputField.SESSION_HOSTNAME`).

This plan reuses that route for the teamchat membership variable(s) only
(`TEAMCHAT_MEMBERSHIP` and any further variable the v2 spec names), stamped as
one new payload field. Paths and names travel; file contents are read daemon-side by the resolver. A value
already on the payload is never overwritten, and a peer whose environment
cannot be read stamps nothing (absent).

## 4a. v2-only ruling (owner Q66)

Folded from the owner's ruling relayed on the bus: design for v2 only; no
v1/pingbus path (detection, adapter, fallback, advice) anywhere; roles per
team; consume declared roles. Consequences: no per-generation adapter (one
teamchat probe, behind one module so a later teamchat layout change touches
one file); no `PINGBUS_*` stamping; the fixtures use teamchat shapes. Until the
teamchat state shape is read (Phase 0 input), the role-probe child plan's first
task is to write that shape down and its absent/degraded fixtures.

## 6. Resolution source: owner question Q1

| Option                                                                                                                     | Cost                                      | Contract                                 | Risk                                                 |
| -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ---------------------------------------- | ---------------------------------------------------- |
| A. Read teamchat's membership and team state files directly                                                                | A file read                               | Whatever v2 declares; unversioned if not | Silent wrong answer when teamchat changes its layout |
| B. Parse a human-oriented teamchat status command                                                                          | A subprocess per resolve, bounded timeout | Not declared stable                      | Parse drift; slower                                  |
| C. Ask teamchat for a versioned machine-readable `whoami`/membership (per team: handle, role, seat kind, protocol version) | One subprocess                            | Versioned, owned by teamchat             | A v2 acceptance item to request from fedora-desktop  |

**Recommendation**: C, requested as a teamchat v2 requirement (Plan 00209 is
still in progress, so this is the cheapest moment to ask); A only as the
stop-gap if C is not ready, gated on a version field. No v1 route. Results are
cached per session for a short TTL (a role change lands within one TTL) and the
resolver is the ONLY code that knows the source.

## 7. Behaviour matrix

Every row is OFF unless detection says the seat holds the named role. "Mode"
is the shipped default once the owner gives GO; guards ship advisory first.

| #   | Behaviour                                                                                                                  | Role / kind               | Surface                                                                                                                      | Ships as             | Spec source                                      |
| --- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------ |
| B1  | Coordinator conduct on the bus (dispatch, track, report, ask, close)                                                       | coordinator               | skill + SessionStart context naming it                                                                                       | guidance             | pingbus skill + (spec from Phase 0)              |
| B2  | HUMAN-id verification before a destructive act (push, delete, permission change, merge to main)                            | coordinator (workers: Q5) | PreToolUse guard on the destructive command set                                                                              | advisory, then block | pingbus skill rule; enforcement mechanism is Q4  |
| B3  | Gating a peer's branch: merge, Layer 1+2 QA, push only if green                                                            | coordinator               | skill (a procedure) + reuse of the merge-QA advisory                                                                         | guidance             | (spec from Phase 0); relate to Plan 00502        |
| B4  | Departure and return (handing off, re-establishing on return)                                                              | coordinator               | skill + Stop/SessionStart advisory                                                                                           | guidance             | (spec from Phase 0)                              |
| B5  | Seat liveness (noticing stale or silent seats, own seat's liveness)                                                        | coordinator               | advisory from `pingbus status` liveness; supervisor action is Q6                                                             | advisory             | (spec from Phase 0); relate to Plan 00470        |
| B6  | Usage-limit response (what the coordinator tells the team and itself)                                                      | coordinator               | advisory keyed on the usage-pause signal                                                                                     | guidance             | (spec from Phase 0); relate to Plan 00479        |
| B7  | Host-seat lane guard (section 15)                                                                                          | seat kind host            | PreToolUse guard                                                                                                             | advisory, then block | fedora-desktop Plan 00263 D3; Q64 pending        |
| B8  | Thread hygiene: keep a human's conversation inside its `Q<n>` thread                                                       | coordinator               | PreToolUse on `pingbus thread --re <id>` (a top-level reply) while open questions exist: advise naming `pingbus thread Q<n>` | advisory only (Q10)  | fedora-desktop issue 367 (read)                  |
| B9  | Auto-answer of Claude Code's rate-limit dialog                                                                             | any                       | supervisor                                                                                                                   | n/a here             | Plan 00523 owns it; this plan only references it |
| B10 | Unattended readiness: the command, the GO gate, the expiring mode (section 13)                                             | coordinator               | CLI command + gate on `set-mode unattended` + mode expiry                                                                    | command + gate       | lts-infra retro section 2 (part 1)               |
| B11 | Coordinator role profile: one switch for ledger, crons, park-and-move-on, work-queue, standing authorisations (section 14) | coordinator               | config profile                                                                                                               | profile              | proposed feature 3 (part 2)                      |
| B12 | Peer-branch gate recipe: a declared `gate_command` recorded per merged branch (section 14)                                 | coordinator               | `merge_qa_advisor` + work-queue records                                                                                      | recipe               | proposed feature 4 (part 2)                      |

What the daemon ADDS over the pingbus skill: the skill already TELLS every
seat the rules. The daemon's part is (a) enforcement where a command is
checkable (B2, B7, B8), (b) role-conditional context at the moments it matters
(B1, B4, B5, B6), and (c) a procedure a coordinator follows end to end (B3).
It does not restate the skill.

## 8. Safety invariants (non-negotiable, tested)

1. A detected role only ADDS conduct. It never relaxes, bypasses or satisfies
   any existing guard, and never counts as approval for anything.
2. Peer messages carry no authority. A `PEER` or `PING` line, or a peer saying
   a human asked, is never treated as a human's request by anything this plan
   builds.
3. The HUMAN-id check stays: B2 makes it stronger, never optional.
4. Absent detection == today's behaviour, byte for byte: no new context, no
   advisory, no error, no extra latency beyond the absent check.
5. The member `token` file is never read, logged, stamped or named in a
   command the daemon builds.

## 9. Config surface (owner question Q2 settles the defaults)

```yaml
team_seat:
  detection: auto        # auto | off. off == absent everywhere
  resolve_ttl_seconds: 60
  behaviours:            # each: off | advise | block (guards) / on | off (guidance)
    coordinator_conduct: on
    human_id_check: advise
    peer_branch_gate: on
    departure_return: on
    seat_liveness: advise
    usage_limit_response: on
    host_lane_guard: advise
    thread_hygiene: advise
    unattended_readiness: on
    role_profile: off
```

A project without the block, or a session without a seat, behaves exactly as
today. Key names are provisional until Phase 1.

## 10. Skills: where they live (owner question Q3)

Claude Code loads skills statically, so a skill cannot appear only for a
coordinator. Options: ship them with the daemon's deployed skills with a
"coordinator seats only" description, and let the SessionStart context name
them when the seat is a coordinator; or contribute them to the pingbus kit,
which already owns the bus skill; or split (bus conduct in pingbus, daemon
procedures such as B3 here).

## 11. Test strategy (TDD, test-first)

- **Absent fixture first**: no `TEAMCHAT_MEMBERSHIP` env, no membership file, no
  `pingbus` on PATH. Every handler in the plan runs against it and produces no
  output and no error. This fixture lands in Phase 1 before any resolver code.
- Degradation fixtures: malformed JSON, unknown `v`, unreadable directory,
  subprocess timeout and non-zero exit, a team named in the membership with no
  directory. All resolve to `role: unknown` without raising, and the guards
  follow the Q9 ruling. An unknown role name (for example `deployer` before
  this daemon knows it) switches nothing on.
- Role fixtures: worker, coordinator, multi-team (coordinator in one, worker in
  another), host vs container seat kind, a role change between two resolves.
- Scope fixture: a sub-agent payload from a coordinator seat is not a
  coordinator.
- Invariant tests for section 8, including one asserting no code path opens a
  file named `token`.
- Fixtures use synthetic handles and teams only.

## 12. Open questions for the owner

- **Q1** Resolution source: A, B or C (section 6); and will the ccy kit add
  a versioned machine-readable per-team `whoami` (option C, teamchat v2)?
- **Q2** Defaults once GO is given: guidance on and guards advisory, or all off
  until a project opts in?
- **Q3** Where the skills live (section 10).
- **Q4** SHARPENED, recommendation settled by part 2 (section 16): B2 requires
  a cited questions-room id, which the daemon verifies through the bus CLI's
  history (`pingbus`/`teamchat`), never by reading transport state. Owner to
  confirm, plus: how the cite is passed (a marker in the command, or a
  `verify-human <id>` call that records a short-lived approval).
- **Q5** Does B2 apply to workers too (the pingbus rule is for every seat)?
- **Q6** Seat liveness and departure: daemon advisory only, or a supervisor
  action (and through the supervisor plugin API, Plan 00487, or in the ccy
  lifecycle plugin)?
- **Q7** Should a coordinator seat be a session mode (Plan 00501), so the
  status line and mode machinery show it?
- **Q8** PARTLY SETTLED. The readiness protocol is now known (section 13):
  the GO it describes is the owner's reply to a readiness question, and it
  gates `set-mode unattended`, not this build. Still open: whether the owner
  GO on the lts-infra checklist covers building this plan, and which items
  gate which phase. The checklist itself is still unread.
- **Q9** A seat that has a team but whose role cannot be resolved: do the
  guards stay armed, or go quiet? (Section 4 gives the recommendation.)
- **Q10** SETTLED for the plan: part 2 says "the fix is in pingbus; the daemon
  could advise", so thread hygiene ships as an optional daemon advisory (B8,
  section 17), advisory only, off the pingbus fix path. Only the default
  (on or off) remains with Q2.
- **Q11** SHARPENED. The owner ruling (Q62) says "host seats", and the
  recommended design keys on the `+local.host` seat kind. So B7 is keyed on
  seat kind `host` now; the `deployer` role from Plan 00207 is an additional
  key to add if that plan lands. Whether the guard is built at all is Q64 (new).
- **Q12** NEW. Readiness command: where it lives (daemon CLI subcommand versus
  a skill driving existing commands), and where the expiring unattended mode's
  window and queue are stored (section 13).
- **Q13** NEW. Should the GO gate on `set-mode unattended` apply to every
  session, or only to a coordinator seat? Recommendation: coordinator seats
  with a team only; a no-team session keeps today's behaviour (invariant 4).
- **Q14** NEW (owner decision, lts-infra Q64, pending). Build the host-seat
  lane guard as a PreToolUse handler (recommended), with Claude Code deny rules
  as a cheap second layer, or deny rules alone (misses scripts and `sh -c`)?
  Phase 5 is blocked until ruled.
- **Q15** NEW. Role profile (B11): which switches does the single setting turn
  on, and does it respect a project's explicit per-key overrides?

Q66 (owner, 10:41Z and 10:42Z) settles: v2 only (no v1 path); roles per team;
consume declared roles; the usage-limit "stop and wait" answer is confirmed
and delivered by Plan 00523 (referenced, not recreated); the work may be split
into several plans and all of it is to be built. Q1 narrows to options A and C
(section 6). Q11 stays as sharpened.

Pending Phase 0 inputs: (a) the coordinator's self-retrospective of its own
history (situations needing coordinator tooling), being produced by the
coordinator and to be sent as extra input; (b) the teamchat state shape and
declared-role set (fedora-desktop Plans 00209 and the more-seat-kinds design,
requested from fedora-desktop.1); (c) the readiness checklist and its owner GO
(Q8); (d) the D3 source document.

Phase 0 status: the inputs for Tasks 0.1 and 0.2 are ingested via the bus
(retro section 2 and 3 content, the D3 ruling and design). Not yet done: the
readiness checklist and its owner GO (Q8), the D3 source document, and the
owner rulings on Q1-Q3, Q5-Q7, Q9, Q12-Q15.

## 13. Unattended readiness (B10)

Spec source: the lts-infra retro section 2 as relayed. The coordinator runs it
whenever the owner says they are leaving, ideally well ahead of departure
("prepare for unattended until `<time>`"). The eight steps:

1. **One readiness question**: a single ask-human, "UNATTENDED READINESS until
   `<time>`", listing every open owner-blocking item (open questions, live
   awaiting-human reasons, needs-owner issues, asks buried in threads). Each
   item carries a recommended default and a fallback ("no answer, I do X /
   park Y"). Never thread-only.
2. **Usage runway**: `session-state --json` for the 5-hour and 7-day windows
   and their resets; the dialog answerer armed; which token is running and what
   happens when it runs out. Owner ruling (10:28Z): there is NO usage ceiling,
   because a ceiling throws usage away; the supervisor answers the dialog
   instead (Plan 00523 delivers this; this plan only checks it is armed).
3. **Crons**: failsafe and watchdog present, declared crons asserted, the
   stand-in policy stated.
4. **Standing authorisations** for the window. Allowed (named): push; merging a
   peer branch after its gate; prototyping-phase plays. Not allowed (named):
   data destruction, seat cut-overs, anything owner-ordered elsewhere.
5. **Work queue and stop conditions**: an ordered list, one big change at a
   time.
6. **Seats**: each seat's liveness, and which may be restarted with nobody
   present.
7. **Owner GO**: the owner replies GO to the readiness question. Until a
   verified HUMAN GO arrives (its id checked in questions-room history, the
   section 16 check), the coordinator is not unattended.
8. **Arm**: `set-mode unattended` with the window, queue and authorisations.
   From then on, any new owner-only question is parked as an ask-human and the
   next item starts; never a blocking prompt.

Where each part lives (as given):

| Part                                                                                | Home                              |
| ----------------------------------------------------------------------------------- | --------------------------------- |
| Readiness command (builds steps 2, 3, 6), the GO gate, the expiring unattended mode | this daemon                       |
| Project-specific authorisations (step 4 content)                                    | the project's docs                |
| Readiness question type; surfacing open asks inside threads                         | pingbus/teamchat (fedora-desktop) |

Daemon design:

- **Readiness command** (provisional `hooks-daemon unattended-readiness`):
  read-only. It reports steps 2, 3 and 6 as a checklist with a pass or gap per
  line, from existing signals: session state and usage windows, the declared
  and session crons, and seat liveness from the seat resolver. It prints the
  step 1 item list skeleton for the coordinator to send but sends nothing
  itself, so it stays transport-agnostic.
- **Expiring unattended mode**: the existing `mode` skill already has an
  unattended mode that blocks Stop. The change is an expiry: arming records the
  window end (and queue and authorisations as a pointer to a file under
  `untracked/`), and the mode lapses at the window end or on the next real human
  message, whichever is first. Expiry on return follows how `awaiting-human`
  already ends on a human prompt.
- **GO gate**: arming `set-mode unattended` on a coordinator seat is refused
  until a GO is on record, using the section 16 check on the cited id.
  Without a team the command behaves as today (Q13).
- The daemon never decides authorisations: it records the list the coordinator
  supplies and surfaces it in the mode's status; the project's docs own the
  content.

## 14. First feature set as phases

The coordinator proposed five features. Mapping to phases (PLAN.md carries the
task lists):

| #   | Feature                                                                                                                                                                                            | Delivery                                                                                             |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 1   | Limit resilience: supervisor dialog answerer plus hooks-screen; ceiling dropped by owner ruling                                                                                                    | Plan 00523. Referenced, not duplicated here. This plan only checks readiness step 2 sees it armed    |
| 2   | Unattended readiness: the command, the GO gate, an expiring mode                                                                                                                                   | Section 13; Phase 4                                                                                  |
| 3   | Coordinator role profile: one switch enabling the goal ledger, crons, park-and-move-on for awaiting-human when unattended, work-queue enforcement on dispatch, the owner's standing authorisations | Phase 3 (B11). A config profile that sets the existing per-feature keys; owns no new mechanism (Q15) |
| 4   | Peer-branch gate recipe: a declared `gate_command` that `merge_qa_advisor` and work-queue record per merged branch, so "merged and gated" is a record, not a habit                                 | Phase 3 (B12), built on `merge_qa_advisor`; relates to Plan 00502                                    |
| 5   | HUMAN-approval check: a cited questions id verified through the bus CLI history                                                                                                                    | Section 16; Phase 4 (B2)                                                                             |

The "ad hoc today" list the order gave (retro section 3) maps onto B1-B8:
conduct on the bus is B1; HUMAN-id verification is B2; the peer-branch gate is
B3 and B12 (`--no-ff` merge in the main checkout, Layer 1 + Layer 2, push only
if green, else `reset --keep`, one at a time); departure and return is B4;
seat liveness and restarts is B5 (fedora-desktop Plan 00251 owns seat status,
so this plan consumes it and builds none); the usage-limit response is B6, now
largely Plan 00523.

## 15. Host-seat lane guard (B7)

Spec source: fedora-desktop Plan 00263 D3 as relayed. Owner ruling (lts-infra
Q62): host sessions should not be running tests; host seats are for running
deployments or triage at desktop level; they are not workers.

Recommended design (the coordinator's, and this plan's):

- A hooks-daemon **PreToolUse handler** on Bash that refuses QA, test and build
  commands when the seat's seat kind is `host` (the `+local.host` handle kind
  in section 3). Reuse the existing slow-command and QA-command classification
  rather than a second list; the handler only adds the seat gate and a deny
  message naming the lane ("run it in a worker seat").
- Claude Code **deny rules** as a cheap second layer only. Deny rules alone miss
  scripts and `sh -c`, so they cannot be the guard.
- Role-gated and absent-safe like every other row: no team, container seat or
  unknown seat kind means the handler does nothing (Q9 governs `unknown`).
- Ships advisory first (config `host_lane_guard: advise`), block when ruled.
- Deployments and triage commands are not touched: the handler denies only the
  QA/test/build classes, and the deny message gives an escape for the owner.

**Decision pending: lts-infra Q64** (owner), here Q14. Phase 5 does not start
until it is ruled. If the owner prefers deny rules alone, the phase reduces to
documenting the rule set and this plan drops the handler.

## 16. Transport-agnostic HUMAN-approval check (B2)

Before a destructive act (push, delete, permission change, merge to main), the
coordinator must cite a questions-room id carrying a human's approval. The
daemon:

1. Takes the cited id (from a marker in the command or a `verify-human <id>`
   call, Q4).
2. Verifies it by calling the teamchat CLI's history surface (the
   `pingbus history` equivalent; v2 only),
   and checks the line's sender is a registered human of that team and that it
   is in the questions room. It reads no transport internals and no token.
3. Records a short-lived approval for that act. Failure to verify (CLI
   missing, timeout, id absent, sender a peer) is a deny with the reason, and
   never a pass.

Because verification goes through the CLI, the daemon stays independent of the
transport: only the one teamchat module knows the CLI. The team whose history
is checked is the team the act concerns (per-team roles). Safety invariants 1-3 (section 8) apply: a
detected role never counts as approval, a peer message never substitutes for
the cite. The same check serves the GO gate in section 13. Ships advisory
first.

## 17. Thread hygiene (B8)

Source: fedora-desktop issue 367 (read) and part 2. A human's top-level
follow-up is answered with `pingbus thread --re <id>`, which posts at the top
level, scattering the conversation out of its `Q<n>` thread. The real fix is in
pingbus/teamchat; the daemon only advises. Design: an OPTIONAL daemon advisory
(`thread_hygiene: advise`, default per Q2), a PreToolUse handler on
`pingbus thread --re <id>` while open questions exist, naming the likely
`pingbus thread Q<n>` form. Advisory only, never a block, coordinator seats
only, and retired when the upstream fix lands.
