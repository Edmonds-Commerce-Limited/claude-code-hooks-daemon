# Plan 00630 design: coordinator-level skills, ccy-teams aware

The detail behind [PLAN.md](PLAN.md). PLAN.md holds the phases and criteria;
this document holds the evidence, the model, the behaviour matrix, the open
questions and (section 18) the disposition of every finding in the
fedora-desktop vet.

## 1. Terms

- **ccy-teams** means the teamchat v2 agent-team bus that `ccy --teams` joins a
  session to. It is NOT Claude Code's own experimental agent teams
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, documented in
  [CLAUDE/AgentTeam.md](../../AgentTeam.md)). Both can be on in one session;
  nothing in this plan reads the Claude Code one.
- **Seat**: one session's membership of one team. A session can hold seats in
  several teams, with a distinct handle per team.
- **Role** (wire): what teamchat's link tells the session it is, PER TEAM. The
  closed set today is `coordinator | worker | probe | null`. `null` means "not
  yet known" and maps to unknown, never to absent. A `probe` session switches
  nothing on. Role changes are owner-approved roster changes (the coordinator
  is a gated declared field), so detection re-resolves within a TTL.
- **Duty**: what the seat is FOR, PER TEAM, declared host-side and carried to
  the session by `teamchat whoami --json`. An OPEN set: `coordinator`,
  `worker` and `host` now; `reviewer` and `observer` later; `null` means
  unknown. A host-kind member defaults to duty `host`. A host member is never
  the coordinator (teamchat's `declare check` refuses it), and host seats are
  not workers. Duty is static for a run. `coordinator` duty equals
  `role == coordinator`. A duty the daemon has no behaviour for switches
  nothing on.
- **Transport kind** (`podman | lxc | host`) is teamchat's, a third separate
  thing. The daemon never reads it and never parses a handle for it.
- **Bus generation**: this plan is designed for v2 `teamchat` ONLY (owner
  ruling Q66: "we need to get rid of v1 ASAP now and definitely should not
  design for it anywhere else"). No v1 verb, file, variable or fixture appears
  in any child plan.

## 2. Inputs and their provenance

Neither input repository has a local checkout here; everything was read over
`gh` or the bus.

- **lts-infra** Plan 00158 retro sections 2-3: not readable at the source (the
  contents API answers 404 to this seat); content arrived as the lts-infra
  coordinator's two bus messages and is folded into sections 13-17. The
  readiness checklist's owner GO is still unread (Q8).
- **fedora-desktop Plan 00263 D3** (host-seat lane guard): substance read via
  the vet (section 18), which quotes its DESIGN.md section 3: A, a library
  handler in hooks-daemon switched on by config, recommended; B, Claude Code
  deny rules in `cc-deny.json`, a second layer fedora-desktop owns. Its
  "UNKNOWN: host-seat signal" is now answered by `whoami` duty.
- **fedora-desktop `PROPOSAL-seat-kinds.md`** (Plan 00209, read at 93fd6761a):
  the approved `duty` spec and `teamchat whoami --json`.
- **fedora-desktop issue 367** (thread scattering): read. Its fix is upstream in
  teamchat. See section 17 for why B8 is suspended.
- **fedora-desktop issue 369** ("teamchat: verify a HUMAN message id in the
  questions room"): the questions-room HUMAN check B2 needs (section 16).
- **fedora-desktop Plan 00207** (team roles): its `deployer` role is replaced by
  duty `host`; it is no longer a key here.

### Pending Phase 0 input: the final `whoami --json` contract

The shape is not final until fedora-desktop's branch `v2-seat-duty` merges
(fedora-desktop.1, bus id `$-NMkedob43KHw6Tj4GqlK2kI0j8G1mNPysg6CYzdcX4`). It
will be a documented contract with, per held seat, exactly four keys:

```text
teamchat whoami --json
{"v": 1, "teams": [{"team": "<team>", "handle": "<handle>", "role": "<role|null>", "duty": "<duty|null>"}]}
```

Plans and fixtures use only those four keys until the merge. The proposal text
at 93fd6761a names the second key `member`; the contract names it `handle`, and
this plan follows the contract. Still to record when it lands: the exact merged
shape and the F44 commit hash of the merge (00631 Task 1.1). The 00631 builder
is already working against this four-key shape on a branch the coordinator
reports as based on `a4fed6cbe399e3308` (not present in this clone, so not
verified here).

## 3. Signals the daemon uses (shapes, not values)

No handle, roster, homeserver or room id is recorded here: the tracker is
public.

| Signal                            | Where                    | Use                                                                                     |
| --------------------------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| `TEAMCHAT_RUNTIME`                | session env (keeper-set) | the session's run directory; absent means no team. Passed to the subprocess, never read |
| `TEAMCHAT_KIT`                    | session env (keeper-set) | locates the binary: `$TEAMCHAT_KIT/bin/teamchat`                                        |
| `teamchat whoami --json`          | CLI, no network          | per held seat: team, handle, role, duty (section 2)                                     |
| `teamchat verify --team <T> <id>` | CLI, live link           | the HUMAN check (section 16); questions room pending issue 369                          |
| `teamchat status`                 | CLI                      | other seats' liveness for B5 and readiness (or fedora-desktop Plan 00251)               |

`whoami` exit codes: 0 read ok (the list may be empty); 69 no session (no
`TEAMCHAT_RUNTIME`, or not a run directory); 65 unreadable or fails strict
decode (the spec's inference, to be confirmed against teamchat's `exits`).

`TEAMCHAT_MEMBERSHIP` is NOT a session signal: `ccy-start-claude` reads and
unsets it, and a host `cc` session never has it. `status.json` is decoded
strictly and versioned by teamchat; the daemon does not decode it (a second
decoder would drift).

## 4. Model

```text
SeatContext
  teams: tuple[TeamSeat, ...]      # empty == absent
TeamSeat
  team: str
  handle: str
  role: str                        # coordinator | worker | probe | unknown
  duty: str                        # coordinator | worker | host | a later duty | unknown
```

API: `role_in(team)`, `duty_in(team)`, and `any_duty(value)` (is any held team
of this session `duty == value`). Nothing exposes "the" role of the session.

Two degradation cases, kept apart:

- **No team** (no `TEAMCHAT_RUNTIME` on the payload, `team_seat.detection: off`,
  `whoami` exit 69, or an empty `teams` list): `SeatContext.absent()`. Silent,
  zero behaviour change, no advisory, no error.
- **Team configured, probe gave no answer** (`TEAMCHAT_KIT` missing, binary
  missing, timeout, exit 65 or any other non-zero, unknown `v`, malformed
  JSON): the seat is present with role and duty `unknown`. Nothing raises.
  Guidance stays off; a handler that would have acted says in its output that
  the probe gave no answer, once per session. Whether B2 stays armed is Q9
  (recommendation: B2 stays on, because the HUMAN rule binds every seat; B7
  goes quiet with the advisory).

Gating:

- Acts that NAME a team gate on the role in that team: a B2 cite names its
  team (`verify --team T`) and the act requires `role == coordinator` in T.
  There is no repo-to-team map: seats are placed by checkout, so one checkout
  can carry several teams, and the team is never inferred from a handle.
- Acts that concern no team (a QA command for B7, the session-level switches of
  the B11 profile) gate on `any_duty`: B7 on `any_duty("host")`, B11 on
  `any_duty("coordinator")`.
- A cached `whoami` answer lives one TTL (default 60 s). A stale `written_ms`
  in teamchat's file is not a reason to drop duty.
- Main thread only: a coordinator seat's sub-agents are not coordinators; the
  gate composes with `handler_scope.acts_as_main_thread`
  (`src/claude_code_hooks_daemon/core/handler_scope.py`).

## 5. Getting the session's signals to the daemon

One daemon serves every session in the project, so its own environment is not
the session's. The precedent is the session hostname override: `init.sh`
stamps `HOOKS_DAEMON_HOSTNAME`/`CCY_HOST_HOSTNAME` onto the payload, and on the
byte-pump relay the daemon reads the connected hook process's environment
(`_stamp_session_hostname` in `src/claude_code_hooks_daemon/daemon/server.py`,
field `HookInputField.SESSION_HOSTNAME`).

This plan reuses that route for `TEAMCHAT_RUNTIME` and `TEAMCHAT_KIT` only. A
value already on the payload is never overwritten; a peer whose environment
cannot be read stamps nothing (absent).

Where `whoami` runs (M-7): the run directory is `/tmp/teamchat/<run>` inside a
ccy container and `$XDG_RUNTIME_DIR/teamchat/run/<run>` on a host, and the
binary is on the session's `PATH`, not necessarily the daemon's. 00631 Task 1.1
either proves the daemon shares the session's mount namespace and user, or
runs `whoami` hook-side and stamps its JSON output instead. Either way the
binary is `$TEAMCHAT_KIT/bin/teamchat` with the stamped `TEAMCHAT_RUNTIME` in
its environment, never a bare name from the daemon's `PATH`.

## 6. Resolution source: Q1 SETTLED as `whoami`

`teamchat whoami --json` (option C), as approved upstream. The file-reading
stop-gap (option A) and parsing a human status command (option B) are dropped.
The resolver is the ONLY code that knows the command; one module, so a contract
change touches one file.

## 7. Behaviour matrix

Every row is OFF unless detection says the seat holds the named role or duty.
Guards ship advisory first.

| #   | Behaviour                                                                                                | Gate                                    | Surface                                                          | Ships as             | Home / source                                |
| --- | -------------------------------------------------------------------------------------------------------- | --------------------------------------- | ---------------------------------------------------------------- | -------------------- | -------------------------------------------- |
| B1  | Coordinator conduct on the bus (dispatch, track, report, ask, close)                                     | role coordinator                        | skill + SessionStart context                                     | guidance             | Plan 00636                                   |
| B2  | HUMAN-id verification before a destructive act                                                           | role coordinator in the cited team (Q5) | PreToolUse guard; `teamchat verify` (section 16)                 | advisory, then block | Plan 00634; issue 369                        |
| B3  | Gating a peer's branch                                                                                   | role coordinator                        | one procedure, delivered as B12                                  | recipe               | Plan 00633 only                              |
| B4  | Departure and return                                                                                     | role coordinator                        | skill + Stop/SessionStart advisory                               | guidance             | Plan 00636                                   |
| B5  | Seat liveness                                                                                            | role coordinator                        | advisory from `teamchat status` or fedora-desktop Plan 00251; Q6 | advisory             | Plan 00636; relates to Plan 00470            |
| B6  | Usage-limit response                                                                                     | role coordinator                        | advisory keyed on the usage-pause signal                         | guidance             | Plan 00636; Plan 00523                       |
| B7  | Host-seat lane guard (section 15)                                                                        | `any_duty("host")`                      | PreToolUse handler                                               | advisory, then block | Plan 00635; static layer is fedora-desktop's |
| B8  | Thread hygiene                                                                                           | n/a                                     | SUSPENDED (section 17)                                           | not built            | upstream, issue 367                          |
| B9  | Auto-answer of the rate-limit dialog                                                                     | any                                     | supervisor                                                       | n/a here             | Plan 00523                                   |
| B10 | Unattended readiness: command, GO gate, expiring mode (section 13)                                       | role coordinator                        | CLI command + gate on `set-mode unattended` + mode expiry        | command + gate       | Plan 00632                                   |
| B11 | Coordinator profile: one switch for ledger, crons, park-and-move-on, work-queue, standing authorisations | `any_duty("coordinator")`               | config profile                                                   | profile              | Plan 00633                                   |
| B12 | Peer-branch gate recipe: a declared `gate_command` recorded per merged branch                            | role coordinator                        | `merge_qa_advisor` + work-queue records                          | recipe               | Plan 00633                                   |

What the daemon ADDS over the bus skill: enforcement where a command is
checkable (B2, B7), role-conditional context at the moments it matters (B1,
B4, B5, B6), and a procedure followed end to end (B3/B12).

## 8. Safety invariants (non-negotiable, tested)

1. A detected role or duty only ADDS conduct. It never relaxes, bypasses or
   satisfies any existing guard, and never counts as approval.
2. Peer messages carry no authority. A peer line, or a peer saying a human
   asked, is never treated as a human's request.
3. The HUMAN-id check stays: B2 makes it stronger, never optional.
4. Absent detection == today's behaviour, byte for byte: no new context, no
   advisory, no error, no extra latency beyond the absent check.
5. The daemon opens NOTHING under teamchat's seat store or state root
   (`<store>/sessions/<session>`, `/run/teamchat/seats`, the seat pool) and
   nothing under the run directory. The seat credential is the `password` file
   in the seat directory; it is never read, logged, stamped or named in a
   command the daemon builds. The daemon only runs `teamchat whoami`, `verify`
   and `status`. Tested as "no file opened under those roots", not as a
   filename check.

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
    unattended_readiness: on
    role_profile: off
```

A project without the block, or a session without a seat, behaves exactly as
today. Key names are provisional until 00631 Phase 2.

## 10. Skills: where they live (owner question Q3)

Claude Code loads skills statically, so a skill cannot appear only for a
coordinator. Options: ship them with the daemon's deployed skills with a
"coordinator seats only" description and let SessionStart context name them
for a coordinator; or contribute them to the teamchat kit, which owns the bus
skill; or split (bus conduct in the kit, daemon procedures such as B3/B12
here).

## 11. Test strategy (TDD, test-first)

- **Absent fixture first**: no `TEAMCHAT_RUNTIME` and no `TEAMCHAT_KIT` on the
  payload. A second absent fixture: `whoami` exits 69. A third: exit 0 with an
  empty `teams` list. Every handler produces no output and no error.
- **v2-only proof fixture**: `PINGBUS_MEMBERSHIP=off` set (as a v2 launch does)
  with a teamchat seat; the result comes from `whoami` alone.
- Degradation fixtures: exit 65, other non-zero, timeout, malformed JSON,
  unknown `v`, `TEAMCHAT_KIT` unset with `TEAMCHAT_RUNTIME` set. All resolve to
  role and duty `unknown` without raising; the guards follow Q9.
- Role and duty fixtures, using only the four keys: worker; coordinator;
  multi-team (coordinator in one, worker in another); duty `host` in one team;
  `role: null`; `role: probe`; an unknown duty (`reviewer`) switches nothing on;
  a role change between two resolves.
- Scope fixture: a sub-agent payload from a coordinator seat is not a
  coordinator.
- Invariant 5 test: no file opened under the seat store, state root or run
  directory during any resolve or verify.
- Fixtures use synthetic handles and teams only.

## 12. Open questions for the owner

- **Q1** SETTLED: `teamchat whoami --json` (section 6).
- **Q2** Defaults once GO is given: guidance on and guards advisory, or all off
  until a project opts in?
- **Q3** Where the skills live (section 10).
- **Q4** B2 verifies a cited questions-room id with `teamchat verify --team T <id>` (issue 369). Owner to confirm how the cite is passed: a marker in the
  command, or a `verify-human <id>` call that records a short-lived approval.
- **Q5** Does B2 apply to workers too (the HUMAN rule is for every seat)?
- **Q6** Seat liveness and departure: daemon advisory only, or a supervisor
  action (Plan 00487 plugin API, or the ccy lifecycle plugin)?
- **Q7** Should a coordinator seat be a session mode (Plan 00501)?
- **Q8** PARTLY SETTLED. The readiness GO gates `set-mode unattended`, not
  this build. Still open: whether the owner GO on the lts-infra checklist
  covers building this plan; the checklist itself is unread.
- **Q9** A seat with a team whose probe gives no answer: guards armed or quiet?
  (Section 4 recommendation.)
- **Q10** B8 thread hygiene: confirm the drop (section 17). Previously
  "settled" from the coordinator's relay, which assumed a v1 verb.
- **Q11** SETTLED by the approved spec: B7 keys on duty `host`; the `deployer`
  role is replaced by that duty.
- **Q12** Readiness command: daemon CLI subcommand or a skill driving existing
  commands.
- **Q13** Should the GO gate on `set-mode unattended` apply to every session, or
  only a coordinator seat? Recommendation: coordinator seats only.
- **Q14** (lts-infra Q64 D3, SETTLED, owner decision relayed by the
  coordinator): build the B7 handler. On a seat whose duty (per team, from
  `whoami`) is host, the guard refuses test, build, lint and QA commands. The
  static deny rule is fedora-desktop's `cc-deny.json` (host-seat entries added
  by fedora-desktop.1); this daemon's handler (Plan 00635) owns only the
  dynamic by-duty check and adds no deny-rule task.
- **Q15** Role profile (B11): which switches, and do explicit per-key overrides
  win?
- **Q16** NEW (vet m-6): does the "no usage ceiling" ruling retire Plan 00479's
  ceiling mechanism, or only mean readiness sets none? This plan reads it as
  the latter until ruled.
- **Q17** SETTLED by the owner (lts-infra Q66 (a), yes): a logged coordinator
  "no-value" retire path for unmerged remote branches; see section 21. The
  regenerable-ignored-glob half of s1 was not ruled and stays unbuilt.

Q66 (owner) settles: v2 only; roles per team; consume declared roles; the
usage-limit "stop and wait" answer is Plan 00523; all of it is to be built.

Received: the coordinator's self-retrospective summary (section 19; the source
file was unreachable). Pending Phase 0 inputs: (b) the final
`whoami --json` contract and its F44 merge commit (section 2); (c) issue 369
landing (section 16); (d) the readiness checklist and its owner GO (Q8).

## 13. Unattended readiness (B10)

Spec source: the lts-infra retro section 2 as relayed. The eight steps:

1. **One readiness question**: a single ask-human, "UNATTENDED READINESS until
   `<time>`", listing every open owner-blocking item, each with a recommended
   default and a fallback. Never thread-only.
2. **Usage runway**: `session-state --json` for the 5-hour and 7-day windows
   and resets; the Plan 00523 dialog answerer armed (read from 00523's armed
   state: a config key plus a supervisor status line, 00523 Task 2.4). Owner
   ruling: no usage ceiling is set by readiness (Q16).
3. **Crons**: failsafe and watchdog present, declared crons asserted, the
   stand-in policy stated.
4. **Standing authorisations** for the window. Allowed (named): push; merging a
   peer branch after its gate; prototyping-phase plays. Not allowed (named):
   data destruction, seat cut-overs, anything owner-ordered elsewhere.
5. **Work queue and stop conditions**: an ordered list, one big change at a
   time.
6. **Seats**: each seat's liveness (from `teamchat status` or fedora-desktop
   Plan 00251; `whoami` carries none) and which may be restarted unattended.
7. **Owner GO**: the owner replies GO in the questions room. Until a verified
   HUMAN GO arrives (section 16), the coordinator is not unattended.
8. **Arm**: `set-mode unattended` with the window, queue and authorisations.

| Part                                                                                | Home                          |
| ----------------------------------------------------------------------------------- | ----------------------------- |
| Readiness command (builds steps 2, 3, 6), the GO gate, the expiring unattended mode | this daemon (Plan 00632)      |
| Project-specific authorisations (step 4 content)                                    | the project's config and docs |
| Readiness question type; surfacing open asks inside threads                         | teamchat (fedora-desktop)     |

Daemon design:

- **Readiness command** (provisional `hooks-daemon unattended-readiness`):
  read-only; pass or gap per line for steps 2, 3 and 6; prints the step 1 item
  skeleton but sends nothing.
- **Expiring unattended mode**: arming records the window end, the queue
  pointer and the authorisation ids; the mode lapses at the window end or on
  the next real human message, whichever is first.
- **One authorisation store**: the window's authorisations are entries in the
  existing `standing_authorisations` handler's list (its ids, enabled for the
  window). The mode records which ids; 00633's profile switches the handler on.
  No second store.
- **GO gate**: arming on a coordinator seat is refused until a GO is on record,
  verified by the section 16 check. Because the GO lives in the questions room,
  the gate cannot pass until issue 369 lands; until then it denies with that
  reason. Without a team the command behaves as today (Q13).
- **GO as cite** (M-8): a verified readiness GO is accepted by B2 as the cite
  for the act classes step 4 allowed, until the window ends or the mode lapses.
  It never covers a not-allowed class.

## 14. First feature set as phases

| #   | Feature                                                                                   | Delivery                                                    |
| --- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 1   | Limit resilience: supervisor dialog answerer                                              | Plan 00523; readiness step 2 reads its armed state          |
| 2   | Unattended readiness: the command, the GO gate, an expiring mode                          | Plan 00632                                                  |
| 3   | Coordinator profile: ledger, crons, park-and-move-on, work-queue, standing authorisations | Plan 00633 (B11); sets existing keys; owns no new mechanism |
| 4   | Peer-branch gate recipe: a declared `gate_command` recorded per merged branch             | Plan 00633 (B12, which is also B3); relates to Plan 00502   |
| 5   | HUMAN-approval check: a cited questions id verified with `teamchat verify`                | Plan 00634 (B2)                                             |

The "ad hoc today" list maps onto B1-B6: conduct is B1; HUMAN-id verification
is B2; the peer-branch gate is B3/B12; departure and return is B4; seat
liveness is B5 (fedora-desktop Plan 00251 owns seat status; this plan consumes
it); the usage-limit response is B6, largely Plan 00523.

## 15. Host-seat lane guard (B7)

Owner ruling (lts-infra Q62): host sessions should not run tests; host seats
are for deployments or triage at desktop level; they are not workers.

Layers, one guard each:

- **Dynamic, by duty: this daemon.** A PreToolUse handler on Bash (Plan 00635)
  refuses QA, test and build commands when `any_duty("host")`. It reuses the
  existing slow-command and QA-command classification; it adds only the gate
  and a deny message naming the lane ("run it in a worker seat").
- **Static: fedora-desktop.** `cc-run` writes `cc-deny.json` from the seat's
  duty and passes it with `--extra-settings` on a host launch. This daemon
  builds no deny rules. fedora-desktop builds no project handler.

Absent-safe: no team, or no team with duty `host`, means the handler does
nothing. A host `cc` session with no team has no duty, so it is outside this
guard (fedora-desktop's static layer is the only cover there). A probe with no
answer follows Q9.

**Settled: lts-infra Q64 D3** (here Q14): build the handler. It refuses test,
build, lint and QA commands on a host-duty seat; unreadable `whoami` means role
unknown and the guards stay armed.

## 16. HUMAN-approval check (B2)

Before a destructive act (push, delete, permission change, merge to main) the
coordinator cites a questions-room id carrying a human's approval. The daemon:

1. Takes the cited id and the team it names (Q4 settles how it is passed).
2. Runs `$TEAMCHAT_KIT/bin/teamchat verify --team <T> <id>` with the stamped
   `TEAMCHAT_RUNTIME`. Per issue 369, `verify` takes a questions-room id and
   answers with the room, the sender, whether the sender is a declared team
   human, the attached `Q<n>` and the text, with documented exit codes.
3. Passes only if the room is the questions room, the sender is a declared
   human of T, and the seat's role in T is coordinator. Records a short-lived
   approval for that act.
4. Any failure (binary missing, timeout, unknown id, peer sender, main-room
   line, or a `verify` that does not yet cover the questions room) is a deny
   with the reason, never a pass. There is no fallback to `history`, which is
   a bounded list and cannot look up one id.

Until issue 369 lands, today's `verify` fetches from the main room only, so a
questions-room cite cannot be verified and B2 (and the GO gate) deny. Plan
00634 is coded against the issue 369 contract and verified when it lands.

## 17. Thread hygiene (B8): SUSPENDED

Issue 367 described a v1 verb (`thread --re <id>` posting at the top level).
In v2, `thread` takes only `Q<n>` with `--ask`/`--close`; `--re` is on `ask`.
No v2 case for a daemon advisory has been shown, so B8 is not built; the fix
lives in teamchat (issue 367). Reinstated only if a v2 case is shown (Q10).

## 18. Vet dispositions (fedora-desktop.1)

Full report: [subagent-reports/261123-fedora-desktop-vet.md](subagent-reports/261123-fedora-desktop-vet.md).
Evidence note: several of the vet's line cites into the child plans point past
the end of 66-line files (00635:85-86 and :110-111, 00633:177-178), although the
plans were unchanged at 2a6fe84eb; the substance was located and fixed anyway
(00635 Task 2.2 was at :51-52; its per-team gating text at :26-27).

| Finding   | Disposition                                                                                                                                           |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| B-1       | Fixed in 00630 sections 3 and 5, 00631: stamp `TEAMCHAT_RUNTIME` and `TEAMCHAT_KIT`, resolve via `whoami`; `TEAMCHAT_MEMBERSHIP` removed.             |
| B-2       | Fixed in 00630 sections 1, 4, 6, 15, 00631, 00635: per-team role plus duty; host never coordinator; seat kind and handle parsing dropped; Q1 settled. |
| M-1       | Fixed in 00630 invariant 5, 00631, 00634: open nothing under the seat store, state root or run directory; credential is the `password` file.          |
| M-2       | Fixed in 00630 section 16, 00634: `teamchat verify --team T <id>` against issue 369; deny, no `history` fallback, until it lands.                     |
| M-3       | Fixed in 00630 sections 3, 7, 10, 11, 17: v1 table, verbs and fixtures removed; B5 on `teamchat status`/Plan 00251; B8 suspended (owner: Q10).        |
| M-4       | Fixed in 00630 section 15, 00635: handler is the daemon's, `cc-deny.json` is fedora-desktop's; 00635 deny-rule task dropped.                          |
| M-5       | Fixed in 00630 section 4, 00635: B7 fires on any held team with duty `host`; no-answer (reported) kept apart from no-team (silent).                   |
| M-6       | Fixed in 00630 section 4, 00633, 00634: no repo-to-team map; the cite names the team; profile on `any_duty("coordinator")`.                           |
| M-7       | Fixed in 00630 section 5, 00631 Task 1.1: prove shared namespace or run `whoami` hook-side; binary is `$TEAMCHAT_KIT/bin/teamchat`.                   |
| M-8       | Fixed in 00630 section 13, 00634, 00632: a verified GO is the cite for its allowed classes until the window ends; fixtured in 00632.                  |
| M-9       | Fixed in 00630 section 13, 00632, 00523 Task 2.4: liveness from `teamchat status`/Plan 00251; 00523 gains a readable armed state.                     |
| m-1       | Fixed in 00630 section 1: role set `coordinator, worker, probe, null`; null is unknown; probe switches nothing on.                                    |
| m-2       | Fixed in 00630 sections 1, 2, 12 (Q11), 00631, 00635: `deployer` removed as a key; duty `host` replaces it.                                           |
| m-3       | Fixed in 00630 sections 1 and 4: 60 s TTL kept; a stale `written_ms` never drops duty.                                                                |
| m-4       | Fixed in 00630 section 3, 00631 fixtures: exit 0, 69, 65 (65 to confirm); empty `teams` is absent.                                                    |
| m-5       | Fixed in 00630 section 15, 00635 Non-Goals: a no-team host session is out of scope here; the static layer and its gap are fedora-desktop's.           |
| m-6       | Needs owner (Q16): the plan reads "no ceiling" as readiness setting none; 00523 Task 2b.2 left as is until ruled.                                     |
| m-7       | Fixed in 00630 section 2: D3 substance recorded; host-seat signal is `whoami` duty.                                                                   |
| Overlap 1 | Fixed in 00632 and 00634: GO-as-cite rule placed in both (shared verifier already declared).                                                          |
| Overlap 2 | Fixed in 00630 section 7: B3 is delivered only as B12 in 00633.                                                                                       |
| Overlap 3 | Fixed in 00630 section 13, 00632, 00633: one store, the existing `standing_authorisations` list.                                                      |
| 00523     | Fixed in 00523 Task 2.4 (armed state); ceiling wording is Q16 (needs owner).                                                                          |

## 19. Coordinator situations (self-retrospective)

Source: the lts-infra coordinator's summary on the bus (id
`$H1i8M1mdHnpNAOeYfcBXS1Qt_KXpAsezoNsVBi7f_zs`) of lts-infra Plan 00158
`reports/retro-2026-11-23-coordinator-situations.md` at b9c175750. The file
itself was unreachable (the contents API answers 404 to this seat). The
retrospective ranks 13 situations by owner cost; the summary lists 11, s13
arrived separately (bus id `$RR8PO-V1j2FGGtlEDunJHL13rc7ewF7M6dICgv370s8`),
and s6 is not known here.

| #   | Situation (evidence as relayed)                                                                          | Disposition                                                                                                                                                                                                  |
| --- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| s1  | Logged coordinator "no-value" retire path for unmerged branches, plus regenerable ignored globs          | Owner decision (Q17); listed, not built. Prior art: the daemon's existing `branch-reject` reviewer route (`R-BRANCH-REJECT-DISPATCH`) and the worktree-remove guard's regenerable-content rule.              |
| s2  | Standing-authorisation presets and the HUMAN-id check                                                    | Plan 00634 (HUMAN check); presets are the `standing_authorisations` store switched on by Plan 00633's profile.                                                                                               |
| s3  | Directives register (one owner directive given about 8 times)                                            | New child Plan 00636.                                                                                                                                                                                        |
| s4  | Stop check mirroring any owner ask to the bus; deny `AskUserQuestion` on coordinator seats               | New child Plan 00636 (extends `R-ASK-USER-QUESTION-UNJUSTIFIED`); owner directive on the chat surface: section 20.                                                                                           |
| s5  | ci-state: GitHub "queued" versus stuck; never assert another seat's code without asking                  | New child Plan 00636.                                                                                                                                                                                        |
| s7  | Coordinator board: parallel peers' state in one view                                                     | New child Plan 00636, consuming `teamchat status` / fedora-desktop Plan 00251.                                                                                                                               |
| s8  | Work-queue on dispatch, and a wind-down mode (109 failed stops around background agents)                 | Work-queue on dispatch: Plan 00633 profile (existing mechanism, Plan 00470). Wind-down mode: new child Plan 00636.                                                                                           |
| s9  | Role per team, and a run lock (one session ran two lts-infra seats)                                      | Role per team: Plan 00631. Run lock: out of scope here (seat placement is teamchat's); Plan 00631 adds a fixture so a `whoami` answer listing one team twice raises an advisory.                             |
| s10 | Host-lane guard                                                                                          | Plan 00635.                                                                                                                                                                                                  |
| s11 | Wake coalescing and carry-over (113 compactions)                                                         | Carry-over: new child Plan 00636. Wake coalescing: out of scope (bus delivery is teamchat's); Plan 00636 Task 1.2 files the request upstream.                                                                |
| s12 | Guard false positives                                                                                    | Niggles ledger Plan 00474: expanded `git ls-files` is N696; new N697 (safe-mode prelude), N698 (bare `*` token), N699 (`sed` word in a piped bus message). Read-only `sed` print-range: disagree, see below. |
| s13 | Plan tooling: `--journal` takes a folder name; synopsis names categories and `--ref`; `find-plan --body` | New child Plan 00636 Phase 3.                                                                                                                                                                                |

Two corrections to the relay. N695 is a plan-number-discovery false positive in
a foreign clone and matches none of the s12 items, so only N696 was already
covered. The read-only `sed -n` print-range deny is deliberate, not a false
positive: the `sed_blocker` guidance states `sed -n '1,20p' file` "is blocked
anyway, DELIBERATELY", because `-n` and `-i` differ by one character, and names
`Read` with offset/limit or `awk 'NR>=a && NR<=b'` as the route. No niggle was
filed; reversing that is an owner call, not a defect.

**Q17** (owner, s1): settled for branches, see section 21; the
regenerable-ignored-glob part is still unruled.

## 20. Owner directive: the team chat is the only human surface

Source: lts-infra bus id `$TKI9gtxdX7GstI6J_SuBS8vTEmm3bjt7T-yrSdUkOVI`,
recorded upstream in lts-infra `CLAUDE/owner-directives.md` (8461e6045). A
"STOPPING BECAUSE: waiting on X" that reaches only the Claude Code terminal is
never seen by the owner. This extends the s4 Stop mirror (Plan 00636 Task 2.1).

Rules for the coordinator-seat Stop handler:

1. Applies per team, to a seat whose role from the 00631 probe is coordinator.
   A worker seat, an unknown role or an absent probe leaves the stop untouched.
2. A stop whose reason waits on the owner is refused unless every thread it
   names got a bus post earlier this turn.
3. Terminal-only status counts as unsent. The stop message is an echo of what
   went to the bus, never the only copy.
4. The deny message names each unposted thread and prints the exact single
   bump command that fixes them all (below): one call, not one per thread.

Verifying "posted this turn", transport-agnostically: the handler reads the
team's history through the read-only teamchat CLI (`pingbus --team <t> history`
today; the handler calls whatever the teamchat CLI documents, behind one
adapter), takes outbound entries stamped after this turn's start, and matches
them to the named threads. No secrets are read and no bus file is opened. An
unreadable bus (CLI absent, error, timeout) fails OPEN and logs the failure
to the daemon log; it never blocks a stop on the handler's own fault.

The remedy is the multi-thread bump, fedora-desktop request 00209 R11
(coordinator, lts-infra bus id
`$UmAjH_e42vs_kdlo2pYOwHKnGDCMJuQukkucJS8I9A4`):
`teamchat bump Q61 Q64 [--note ...]` re-pings each listed thread still
waiting on a human with "still waiting: <its question>";
`teamchat bump --waiting` does every open thread the seat asked. It notifies
by default. A refused stop prints the exact command to run, naming the
unposted threads (`teamchat bump <ids>`), so the fix is ONE call, not N.
Dependency: R11 landing in teamchat (Plan 00636 Task 2.1 depends on it); the
guard calls the command the teamchat CLI documents, behind the same adapter.

Notifying posts only (coordinator addendum, bus id
`$dmAOwAJt3ZU7lEz-zXujdmyZbNwnQC66DRPHDnf1YdQ`): a thread post the owner must
act on has to NOTIFY (v1: `pingbus thread --ask`). A plain post lands silently
and the owner missed bumps that way, so the guard counts only notifying posts
as "the owner was told". Rule 2 and "posted this turn" are read with that
filter. A `teamchat bump` notifies by default, so the remedy always produces
a notifying post. Fail closed on the filter: a post whose notify status cannot
be read from the history counts as non-notifying, and the deny says so. (This
is distinct from the unreadable-bus case above, which fails open.)

Open question Q18, narrowed by R11: which threads does a stop name? With
`teamchat bump --waiting` covering every open thread the seat asked, option
(c) (every thread with an unanswered owner ask in the history is named) is
the natural reading, and its over-refusal costs one bump call. Still open:
(c) alone, or (c) plus (b) a structured `THREADS: a, b` line to narrow it;
(a) parsing the reason text stays rejected as fragile. Second half, how a
post is known to be notifying: (d) the notify marker on the history entry
(preferred; ask fedora-desktop.1 whether R11's bump posts carry it), else
(e) infer it from the bump command the turn ran. Plan 00636 Task 1.1 settles
both before Task 2.1 starts.

Test-first acceptance criteria (each red before the handler exists):

- A plain, non-notifying post to the named thread does not satisfy the guard;
  the stop is denied and the deny prints the `teamchat bump <ids>` command.

- A post whose notify status cannot be read counts as non-notifying (denied).

- Two unposted named threads produce ONE bump command naming both.

- A notifying post to the named thread satisfies it.

- A coordinator stop waiting on the owner with one unposted named thread is
  denied, and the deny names that thread.

- A worker seat stop, and a stop with an unknown role, are untouched.

- A stop whose every named thread has a bus post this turn passes.

- A stop with terminal-only status (no post anywhere) counts as unsent.

- An unreadable bus passes and writes a log line.

- A stop that does not wait on the owner is untouched.

### 20.1 Owner HARD requirement: deterministic recent-bump check (supersedes "this turn" and Q18)

Relayed by the coordinator as the owner's HARD requirement (a peer note, so no
authority of its own until the owner confirms). Intent: a STOPPING BECAUSE that
says it is waiting for answers is countered by a deterministic check that the
threads in question were recently bumped, and that it is very clear to a human
on Lightning what is awaited. Telling the owner in the Claude Code session
breaks the rule that Lightning is the only human surface. MUST, not advisory.

1. Trigger: a Stop on a coordinator seat (00631 probe) whose reason text waits
   on a human, or whose session is in the awaiting-human mode.
2. The handler reads the bus (`pingbus --team <t> history --room questions`
   today; `teamchat` history on v2, behind the one adapter) and, for EVERY open
   question this seat asked or owns, requires a NOTIFYING post (v1 `thread --ask`; v2 `teamchat bump`) in that thread within the last N minutes
   (configurable, default N to be settled in Task 1.1) whose text names what is
   awaited.
3. Otherwise the stop is refused and the deny prints the exact bump command
   for the stale threads (one call; `teamchat bump <ids>` on v2).
4. Deterministic: ids, timestamps and the notify flag only. No LLM judgement.
   "Names what is awaited" means the post body is non-empty after the
   command's own boilerplate, not a semantic check.
5. The stop text must not restate the waits; it points at the threads (ids).

Reconciliation with the rest of section 20:

- Rule 2 above ("every thread it names got a post this turn") is REPLACED by
  "every open question the seat asked or owns got a notifying post within N
  minutes". This settles Q18's first half as option (c) outright: the handler
  never parses the reason text for thread names, and (b) `THREADS:` and (a)
  are dropped. Over-refusal costs one bump call.
- "This turn" is replaced by the N-minute window, because a turn boundary is
  not readable from history while a timestamp is.
- Rule 3 (stop message is an echo) is tightened by item 5: it is a pointer.
- The notifying-only filter and its fail-closed rule stand unchanged.
- The unreadable-bus fail-open stands, but is logged loudly and is distinct
  from an unreadable notify flag, which fails closed.

Open item (Q18 second half, recorded 2026-11-23): whether pingbus v1 `history`
can supply the notify flag. `pingbus history --help` (read-only) lists only
`--team`, `--limit` (default 50, max 500) and `--room {main,questions}`, and
`pingbus questions --help` lists only `--all` and `--retitle-closed`; neither
documents a per-entry notify or mention field. So it is NOT shown that v1 can.
Until fedora-desktop.1 confirms a notify marker (option d), the rule is
fail-closed: an entry with no readable notify flag counts as non-notifying, so
on v1 the check may refuse even after a `thread --ask` post. Mitigation
(option e, inference from the command the turn ran) is a fallback only if the
owner accepts it, since it is not read from the bus.

Additional test-first criteria (each red first):

- A waiting-on-human stop (by reason text) and an awaiting-human-mode stop are
  both detected; a stop that is neither is untouched.
- An open question with a notifying post inside N minutes passes; the same post
  older than N minutes is stale and denied with the bump command.
- A notifying post with an empty or boilerplate-only body does not count.
- A question this seat neither asked nor owns is ignored; one it owns is
  required even when the stop names no thread.
- Several stale threads produce one command naming all of them.
- A history entry with no readable notify flag counts as non-notifying.
- The deny text names thread ids only and does not restate the awaited
  content; a stop text that restates the waits is not required to be rejected.
- N is read from config; an invalid N falls back to the default and logs.
- Unreadable bus: stop passes, loud log line.

Owner-started threads (peer note relayed from the coordinator, who answered
three such messages in other threads and the owner saw no response): a
top-level HUMAN message in the questions room (no question id) starts its own
thread and is an OPEN question for this check until a NOTIFYING reply from
this seat lands in THAT thread (`thread --re <that message id>`). Additional
red tests:

- An open owner-started thread with no reply from this seat is denied, with
  the bump command naming its message id.
- A notifying reply in a DIFFERENT thread does not close it.
- A non-notifying reply in the right thread does not close it.
- A reply whose notify flag is unreadable counts as non-notifying.
- A notifying reply in that thread from this seat closes it.

"In that thread" is read from the m.thread relation to the owner's message,
NOT from m.in_reply_to (coordinator's account, unverified here: pingbus v1
`thread --re` posts only a quoted reply in the room, not into the owner's
thread, and a fix is requested from fedora-desktop.1). Unverified here:
whether pingbus v1 `history` exposes m.thread at all; fail closed meanwhile.
Further red tests:

- A reply carrying only m.in_reply_to to the owner's message does not close
  the thread.
- A reply with an m.thread relation to the owner's message (and notifying)
  closes it.
- An unreadable relation counts as not in the thread (does not close it).

Conduct advisory (00636): a reply to a human message posted outside that
message's thread. OPEN: it is deterministic only if `history` entries expose
the thread/parent id and the author kind; not shown for v1 or v2 here, so
confirm with fedora-desktop.1 (with Task 1.2's notify-flag question) and ship
the advisory only if both are readable; otherwise record it as guidance only.

## 21. Coordinator no-value remote branch retire (Q17, settled)

Owner ruling (lts-infra Q66 (a), bus id
`$QQsVGb5BLX2KG-aRLIcMW_CIV7xpXDn1YbRfrepOZV0`): a coordinator may delete an
UNMERGED remote branch it has judged to hold no value. It must log the
verdict, list the branch in the daily report, and must NEVER delete a branch
with open review comments. Built by Plan 00637.

**What exists (read, not changed).** Plan 00620's `branch-reject` route
(`core/branch_reject.py`, `branch-reject request|digest`, the dispatch gate
`R-BRANCH-REJECT-DISPATCH`, the SubagentStop verdict recorder and the
`hooks-daemon-branch-reject-reviewer` agent, config `branches.reject`): an
admitted request prints the exact reviewer prompt; a separate at-least-Opus
reviewer judges every unique commit and content-unique path; a verdict plus a
guard-written, verified recovery bundle let `delete-branch` remove an
`unproven` LOCAL branch; verdicts are single-use and expire; removals are
rate-limited and ledgered (default `.claude/branch-removals.jsonl`, config
`branches.reject.ledger_path`). The rate is counted over a rolling
`window_days` (default 7): a removal needs two reviewers once `n >= two_reviewer_after` (default 3) removals are in the window and is refused at
`refuse_after` (default 10). The route is local-only: `core/branch_reject.py`
has no remote deletion, and its callers are `delete-branch` (via
`RejectRoute` in `daemon/branch_safety.py`), the `branch-reject` CLI and the
dispatch gate, so `R-GIT-PUSH-DELETE-REMOTE` is untouched by it.
`delete-branch --remote-only` deletes a remote branch only on the merged or
no-unique-file proof, under a lease on the proven tip.

**What is new.**

1. A remote variant: `branch-reject request` accepts a branch that exists only
   on the remote (fetch the tip, same inventory and prompt); an accepted
   `no-value` verdict plus bundle lets a leased remote delete proceed. Today
   an unmerged remote branch with unique work has no route at all.
2. A seat gate: the remote variant requires `role == coordinator` (Plan 00631)
   in a held team. Worker, unknown and absent-probe seats keep the current
   behaviour (refused).
3. The open-review-comments refusal: before the request is admitted and again
   at delete time, read the branch's pull requests and their review threads
   and comments through `gh`. Any open (unresolved) review comment on any PR
   from the branch refuses. An unreadable answer (gh absent, auth, error,
   timeout, truncated page, ambiguous PR lookup) refuses: fail CLOSED.
4. A daily-report line per retired branch (name, tip, verdict id, reviewer),
   fed from the ledger entry (`remote: true`).

**Not weakened.** The independent reviewer verdict, its single use and
lifetime, the bundle, the rate limits, the dispatch gate's exact-prompt rule
and the lease are all reused as is. `R-GIT-PUSH-DELETE-REMOTE` and
`R-GIT-BRANCH-FORCE-DELETE` still deny every other route; the new route is a
subcommand the guards already know how to prove, not an exemption by role. A
coordinator's own judgment is never the evidence: the reviewer's verdict is.

**Decided: one removal-rate window.** The remote variant counts against the
SAME removal-rate window as local removals: one shared window, not a second
one (coordinator agreed, lts-infra bus id
`$UmAjH_e42vs_kdlo2pYOwHKnGDCMJuQukkucJS8I9A4`). Not an owner question.

## 22. Upgrade as a standing-authorisation preset (Q66 (b))

Owner ruling: upgrading hooks-daemon to the latest tag is a default standing
authorisation in every project, shipped as a preset. Refinement (bus id
`$vXu1JaVjHLZ1Kc5av0-zniJ0g81Rxz0NQTE6YKazliY`): a config key controls how far
an AUTOMATIC upgrade may go. Built by Plan 00633 (it already owns the
`standing_authorisations` store; Plan 00632 is the unattended gate and does
not touch the store).

**Existing pieces.** `standing_authorisations` (Plan 00223/00283) replays
recorded authorisations as short text, every built-in ships DISABLED
("nothing is authorised by default"), and text is a recorded request, never a
countermand. A preset is a built-in entry that ships enabled for this one
act, with the same revocable config key. Plan 00625 (automatic upgrade
standing approval and upgrade lock) is an unfilled template: it names no
switch, no signing key and no lock design yet, so there is nothing to reuse
and nothing to be blocked on mechanically.

**Key.** `upgrade.automatic_scope`, values `major | minor | patch | none`, default `major` (owner ruling below), the same for attended and unattended upgrades.
Plan 00625 must reuse this name for its switch rather than coin another.

**Semantics.** The "current" version is the installed daemon version read from
the installed package (not from git history). The target is the highest
release tag the rule admits:

| value   | admitted target                               |
| ------- | --------------------------------------------- |
| `major` | the latest tag                                |
| `minor` | the latest tag with the same major as current |
| `patch` | the latest tag with the same major and minor  |
| `none`  | nothing: every upgrade is triggered by hand   |

At a boundary the setting forbids (a newer tag exists but is out of scope),
surface a one-line notice naming the current version, the newer tag and the
setting; never block, and a manual upgrade is never affected by the key. An
unparseable version or tag list admits nothing and logs why (fail closed,
notice only).

**Owner ruling: no attended/unattended split (Q66 scope follow-up).** The
owner answered "unattended or not should not make a difference really"
(Q66 question id `$U506zXj_P9k99uc1zLrkfS89CYP2vGMfOS7TpyrWYxo`, relayed by
the coordinator on the lts-infra bus, id
`$KlxivVJ6cbAIoN4uNerRK2Hj8BDO3nEioVdVwoLYVP8`). So:

- `upgrade.automatic_scope` applies identically to every automatic upgrade,
  whether the session is attended or unattended. Default `major`. Ships now.
- When Plan 00625's signed-tag verification ships, it applies to EVERY
  automatic upgrade, attended or not. The scope key decides WHICH tag is
  eligible; verification decides whether that tag may be applied. They
  compose with AND, with no session-kind condition on either.
- Nothing in this design, Plan 00633 or Plan 00625 may branch on attended
  versus unattended for upgrades. This replaces the earlier recommendation
  (preset authorising only attended upgrades, unattended waiting on 00625).

**RISK for the owner (accepted by the ruling, not a blocker).** Until Plan
00625's signature verification ships, the default `major` means every project
automatically upgrades to the latest release tag WITHOUT any check that the
tag is genuine: whoever can push a tag to the release repository decides what
code every project runs next. The mitigations, and what exists today:

| Mitigation                                                                                                                                                                                                                                                                                                                                                          | Exists today?                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Upgrade-flow safety in `scripts/upgrade_version.sh`: target tag must resolve to a commit; state snapshot (`create_state_snapshot`, `scripts/install/rollback.sh`); config backup (`backup_config`); `verify_venv`; `restart_daemon_verified`; EXIT-trap rollback that restores the snapshot (or checks out the previous ref) and restarts the old daemon on failure | Yes. It catches a BROKEN upgrade; it does not detect a MALICIOUS one                                |
| Tag signature verification                                                                                                                                                                                                                                                                                                                                          | No. No `verify-tag`/GPG check anywhere in the upgrade scripts; Plan 00625 (still an empty template) |
| `upgrade.automatic_scope: none` (turns every automatic upgrade off per project)                                                                                                                                                                                                                                                                                     | No. Built by Plan 00633 Phase 4                                                                     |
| One-line notice on the first automatic upgrade under the preset (names the preset, the key, the `none` switch and that tags are not yet signature-checked)                                                                                                                                                                                                          | No. Built by Plan 00633 Phase 4                                                                     |

**Acceptance (tests first, per value; current 1.4.2, tags 1.4.3, 1.5.0, 2.0.0
as the fixture):** `major` selects 2.0.0; `minor` selects 1.5.0 and emits the
notice naming 2.0.0; `patch` selects 1.4.3 and emits the notice naming 1.5.0
and 2.0.0; `none` selects nothing and emits one notice; no newer tag in scope
emits no notice; a manual upgrade ignores the key in all four; an unparseable
tag list selects nothing and logs; the preset text is a recorded request that
names `upgrade.automatic_scope` and contains no "ignore/override" wording;
every case gives the same result in an attended and an unattended session
(no session-kind branch); the first automatic upgrade under the preset emits
the one-line risk notice once, and later ones do not; once 00625 lands, an
unsigned latest tag is never applied by ANY automatic upgrade, attended or
not.
