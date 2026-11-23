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
- **Role**: what the team record says a member is. pingbus v1 has exactly two
  agent roles today, `coordinator` and `worker` (at most one coordinator per
  team), plus humans. fedora-desktop Plan 00207 plans more (outside
  collaborator, deployer). So role is an OPEN set: a role this daemon does not
  know switches nothing on.
- **Seat kind**: where the seat runs, `host` or `container`. The order's
  "host" is a seat kind, not a third role: a host seat can be a worker or the
  coordinator. Role and seat kind are two independent axes. Under Plan 00207
  the host-side job may become the `deployer` ROLE. B7 is therefore keyed on
  whichever the Phase 0 spec names, and the resolver exposes both.
- **Bus generation**: v1 `pingbus` today, v2 `teamchat` planned (fedora-desktop
  Plan 00209). Detection sits behind one adapter per generation, so v1's
  retirement does not reach any handler.

## 2. Inputs and their provenance

The order named inputs in two other repositories. Neither has a local checkout
in this container (none under `/workspace`, `/mnt`, `/srv` or `/opt`). Over
`gh`:

- **lts-infra** Plan 00158 `reports/retro-2026-11-23-unattended-weekend.md`
  (sections 2-3) and its readiness checklist with the owner GO: NOT READ. The
  repository's contents API answers 404 to this seat.
- **fedora-desktop** Plan 00263 decision D3 (the host-seat lane guard): NOT
  READ. No `00263` folder exists on the default branch's `CLAUDE/Plan/`, and
  it is probably still on a work branch.
- **fedora-desktop issue 367**: READ. A human posts a top-level follow-up in
  the questions room, and the envelope suggests `pingbus thread --re <id>`,
  which also posts at the top level. So the coordinator scatters the
  conversation out of its `Q<n>` thread. The issue's expected fix is in pingbus
  itself: the envelope names the likely open `Q<n>`, and
  `thread --re` on a top-level message needs an explicit `--top-level`. It is
  a v2 (`teamchat`) acceptance item. v1 gets the fix only if it is nearly free.
- **fedora-desktop Plans 00207 and 00209**: READ for context, not named by the
  order. 00207 (team roles, Not Started, awaiting owner decisions) adds roles
  beyond coordinator and worker. They are an outside collaborator and a
  **deployer**, which is "a host desktop session with the owner's permissions".
  00209 (agent bus v2, `teamchat`, In Progress) is the planned replacement for
  v1 `pingbus`. It uses a `TEAMCHAT_MEMBERSHIP` variable, and v1 retires once no
  team is v1-live.

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

- **No team configured** (no `PINGBUS_MEMBERSHIP`/`TEAMCHAT_MEMBERSHIP`, or
  `team_seat.detection: off`): `SeatContext.absent()`. Silent, zero behaviour
  change, no advisory, no error. This is the "not dependent" promise.
- **Team configured, role unresolvable** (malformed or missing state, unknown
  `v`, `pingbus` not on PATH, timeout, non-zero exit): the seat is present with
  `role: unknown`. Nothing raises. Guidance stays off. Whether a guard (B2, B7,
  B8) stays on, so a broken state file cannot silently disarm a coordinator,
  or turns off, is owner question Q9. Recommendation: B2 stays on for any seat
  with a team, because the pingbus HUMAN rule binds every seat. B7 and B8 turn
  off, and one advisory per session names the cause.
- `is_coordinator(team=None)`: true when any (or the named) team says
  coordinator. Multi-team: a seat may coordinate one team and work in another;
  behaviours that act on a specific team (thread hygiene, peer gate) take the
  team from the command they judge.
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

This plan reuses that route for three variables only, `PINGBUS_MEMBERSHIP`,
`PINGBUS_HOME` and `PINGBUS_TEAMS`, stamped as one new payload field. Paths
and names travel; file contents are read daemon-side by the resolver. A value
already on the payload is never overwritten, and a peer whose environment
cannot be read stamps nothing (absent).

## 6. Resolution source: owner question Q1

| Option                                                                                           | Cost                                      | Contract                                 | Risk                                                |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------- | ---------------------------------------- | --------------------------------------------------- |
| A. Read `state/team.json` + `member.json` directly                                               | A file read                               | None: pingbus-private, unversioned       | Silent wrong answer when pingbus changes its layout |
| B. Parse `pingbus status` (offline)                                                              | A subprocess per resolve, bounded timeout | Human-oriented text, not declared stable | Parse drift; slower                                 |
| C. Ask the ccy kit for `pingbus whoami --json` (team, handle, role, seat kind, protocol version) | One subprocess                            | Versioned, owned by pingbus              | Needs an upstream change in the ccy kit             |

**Recommendation**: C, requested upstream for v1 and as a v2 (`teamchat`)
requirement, since v1 is retiring; B behind the same adapter until C
ships; A only if the owner rules subprocess cost unacceptable, and then gated
on the `v` field. Whichever is chosen, results are cached per session for a
short TTL (a role change lands within one TTL) and the resolver is the ONLY
code that knows the source.

## 7. Behaviour matrix

Every row is OFF unless detection says the seat holds the named role. "Mode"
is the shipped default once the owner gives GO; guards ship advisory first.

| #   | Behaviour                                                                                       | Role / kind               | Surface                                                                                                                      | Ships as             | Spec source                                      |
| --- | ----------------------------------------------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------ |
| B1  | Coordinator conduct on the bus (dispatch, track, report, ask, close)                            | coordinator               | skill + SessionStart context naming it                                                                                       | guidance             | pingbus skill + (spec from Phase 0)              |
| B2  | HUMAN-id verification before a destructive act (push, delete, permission change, merge to main) | coordinator (workers: Q5) | PreToolUse guard on the destructive command set                                                                              | advisory, then block | pingbus skill rule; enforcement mechanism is Q4  |
| B3  | Gating a peer's branch: merge, Layer 1+2 QA, push only if green                                 | coordinator               | skill (a procedure) + reuse of the merge-QA advisory                                                                         | guidance             | (spec from Phase 0); relate to Plan 00502        |
| B4  | Departure and return (handing off, re-establishing on return)                                   | coordinator               | skill + Stop/SessionStart advisory                                                                                           | guidance             | (spec from Phase 0)                              |
| B5  | Seat liveness (noticing stale or silent seats, own seat's liveness)                             | coordinator               | advisory from `pingbus status` liveness; supervisor action is Q6                                                             | advisory             | (spec from Phase 0); relate to Plan 00470        |
| B6  | Usage-limit response (what the coordinator tells the team and itself)                           | coordinator               | advisory keyed on the usage-pause signal                                                                                     | guidance             | (spec from Phase 0); relate to Plan 00479        |
| B7  | Host-seat lane guard                                                                            | seat kind host            | PreToolUse guard                                                                                                             | advisory, then block | fedora-desktop Plan 00263 D3 (spec from Phase 0) |
| B8  | Thread hygiene: keep a human's conversation inside its `Q<n>` thread                            | coordinator               | PreToolUse on `pingbus thread --re <id>` (a top-level reply) while open questions exist: advise naming `pingbus thread Q<n>` | advisory only (Q10)  | fedora-desktop issue 367 (read)                  |
| B9  | Auto-answer of Claude Code's rate-limit dialog                                                  | any                       | supervisor                                                                                                                   | n/a here             | Plan 00523 owns it; this plan only references it |

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

- **Absent fixture first**: no `PINGBUS_*` env, no membership file, no
  `pingbus` on PATH. Every handler in the plan runs against it and produces no
  output and no error. This fixture lands in Phase 1 before any resolver code.
- Degradation fixtures: malformed JSON, unknown `v`, unreadable directory,
  subprocess timeout and non-zero exit, a team in `PINGBUS_TEAMS` with no
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
  `pingbus whoami --json`?
- **Q2** Defaults once GO is given: guidance on and guards advisory, or all off
  until a project opts in?
- **Q3** Where the skills live (section 10).
- **Q4** B2 mechanism: how a guard knows the act traces to a verified `HUMAN`
  line. Options: require a `pingbus history` lookup in the same turn (judged
  from the transcript); a daemon-side `verify-human <event-id>` command that
  records a short-lived approval; or advisory only.
- **Q5** Does B2 apply to workers too (the pingbus rule is for every seat)?
- **Q6** Seat liveness and departure: daemon advisory only, or a supervisor
  action (and through the supervisor plugin API, Plan 00487, or in the ccy
  lifecycle plugin)?
- **Q7** Should a coordinator seat be a session mode (Plan 00501), so the
  status line and mode machinery show it?
- **Q8** Confirm the owner GO named in the lts-infra readiness checklist covers
  this build, and which checklist items gate which phase. (The checklist was
  unreadable from this seat.)
- **Q9** A seat that has a team but whose role cannot be resolved: do the
  guards stay armed, or go quiet? (Section 4 gives the recommendation.)
- **Q10** B8 overlaps the pingbus-side fix that issue 367 asks for (envelope
  names the thread; `--top-level` required). Should the daemon ship an interim
  advisory for v1, or leave thread hygiene to pingbus/teamchat entirely?
- **Q11** Is the host-seat lane guard (B7) keyed on seat kind `host`, or on
  the `deployer` role from fedora-desktop Plan 00207 once that lands?
