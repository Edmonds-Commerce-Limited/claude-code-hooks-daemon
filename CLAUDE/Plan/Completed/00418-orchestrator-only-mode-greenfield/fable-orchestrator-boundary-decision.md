# Decision: the orchestrator-only boundary, and the two promotions

Supporting document for Plan 00418 Tasks 2.1 and 2.2. Decided from the
recorded simulation data in `untracked/logs/hooks/verdicts.jsonl`, re-derived
from the raw log rather than from `PLAN.md`'s summary. Decision only — nothing
here was implemented.

## Ruling 1 (Task 2.1) — where the boundary goes

**DECISION: the denial boundary is drawn on tool identity — `Write`, `Edit`
and `NotebookEdit` (and any other file-mutating tool outside the coordination
set) are denied on the main thread; `Bash` is never denied and stays
record-only with its command-head label; the one path exemption is the plan
directory (`plan_workflow.directory`, currently `CLAUDE/Plan/`), whose
`PLAN.md`/`JOURNAL/`/supporting documents the project's own workflow makes the
lead's to write.**

### Evidence

The plan's headline figures were reproduced against the raw log and every one
of them is an ALL-SESSIONS cumulative total that blends synthetic hook events
into the main thread's record:

| PLAN.md figure                        | Moment the all-sessions total hit it | Composition at that moment (real main-thread session vs synthetic)                              |
| ------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------- |
| 437 "first session" (PLAN.md:120)     | 2026-09-15 18:48:04                  | real 151 (Bash 114, Edit 29, Write 6); synthetic 286 incl. all 4 `Artifact` fires               |
| 1,385 "second sample" (PLAN.md:142)   | 2026-09-15 21:38:38                  | real 879 (Bash 606, Edit 198, Write 47); synthetic 506, of which 203 of the 250 `Write` records |
| 1,787 "every one allow" (PLAN.md:189) | 2026-09-15 22:33:11                  | real 1,066; synthetic 721                                                                       |

Tool split at the 1,385 moment is exact to the plan — Bash 895, Write 250, Edit
205 — so the plan quoted `bin/hooks-daemon verdicts` correctly; that command
has no per-session filter (`verdicts --help`: only `--log-file`/`--json`;
`daemon/verdict_report.py` never reads `session`). The synthetic producers are
`daemon/playbook_harness.py:429` (`session_id: playbook-probe-<run>-<n>`, one
session per probe, 691 distinct values at the snapshot) and
`tests/integration/test_forwarder_socket_stdin.py:39` (`socket-stdin-test`),
plus 78 records with no `session_id` at all, which `controller.py:996` labels
`default`. They recur every hour with the QA runs (140–280 per hour through the
night), so as of this reading 2,717 of 5,396 records (50%) are synthetic.

Two consequences for the plan text: the "437 first session" and "1,385 second
sample" are the SAME real session (prefix `9679b063…`, continuous from
17:59:39 on 15 Sep) read at two moments, not two sessions; and `Read` being
zero is correct but the `Artifact` count was never main-thread work.

**The plan's arithmetic conclusion survives on clean data, and strengthens.**
Real session only, post-classifier Bash at the 22:34 snapshot (432 calls):

| Measure                                             | PLAN.md (blended) | Real session only |
| --------------------------------------------------- | ----------------- | ----------------- |
| Distinct labels                                     | 171               | 197               |
| Compound (label carries `+`)                        | 325 (79%)         | 399 (93%)         |
| Most common label                                   | 9.5%              | 9.0%              |
| Labels needed to cover 50%                          | 21                | 23                |
| Labels seen exactly once                            | 62%               | 72%               |
| Labels mixing a read-only head with a mutating head | not measured      | 95 (22%)          |

The synthetic fires are single-head fixtures (`echo` 495, `git commit` 184,
`git status` 66 across the synthetic set), which is what pulled the blended
compound share DOWN to 79%. On the real record nine calls in ten run several
commands, and one in five straddles the line inside one invocation
(`set+git add+git commit+…`, `set+python+echd-capture`). No per-call verdict on
a Bash head can be right, so Bash cannot be a denial surface. That is
arithmetic, as the plan says, and it is not the owner's to re-decide.

**`Write`/`Edit` are classifiable, and the transcript says what they were.**
The real session to this reading: Edit 705, Write 111. The handler's
`additionalContext` line carries the path, so the transcript classifies them
by top-level directory:

| Where the main thread wrote                                                                         | Edit       | Write     |
| --------------------------------------------------------------------------------------------------- | ---------- | --------- |
| Implementation (`src/`, `tests/`, `scripts/qa/`, `.claude/project-handlers`, `.claude/ccy`, config) | ~515 (73%) | ~64 (58%) |
| Plan/docs tree (`CLAUDE/Plan`, `CLAUDE/Security`, `CLAUDE/Routine`, `CLAUDE/UPGRADES`)              | ~172 (24%) | ~22 (20%) |
| `untracked/scratch`                                                                                 | 13 (2%)    | 26 (23%)  |

Three quarters of the main thread's edits are implementation — the exact work
the plan exists to push to subagents (PLAN.md:13-14). That settles the
journal's two readings (JOURNAL 18:50 entry) in favour of the second: the lead
IS doing work it should delegate.

The plan-tree quarter is the reason for the one exemption. `DirectoryRoles.md:39`
gives the plan folder to `PLAN.md`, supporting docs, `JOURNAL/` and
`subagent-reports/`; `dispatch_declaration` routes a subagent's output to
`subagent-reports/`, which leaves the rest of the folder as the coordinator's.
Denying those writes would buy no context hygiene (a journal entry is small)
and would push the lead into `cat >> JOURNAL` heredocs, which is exactly the
route this project's own `CLAUDE.md` says bypasses every content guard. The
exemption is a path under a key that already exists in config
(`plan_workflow.directory`); it is deterministic, unlike any Bash heuristic.
`untracked/scratch` is NOT exempt: nothing designates the lead its author, and
the blocking record will show whether that hurts.

### Cost, and who bears it

Roughly 580 main-thread implementation writes per long session become either a
subagent dispatch or a Bash redirect. The owner bears it in every session in
this repository. The hourly `issue-sdlc` tick already delegates implementation
to a sub-agent (`.claude/skills/issue-sdlc/SKILL.md:21`) but lists `Write` and
`Edit` in its `allowed-tools` (line 7), so any direct write in its main-thread
steps would be denied and has to be checked before blocking is enabled.

### Strongest argument against

The gate is porous by construction: Bash stays open, so `cat <<EOF > file`
writes the file the `Write` denial refused, and `cat` already appears as a
head 72 times in the real session's classified Bash. The answer is that this is
a BEHAVIOURAL gate, not a security one — its purpose is a clean lead context,
and the head record is precisely the instrument that shows evasion (`cat`,
`tee`, `<other>` rising after enable). If that happens the boundary is wrong
and the record will say so; it does not argue for denying Bash, which the
arithmetic has ruled out.

### Human gate?

**None.** Bash is excluded by arithmetic; `Write`/`Edit` are included by the
plan's own premise plus a 73% implementation share; the plan-directory
exemption follows from the project's written directory roles. Every input is
in the repository.

## Ruling 2 (Task 2.2a) — promote to blocking?

**DECISION: yes — add an opt-in `block` mode to the PROJECT handler, scoped
exactly to Ruling 1's boundary, with simulate remaining the default; enable it
in this repository once two technical preconditions are met. Nothing ships to
the library under this ruling.**

### Evidence

- The progression was the owner's own ruling: "dog food as a project level
  handler initially … with a WARN/Simulated mode instead of block to start
  with" (PLAN.md:41-42). Simulate was the START, and Goal 3 (PLAN.md:64-65)
  says the block decision is made from the record. The record now exists and
  points one way: 73% of main-thread edits are implementation.
- The handler has no deny path at all (`orchestrator_simulate.py:22-28`;
  pinned by `test_handle_never_returns_deny_attribute_anywhere`). A block mode
  is therefore a build with its own RED test, not a flag flip.
- Non-Goal "Blocking by default, ever" (PLAN.md:74-75) is honoured: the mode is
  opt-in and the default stays simulate.

### The two preconditions (technical, not gates)

1. **The record must be filterable to real sessions before a deny count is
   quoted.** `bin/hooks-daemon verdicts` cannot separate the main thread from
   `playbook-probe-*`, `socket-stdin-test` and `default`. Every figure in
   PLAN.md Task 2.1 is contaminated by this, and a blocking record read the
   same way would count the acceptance suite's probes as denied agent work.
2. **Blocking must be proven not to fire on synthetic probes.** The playbook
   builds events with no `agent_id` (`playbook_harness.py:425-431`), so a
   block mode as naively written would DENY every playbook `Write`/`Edit`
   probe — 280 `Write` probes at the snapshot — and, under
   most-restrictive-wins, turn other handlers' expected ALLOW outcomes into
   failures. The acceptance harness would go red on the day blocking was
   enabled. Whatever the discriminator (the harness marking its events, or the
   handler recognising a probe), it needs a test before enable.

Both are builds. Neither turns on anything outside the repository.

### Cost, and who bears it

As Ruling 1: the owner's sessions and unattended cron ticks in this repo. The
reversal cost is one file rename (`PROJECT_HANDLERS.md:470-473`: prefix the
file with `_`) or the opt-in switch turned back off. Nothing is destroyed by a
wrong answer; the failure mode is friction and, in an unattended session, a
turn spent dispatching rather than editing.

### Strongest argument against

The evidence base is ONE session of ONE user in ONE repository — the "two
samples" are the same session — and enabling a deny on that is enabling it on
an anecdote. Fair. It is also why the promotion stays a project handler and
why preconditions 1–2 come first: the blocking record from this repo, over
several real sessions and cleanly filtered, is the evidence the NEXT decision
(Ruling 3) needs, and it cannot be gathered without enabling.

### Human gate?

**Not one, by the brief's own test.** The question "should the owner's own
main thread be denied direct implementation writes in the dogfood repo" has a
defensible technical answer from the record (73% implementation), the owner
has already ruled the direction, the change touches no other project, and it
is reversible in one rename. The owner's tolerance for friction is the only
thing not in the repository, and a one-line veto is cheaper than a gate.

## Ruling 3 (Task 2.2b) — promote to the shipped library?

**DECISION: no — not from this record and not in this plan. Revisit only with
a filtered blocking record from this repository spanning several real
sessions, and treat THAT revisit as the genuine owner decision it is.**

### Evidence

- PLAN.md:70-72 already lists library shipping as a Non-Goal of this plan, and
  the owner's standing ruling is that new gates dogfood as project handlers
  first. Ruling 2 has not yet produced a blocking record, so the precondition
  for the later decision does not exist.
- The simulation record is not evidence about client projects: one session
  (`9679b063…`), one user, one workflow (agent-team orchestration with a ccy
  supervisor and hourly ticks). A client project with no subagent workflow
  would see a denial on every write, which is the "agent that cannot work at
  all" failure PLAN.md:75 names.
- PLAN.md:77-80: upstream delegate mode may make the whole handler redundant.
  A project handler is cheap to delete; a library handler carries docs,
  config manifests, upgrade guides and every client's config-optimiser
  surface.

### Cost, and who bears it

Any client who wants orchestrator-only mode waits; none has asked (issue #14
is the owner's). The project bears nothing.

### Strongest argument against

The distinction "project handler changes no installing project's gate surface;
library handler changes every one" is softened by the handler being opt-in and
disabled by default — a client that never enables it sees only a docs entry.
True, and still not enough: the maintained surface, the upgrade-guide entry
and the commitment to keep it correct against upstream changes are real even
when the gate is off, and this record cannot yet justify them.

### Human gate?

**Yes — but it is not open yet, and it is the only genuine one in this plan.**
When a filtered blocking record exists, the owner will be asked exactly this:
*Do you commit every installing project to an opt-in orchestrator-only gate
that this repository's own record supports, knowing that (a) the record comes
from one repository and one workflow, (b) upstream delegate mode may make it
redundant, and (c) shipping it means maintaining it for users indefinitely?*
That is a commitment to users and a risk appetite, and nothing in the
repository can answer it. Today the answer is "not yet" on evidence, and that
part is technical.

## Corrections the plan owes its own text (no edits made here)

- PLAN.md:120-126, 141-153, 177-179, 189: the totals are all-sessions and
  include synthetic fires; the two "samples" are one session. The conclusion
  (Bash unclassifiable by head) stands and is stronger on real data.
- PLAN.md:163 "455 calls needing no interpretation": 245 were real at that
  moment (Edit 198, Write 47); 203 of the 250 Writes were playbook probes.
- The empirical "all allow" claim is correct as of this reading: 5,396
  `orchestrator-simulate` records, all `allow`, against a control of 7,375
  `deny` records from other handlers in the same log.

Scratch scripts used, kept for re-running:
`untracked/scratch/analyse_orch_verdicts.py`,
`untracked/scratch/analyse_orch_snapshot.py`,
`untracked/scratch/analyse_orch_timeline.py`; outputs alongside them.
