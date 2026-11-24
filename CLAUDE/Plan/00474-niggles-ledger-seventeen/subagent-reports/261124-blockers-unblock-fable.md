# Blockers on Plans 00523, 00630, 00634, 00635 (plus 00627 6B and N720): what can move now

Read-only pass by a Fable sub-agent. Nothing was edited, committed, pushed or sent.
This file is uncommitted; the coordinator commits it.

Verdict key: **(a)** engineering can do it now; **(b)** needs a peer; **(c)** needs the owner.

## What I could not verify

- **No live teamchat check was possible.** This shell has no `TEAMCHAT_RUNTIME` or
  `TEAMCHAT_KIT`, so `whoami`, `verify` and the kit's `duty` output are untested here.
- **The state of fedora-desktop issue 369 is unknown.** No repository slug for it is recorded
  in the plan folders, and one guessed `gh` call failed.
- **Every owner ruling below reached this repo by peer relay**, not as a line verified from
  this seat: lts-infra Q62 and Q64 D3 (host lane), "no usage ceiling", and the Q66
  housekeeping line (00627 journal `221450Z-decision-3070c3.md` says "not verified from this
  seat").
- **"Q66" names more than one ruling**: v2 only and roles per team (00630 PLAN.md:19), the
  no-value retire path (DESIGN.md:305), the upgrade preset (DESIGN.md:765) and unattended
  housekeeping (00627 PLAN.md:121). Below, "Q66 housekeeping" means the last one only.
- The host start time below assumes the container clock is UTC.

## Plan 00523: supervisor answers the rate-limit menu

### Blocker 1: Task 3.1 and Phase 1 need a real limit hit

**Verdict: neither (a), (b) nor (c): it waits on an event.** Nobody can rule or build it into
existence. It should stop being counted as "blocked work"; the plan can sit In Progress with
only this open.

**Evidence**: PLAN.md:46-53, 111-112, 138-139. Fixtures are reconstructed, not captured
(PLAN.md:59-61).

**No engineering step recommended.** A capture-on-near-miss file would make the next hit
self-recording, but review fix L1 removed exactly that file on purpose and logs a near miss by
hash only (PLAN.md:179). Bringing it back loosens a review fix, and it cannot run while the
answerer reads `INERT`. So the capture stays a by-hand step when a hit happens.

### Blocker 2: host-side parts need a ccy relaunch

**Verdict: (c), an operator act, no decision in it.**

**Evidence**: the supervisor host process (pid 2) started Mon Nov 23 12:33:38. The firm fact:
F1-F4 were built about nine hours later (journal `214155Z-action-8f13ee.md`, 21:41), so the
host cannot hold `enter_takebacks` / `resume_vetoed_at`. The weaker one: PR 223's merge commit
`42486817b` is timed 12:47:27Z, after the host start, but a commit time is not a deploy time
(`.claude/ccy/CLAUDE.md`), and the branch files may have been on disk earlier; so whether the
host holds the screen dump and the apply veto is unverified. The worker (pid 1295615, started
22:38:06) has reloaded. PLAN.md:189-196 says the same. `rate_limit_armed_status` also reads `INERT`
with no `hooks-screen` binary (PLAN.md:78-82), and that build is recorded as the owner's
v2-window action (PLAN.md:186-187).

**Owner question**: see O6.

### Blocker 3: Phase 2b "needs owner ruling Q16"

**Verdict: (a). The plan's stated reason does not hold up.**

**Evidence**:

- The real blocker is a missing field: the `.usage-paused` record has seven fields and none
  says why the pause exists (`src/claude_code_hooks_daemon/utils/usage_pause.py:76-91`;
  supervisor copy `.claude/ccy/claude-supervise.py:3836-3844`, pinned by
  `tests/unit/supervise/test_usage_pause.py`).
- Q16 touches only the parenthetical of Task 2b.2 (PLAN.md:104-105). Q16 asks whether the
  ceiling is retired; the plan already reads it as "readiness sets none" (DESIGN.md:302-304),
  and this repo's own config still dogfoods a ceiling (`.claude/hooks-daemon.yaml:2015-2023`).
- A hard-limit pause that injects nothing is correct whichever way Q16 goes. If the ceiling is
  later retired, the ceiling branch is deleted and the hard-limit branch stays.
- The need is an owner report, not a preference: `/compact` and `continue` typed every 5
  minutes into a session at its weekly limit (PLAN.md:91-93).
- `stop_failure_recorder` stores only the error type and a time
  (`handlers/stop_failure/stop_failure_recorder.py:59-74`), so Task 2b.1 needs the reset time
  from the status payload or the screen recogniser, as PLAN.md:98-100 already says.

**Next actions (builder, test-first)**:

1. Add a `cause` field (`ceiling` | `hard_limit`) to both halves, defaulting to `ceiling`
   when absent so existing records keep their meaning. First RED tests: does either parser
   reject an unknown key, and does an old supervisor host read a record carrying the new key.
   I did not verify either.
2. First RED test for the gate: `usage_pause_gate.py:11-14` lifts a pause when a fresh reading
   is under the ceiling, and a host with no ceiling yields no breach (`:548`). A hard-limit
   record on a host with no ceiling may therefore be lifted at once. The gate must leave a
   `hard_limit` record alone until `resume_at`. Unverified beyond those lines.
3. Task 2b.2: `_usage_pause_outcome` (`claude-supervise.py:9373`) injects nothing for
   `hard_limit`; a ceiling pause keeps its single `/compact`.
4. Task 2b.3 back-off follows once 2b.1 exists.

**Also fix (docs)**: PLAN.md:190-191 says "Phase 2b and Task 2.4 are built". Phase 2b is not
built (tasks unticked at PLAN.md:95-108; journal `214155Z-action-8f13ee.md`).

## Plan 00630: coordinator-level skills (umbrella)

### Blocker 1: the `whoami --json` contract's F44 merge

**Verdict: (b) for the record; it blocks no building.**

**Evidence**: the contract shape and exit 69 are recorded (DESIGN.md:60-77). Nothing depends
on exit 65: 00631 treats 65 and every other non-zero alike (DESIGN.md:94-96). The resolver,
stamp, CLI and gates are built (00631 PLAN.md:63-80). What is open is the F44 hash, exit 65
and the namespace proof (00631 PLAN.md:47-52, 130-133). Only live verification (00630 Task
1.3) truly waits.

**Next actions (a)**: the namespace proof is ours, not the peer's. In a v2 seat, run
`bin/hooks-daemon team-seat` (00631 Task 2.3) and record the answer. If it reads absent or
unknown where the session's own `teamchat whoami --json` answers, the fallback is already
designed: run `whoami` hook-side and stamp its JSON (DESIGN.md:163-169). Needs a v2 seat, so
it rides on the peer message below.

### Blocker 2: owner questions Q16, m-6, Q10

**Verdict: (c), all low priority. None blocks work.**

- **Q16 and m-6 are one question** (DESIGN.md:461 points m-6 at Q16). The safe reading
  (ceiling kept) is in force. Only "retire it" changes anything, and that removes a guard.
  See O7.
- **Q10** (confirm B8 thread hygiene stays dropped): B8 is suspended and unbuilt
  (DESIGN.md:428-433). Confirming changes nothing; reinstating needs a v2 case nobody has
  shown. See O8.

### Other open questions in section 12 (Q2, Q3, Q6, Q7, Q12, Q13, Q15)

Not named as blockers in the brief. Q2 has a built default (guards advisory, silent with no
team), which is not an owner ruling. Q12, Q13 and Q15 gate 00632 and 00633, which are Not
Started; they are worth one batch after the items below, not before. Task 0.2 also still
lists the lts-infra readiness checklist and its owner GO (Q8) as unread (PLAN.md:69-72); that
gates 00632 only.

### Peer message (one bundle, to fedora-desktop)

> hooks-daemon needs five facts to close Plans 00630/00631/00634/00635. Short answers are
> fine.
>
> 1. `whoami --json`: the F44 commit hash of the merge (we hold the v2 branch hash only).
> 2. Does `whoami` exit 65 on an unreadable or non-decoding state file? Point at the `exits`
>    table.
> 3. From which kit version does `whoami --json` emit `duty` for every seat? Can a current
>    seat still answer `duty: null`?
> 4. Issue 369 (`verify` for a questions-room id): status, and the final contract. We need:
>    the argv (is `--json` a flag?), the exit codes, the answer's keys, the event id
>    alphabet, and two additions if not present: the line's timestamp, and the `Q<n>` the
>    line answers.
> 5. Can you give us a seat with duty `host` for a live check of the lane guard? In any v2
>    seat we also need one run of `bin/hooks-daemon team-seat` beside the seat's own
>    `teamchat whoami --json`, to prove the daemon can run the probe from its own namespace.

## Plan 00634: HUMAN-approval check

### Blocker 1: Task 2.3 waits on issue 369's `verify` shape

**Verdict: (b).** Item 4 of the peer message. The production verifier refuses every cite
until then (`utils/human_approval.py:214-226`), which is the safe state.

**Evidence**: PLAN.md:62-64, 108-113. The id grammar is provisional
(`human_approval.py:62`) and fails closed if real ids differ.

### Blocker 2: P1, bind the approval

**Verdict: (a) for most of it, (b) for line age.**

**Evidence**: review finding 1 (`subagent-reports/261123-opus-independent-review-pr225.md`
lines 24-43). `VerifiedLine.question` is parsed and unused (`human_approval.py:120-127`,
`:210`). `ApprovalRecords` is memory-only (`:272`).

**Proposed resolution (it only tightens, but it has a cost, so the shape is confirmed in
O4)**:

1. **Single use per cite and act class, persisted.** One human line approves one act. The
   ledger must be a file, since a daemon restart would otherwise reset it. Buildable now
   against the provisional fixtures. Cost: under `block`, outside a readiness GO window, every
   coordinator push needs its own human line. It must not touch GO-as-cite, which covers many
   acts by design (PLAN.md:28-30).
2. **The line must answer a `Q<n>`**: a verified line with no question tag is refused. The
   field is already parsed. This stops "any human line, whatever it says".
3. **Maximum line age**: needs `verify` to return a timestamp. Peer item 4. Until it does,
   refuse (fail closed) under `block`.

The module's invariant 4 is "the line's text is never kept, logged or echoed"
(`human_approval.py:15`, `:121`), and the plan's P1 asks for binding to the text
(PLAN.md:73-74). Those two are in tension: the text could be judged inside the verify call
without being kept, but nothing does so, and judging free text is not a deterministic check.
With rules 1-3 only, "NO, do not push" answering the right `Q<n>` still passes. That residual
is real; closing it needs either a fixed answer token from teamchat (a peer request) or an
owner acceptance.

### Blocker 3: P2, sub-agents and teammates are never armed

**Verdict: (c).** It is the same question as 00635 finding 3; see O1.

**Evidence**: `human_approval.py:322`, `:366`; `team_role_gate.py:74-75`, `:98-99`. The
design pins "a sub-agent is not a coordinator" (DESIGN.md:142-144, 263-264), so arming
sub-agents changes a stated design point, and under `block` it denies every push a
coordinator's sub-agent makes today.

### Blocker 4: P3, advise is annotation only

**Verdict: (a), partly met.** It is a documentation requirement. The handler's own text says
it: "`mode: advise` only reports; `mode: block` denies"
(`handlers/pre_tool_use/human_approval_check.py:465-466`), as does the live config comment
(`.claude/hooks-daemon.yaml:445-450`). But the generated rule table in the project
`CLAUDE.md` lists `R-HUMAN-APPROVAL-MISSING` and `R-HOST-SEAT-LANE` under "All other enforced
rules" with a "Blocked" column and no advise caveat, which is the misreading P3 forbids. The
remaining work is that table's wording for both rules (a generator change). I did not read
HANDLER_REFERENCE.

### Blocker 5: Q4 and Q5

**Verdict: (c), confirm only.** Both are built as proposed and are the safe choice: a shell
comment is never expanded, which matters because the id starts with `$` (journal
`145636Z-decision-7d7b89.md`); and unknown roles stay armed. See O4.

### Flip to `mode: block`

**Verdict: (c), and not yet.** It needs issue 369, P1 and the O1 ruling first. Until 369
lands, `block` denies every coordinator push (PLAN.md:108-109).

## Plan 00635: host-seat lane guard

### Blocker 1: "about 40 wrapper bypasses need owner rulings"

**Verdict: (a) for the bulk. The brief overstates the owner's part.** The review says the fix
belongs in the classifier tables and marks only container and remote execution for the owner
(`subagent-reports/261123-opus-independent-review-pr233.md` lines 75-100).

**Evidence (probe run today against main)**: `is_lane_command` returns False for
`xargs pytest < f`, `eval pytest`, `echo $(pytest)`, `echo pytest | bash`,
`python3 -I -m pytest`, `coverage run -m pytest`, `uv run -p 3.12 pytest`,
`taskset -c 0 pytest`, `make -C sub test`, `npm t`, `just test`, `cargo +nightly test`,
`pre-commit run --all-files`, `./scripts/qa/run_autofix.sh`, `docker exec app pytest`,
`ssh host pytest`. Findings 1 and 7 spot-check as fixed (one spelling and three rows only):
`"pytest" tests/` is True; `mvn deploy`, `./deploy-qa.sh` and `command -v pytest` are False.

**Next actions (builder, test-first, one table per commit)**:

1. Wrappers and value options: `xargs`, `eval`, `taskset`, `flock`, `chronic`, `unbuffer`,
   `script -qc`, `stdbuf -o L`, `exec -a`, `env -C`, `sudo -h/-T`.
2. Launchers: `python -I/-X ... -m`, `coverage run -m`, `uv run -p/--python`,
   `cargo +toolchain`.
3. Lane-only names: `gmake`, `just`, `task`, `hatch`, `npm t`, `run-script`, `pnpm vitest`,
   `yarn jest`, `bunx`, `make -C/-f`, `pre-commit run`, `run_autofix.sh`.
4. Command substitution in argument position and a shell fed on stdin.

**Caution for the builder**: the wrapper tables are shared with
`long_running_command_guard`. Peeling a wrapper there turns a foreground advisory into a deny
for every session, not just host seats (review finding 6, lines 158-172). Keep lane-only
names in the lane tables, and give every shared-table change a release-note line.

**Owner part**: container and remote execution, and accepting what text parsing cannot see
(`P=pytest; $P`, `python -c`). See O3.

### Blocker 2: sub-agents of a host seat are never judged (finding 3)

**Verdict: (c).** Same question as 00634 P2; see O1.

### Blocker 3: does the kit emit `duty` (finding 10)

**Verdict: (b)**, peer item 3. **Plus one (c) the plan does not list**: the relayed ruling
covers an unreadable `whoami` (PLAN.md:30). The handler also arms on a readable answer whose
`duty` is null (review lines 131-144, 212-217). Under `block` that stops every worker seat in
such a team from running tests. See O2.

### Blocker 4: live check needs a host-duty seat

**Verdict: (b)**, peer item 5.

### Flip to `mode: block`

**Verdict: (c), and not yet.** After Blocker 1's tables, O1, O2, O3 and the live check.

## Plan 00627 Phase 6B (context)

**Verdict: (c).** It loosens the TTY-only gate on `--apply` and the reap (PLAN.md:123), and
the owner line is known here only on a peer's word (journal `221450Z-decision-3070c3.md`).
Peers carry no authority, so the precondition in Task 6B.0 is not met from this seat. One
line from the owner settles it: O5.

**Nothing starts before the ruling.** PLAN.md:127 says nothing below Task 6B.0 starts before
it, and the tests of 6B.2-6B.4 describe a no-TTY path that does not exist yet, so they could
not be seen failing for the right reason.

## N720: secret-file guard residual bypasses (context)

**Verdict: (c) by the brief's rule, though it tightens rather than loosens.** It trades
usability, so it is the owner's call (NIGGLES.md:8435).

**Recommendation: fail closed**, scoped as the entry proposes: only when a protected-file
link exists under the project, deny a command whose glob-relevant shell state cannot be
established statically (dynamic command names, `eval`, `trap`, `printf -v`, `-O`, `--rcfile`,
`source`, `.`). Reason: item 3 of the entry is unbounded, so each new keyword is another
bypass found later; and the cost lands only on projects that hold such a link.

**Not covered by that call, buildable now (a)**: item 1 (case-exact compare under
`nocaseglob`), item 2 (the older bracket reader still in use), item 4 (extglob beside a size
limit is allowed instead of denied). Each has a reproducer in the PR 232 review. They are
plain defects, test-first, then the independent security review. PR 232 is merged
(`384515f38`). The entry says item 1 is also ledgered as N719; check that entry before
building so it is not done twice. I did not re-run the reproducers.

## Owner decisions needed

Ordered by how much work each unblocks. Each can be answered in one line.

- **O1. Sub-agents and in-process teammates of a coordinator or host seat: arm them?**
  (00634 P2, 00635 finding 3.) Options: (A) arm them: under `block` a coordinator's sub-agent
  cannot push, delete or merge, and a host seat's sub-agent cannot run tests; (B) leave them
  unarmed and document it, which leaves both guards bypassable by one dispatch; (C) arm for
  the lane guard only. **Recommend A.** A guard a single Agent call walks round is not a
  guard. Cost: the coordinator does its own pushes and merges; sub-agents hand back commits.
  It also collides with `R-BRANCH-SUBAGENT-STOP-GUARD`, which refuses a sub-agent stop that
  leaves unpushed commits: that guard would need a hand-over route in a coordinator seat.
- **O2. A seat whose `whoami` answers but declares no duty: is the host lane guard armed?**
  Options: (A) quiet with a one-time advisory; (B) armed, as built. **Recommend A.** An
  unreadable probe stays armed as ruled; a readable answer with no duty is a worker on an
  older kit, and B under `block` stops it testing. This loosens what is built, hence asked.
- **O3. Host lane guard: do `docker exec`, `docker compose run` and `ssh host <test>` count
  as lane commands, and is the unparseable residue accepted?** Options: (A) container
  execution counts, `ssh` does not, residue accepted and documented; (B) both count; (C)
  neither. **Recommend A.** A local container still spends the host's CPU; a test over `ssh`
  runs elsewhere and is triage. The static `cc-deny.json` layer is the backstop for the
  residue.
- **O4. Confirm 00634 Q4 and Q5 as built, and the P1 binding?** Cite as a trailing shell
  comment; coordinator seats and unreadable roles armed; one human line approves one act, must
  answer a `Q<n>`, and has a maximum age (a readiness GO still covers many). **Recommend
  yes.** Cost: under `block`, outside a GO window, each push needs its own human line.
- **O5. Q66 housekeeping: confirm in the questions room that `scratch-sweep --apply` and
  `worktree-reap --reap` may run without a terminal when the daemon's proof shows nothing
  unregenerable is lost.** Options: (A) yes, behind the proof and an independent security
  review; (B) no, keep the terminal. **Recommend A.** The residue keeps its typed
  confirmation and an unreadable proof deletes nothing.
- **O6. Relaunch ccy for this session, and build `hooks-screen`?** The running host predates
  PR 223, so the rate-limit answerer's host half is not live and it reads `INERT` without the
  binary. **Recommend yes, at the next natural break.** Cost: the live session restarts.
- **O7. Q16: does "no usage ceiling" retire Plan 00479's ceiling, or only mean readiness sets
  none?** **Recommend "readiness sets none"; keep the ceiling.** Retiring it removes a guard
  this repo still dogfoods. Phase 2b proceeds either way.
- **O8. N720: should the secret-file guard deny a command whose shell state it cannot
  establish, when a protected-file link exists under the project?** Options: (A) yes, fail
  closed; (B) keep listing keywords. **Recommend A.** Cost: `eval`, `source`, `trap` and
  similar are refused in projects that hold such a link.

Q10 (B8 stays dropped) is left off: it blocks nothing and needs no answer unless the owner
wants B8 back.

Not asked, because they are not ready: flipping `human_approval_check` or
`host_seat_lane_guard` to `block`. Each has engineering and peer steps ahead of it, listed
above.

## Work that can start today with no ruling and no peer

1. 00523 Phase 2b: the `cause` field, the gate rule, the no-injection branch, the back-off.
2. 00635 finding 2: the classifier tables, items 1-4.
3. 00634 P3: the generated rule table's wording for the two advise-mode rules. P1's ledger
   and required `Q<n>` once O4 confirms the shape.
4. N720 items 1, 2 and 4 (after checking N719).
5. 00523 PLAN.md:190-191 wording.
