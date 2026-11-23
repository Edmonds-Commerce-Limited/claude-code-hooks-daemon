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
- **Q14** (lts-infra Q64, pending) Build the B7 handler at all? The layer
  ownership is no longer open: if built, the dynamic by-duty check is this
  daemon's handler (Plan 00635) and the static deny set is fedora-desktop's
  `cc-deny.json`.
- **Q15** Role profile (B11): which switches, and do explicit per-key overrides
  win?
- **Q16** NEW (vet m-6): does the "no usage ceiling" ruling retire Plan 00479's
  ceiling mechanism, or only mean readiness sets none? This plan reads it as
  the latter until ruled.
- **Q17** NEW (retrospective s1): a coordinator "no-value" retire path; see
  section 19.

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

**Decision pending: lts-infra Q64** (here Q14) on building the handler.

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

**Q17** (owner, s1): adopt a logged coordinator "no-value" retire path for
unmerged branches and regenerable ignored globs, and if so, is it the existing
`branch-reject` reviewer route extended to coordinator seats?

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
4. The deny message names each unposted thread and the one post that fixes it.

Verifying "posted this turn", transport-agnostically: the handler reads the
team's history through the read-only teamchat CLI (`pingbus --team <t> history`
today; the handler calls whatever the teamchat CLI documents, behind one
adapter), takes outbound entries stamped after this turn's start, and matches
them to the named threads. No secrets are read and no bus file is opened. An
unreadable bus (CLI absent, error, timeout) fails OPEN and logs the failure
to the daemon log; it never blocks a stop on the handler's own fault.

Open dependency (teamchat side, ask fedora-desktop.1): a multi-thread bump, one
bus call that posts the same status to N threads, so the refusal costs one call
rather than N. Until it exists the deny names the per-thread posts. Filed with
Plan 00636 Task 1.2 alongside the wake-coalescing request.

Open question Q18: how does the handler learn which threads a stop names?
Options: (a) parse thread ids or names out of the stop reason text; (b) require
a structured line in the stop message (`THREADS: a, b`); (c) treat every thread
with an unanswered owner ask in the history as named. (a) is fragile, (b) adds a
format agents must remember, (c) needs no cooperation but can over-refuse.
Unsettled; Plan 00636 Task 1.1 settles it before Task 2.1 starts.

Test-first acceptance criteria (each red before the handler exists):

- A coordinator stop waiting on the owner with one unposted named thread is
  denied, and the deny names that thread.
- A worker seat stop, and a stop with an unknown role, are untouched.
- A stop whose every named thread has a bus post this turn passes.
- A stop with terminal-only status (no post anywhere) counts as unsent.
- An unreadable bus passes and writes a log line.
- A stop that does not wait on the owner is untouched.
