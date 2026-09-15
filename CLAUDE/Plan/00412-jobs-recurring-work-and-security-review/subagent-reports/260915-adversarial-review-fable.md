# Adversarial review of Plan 00412 — fable, 2026-09-15

Brief: find what is wrong with the design before it is built. Every claim
below is tagged **CONFIRMED** (I read the code or ran the command cited) or
**SUSPECTED** (it looks wrong and I could not check). Where a decision is
sound I say so in a line and move on.

Inputs read in full: `PLAN.md`, `DESIGN.md`, the day-file journal, the
closing sections of all four research reports, and the six session-start
handlers the plan names as waiting consumers. One experiment was run, in
`untracked/scratch/ledger-merge-demo/` (left on disk; `git -C`, no `cd`).

## Verdict in five lines

1. **CONFIRMED — D9's "strongest delivery guarantee" is true only for Python
   handlers, not for a Routine.** The daemon cannot execute agent work at
   SessionStart; it injects context. For an agent-run procedure, `session_start`
   is a prompt, exactly like a cron.
2. **CONFIRMED — none of the six sweeps fits the Routine shape.** All six are
   point-in-time whole-tree checks with no cadence, no interval and no run
   record. What they share is `SessionStartHandlerBase`, which they already
   share. The "six waiting consumers" justification does not survive reading
   them.
3. **CONFIRMED — the interval model fits delta-able checks only.** D12's own
   full-only class, and every one of the six sweeps, has point-in-time
   coverage: "tree at X was scanned", which is a pointer with history, not an
   interval. cargo-vet's model works because every audit there is a diff.
4. **CONFIRMED — a yearly append-only ledger merge-conflicts on every pair
   of concurrent runs** (demonstrated), the lock cited as precedent is
   per-checkout, and `journal-append-only` is advisory, not a guarantee.
5. **CONFIRMED — D10 has no `started` state, so `failed` has no writer**, two
   runs at once are invisible, and a whole-repository first run (3,516
   tracked files, 140k lines of `src/` Python, not "~1,700 files") that dies
   at chunk 30 of 50 records nothing.

The rest of this document is the evidence, in the order the brief asked.

## 1. D9 — a trigger is a kind, and `session_start` is "strongest"

### 1.1 CONFIRMED: the daemon cannot run a Routine at SessionStart, only prompt one

A SessionStart handler returns `AdvisoryResult(... context=[...])` — text
injected into the agent's context — e.g.
`handlers/session_start/plan_qa_sweep.py:102-105`. The daemon deliberately
does not run headless Claude: `skill_scan/pipeline.py:5` records the decision
("dispatches an in-session subagent at it … no headless"). So:

- The six sweeps are Python that the daemon EXECUTES inside the hook budget.
  For them the guarantee claim is true.
- A Routine run under Task 2.3 is "hand the agent the procedure"
  (`PLAN.md:130-132`). The daemon can only inject "a run is overdue, run
  `run-routine <id>`". Whether it happens depends on the agent, exactly as with
  a cron tick.

DESIGN.md D9 (`DESIGN.md:194-199`) conflates the two. The honest statement is:
the daemon owns DELIVERY of the prompt at session start (it does not own
delivery of a cron tick); it owns EXECUTION of neither. That is a real but
much smaller advantage than "the trigger with the strongest delivery
guarantee", and it is the difference between "a monthly job may need no cron"
(`DESIGN.md:201-205`) being true and being true only for a session someone
is present in.

### 1.2 CONFIRMED: "a session" is any transcript under 100 bytes

`utils/session_helpers.py:15-43`: a new session is one whose transcript file
is absent or at most 100 bytes. Every `claude` launch, every worktree session,
and (by the same heuristic) every `/clear` qualifies. Five of the six sweeps
use this; `remote_docs_staleness.py:74-77` uses the hook's `source == "startup"` field instead and falls back to the heuristic. So there are already
two definitions of "session start" among the handlers D9 wants to unify; a
`session_start` trigger kind has to pick one and say which.

### 1.3 CONFIRMED: the overdue check needs a state D10 does not have

With D6's overdue gate, a `session_start` routine is silent while in-date —
so a heavy user is not nagged forty times a day while things are fine. The
problem is the other branch. Once overdue, EVERY new session is prompted until
a run is RECORDED, and a whole-repository run takes hours. During those hours
the owner's normal working pattern (agent teams, worktrees — this very session
has three sibling agents) opens more sessions, each of which is told the run
is overdue.

D10's five states (`DESIGN.md:219-227`) are `no record`, `clean`, `findings`,
`failed`, `skipped-with-reason`. There is no `started` / `in progress`. So
nothing in the records can say "a run is underway, do not start another",
which means the overdue check is NOT composable with `session_start` as
designed — it needs a started-record, and that record has to be written before
the run begins, not after it ends. The same missing state is what makes
`failed` unwritable (§4.1).

### 1.4 CONFIRMED: D4's bloat argument and D9 contradict each other

`DESIGN.md:106-111`: "Bloat is not driven by run count. A monthly full sweep
plus per-release deltas is a few dozen records a year". True for a clock
trigger. A `session_start` routine that records its runs (D7: "a run record
proves a run, including a run that found nothing", `DESIGN.md:135-136`) writes
a row per new session — for this owner, dozens per day, thousands per year in
one yearly file. Either session-start routines do not record (then they are
not Routines under D7), or the ledger is the bloat the owner flagged. The
design picks neither.

### 1.5 SUSPECTED: the overdue answer is branch-local

The ledger is in-repo, so "is a run overdue?" is answered from whichever
branch the session is on. A run recorded on a feature branch is invisible to
`main` until merged; a worktree behind `main` reports overdue when `main` is
current. Probably tolerable; not addressed anywhere in DESIGN.md.

### 1.6 CONFIRMED: D6 puts the overdue check in the wrong handler

D6 says the overdue assertion "belongs there" beside `persistent_cron_assertor`
(`DESIGN.md:126-128`). That handler's own docstring says it "asserts by
instruction, never by verification" and reads config only
(`handlers/session_start/persistent_cron_assertor.py:13-19`). An overdue check
IS verification — it reads the ledger. It is a new handler, and Task 2.5
should say so.

### 1.7 Three weeks unopened — sound

Nothing fires, nothing records, the next run's interval widens (D5). That is
the correct behaviour for a repository-scoped obligation with no daemon
present; no objection.

## 2. D2 — the interval model under non-linear history

### 2.1 CONFIRMED: the model needs an ancestry invariant the design never states

`from -> to` composes under git range semantics (`git log from..to` = commits
reachable from `to`, not from `from`) precisely when `from` is an ancestor of
`to`. Then a run on branch B recording `to = C_b`, merged with `--no-ff` into
`M`, is followed correctly by a run `C_b -> M` that covers the main-side
commits B did not see. The merge-base vs first-parent question dissolves once
that invariant holds. But nothing in D2, Task 2.1 (`PLAN.md:122-125`) or Task
2.4 requires `git merge-base --is-ancestor from to`. Without it a run can
record a `from` on an unrelated line and the chain check (`from_N == to_{N-1}`) still passes. Add the invariant to the algebra and its tests.

### 2.2 CONFIRMED: local rebase is allowed, and D16 does not cover it

`DESIGN.md:328-334` says the squash bans keep stored baselines resolvable.
Squash and `gh pr merge --rebase` are blocked, but the guard explicitly
ALLOWS local rebasing: `handlers/pre_tool_use/ancestry_preserving_merge.py:114-116`
— "A LOCAL git rebase … is fine and stays allowed". A run recorded on a
feature branch at `C_b`, followed by `git rebase main` before merging,
rewrites `C_b`; the row (now on the rebased branch) still says `to = C_b`,
which is reachable from no ref once the reflog expires. Before that it
resolves but is not an ancestor of anything on `main`, so the next run's
`C_b..M` silently re-covers the whole branch (over-coverage, then D12's
"baseline unresolvable" escalation after GC). D16 is a true statement about
squash and an incomplete statement about resolvability.

### 2.3 CONFIRMED: a tag endpoint is a mutable pointer, and D2 permits one

`DESIGN.md:50-51`: `from` and `to` are "each a commit SHA or tag". Tags are
mutable refs. No guard covers `git tag -d` or `git tag -f`
(`handlers/pre_tool_use/destructive_git.py` has no tag pattern; the
`update-ref -d` rule at `destructive_git.py:133` is `refs/heads/` only). A row
whose `to` is `v3.64.0` inherits every failure mode D2 rejects a pointer for.
Fix: resolve at record time and store the SHA, optionally the tag beside it
for readers.

### 2.4 CONFIRMED: the interval is the right shape for delta-able checks only

This is the most important finding about the most important decision.

D12 (`DESIGN.md:250-251`) classifies every check as delta-able or full-only.
A delta-able check's coverage is genuinely an interval: "the diff `from..to`
was examined for X". A full-only check's coverage is not: a full sweep at `X`
establishes "tree(X) is clean under Y" and says nothing about any commit
between the previous sweep and `X`. Laying two full-only runs end to end does
not compose into a covered span; the only question they answer is "how old is
the last one", which is the cadence-over-a-pointer query D2 says never to use.

cargo-vet's model (`DESIGN.md:48`) is interval-shaped because every audit
there is a diff between two crate versions. The plan borrows the shape without
the precondition. The consequence for Task 2.1: the algebra must be over
(interval × check-set), and for the full-only subset the "gap" is an AGE, not a
hole. Task 2.4's "a gap between consecutive runs" is well-defined only for the
delta-able subset.

### 2.5 Sound, briefly

The chain check is itself a pointer chain (`from_N` must equal `to_{N-1}`),
and its value is exactly as claimed: it catches a crash, a careless edit or a
mis-chosen `from`, because the mismatch is visible. It does not and cannot
catch a run that records the right SHAs and did not look. D2's failure
argument is correct within that boundary.

## 3. Does it need to exist? The six sweeps, read

| Handler                       | Trigger gate                     | What it checks                                        | Interval? | Cadence? | Run record?                                                               | Fits Routine?  |
| ----------------------------- | -------------------------------- | ----------------------------------------------------- | --------- | -------- | ------------------------------------------------------------------------- | -------------- |
| `plan_qa_sweep`               | `is_resume_session` (`:64`)      | whole plan tree, now (`:98`)                          | none      | none     | none                                                                      | no             |
| `docs_qa_sweep`               | `is_resume_session` (`:75`)      | whole doc corpus, now; also rebuilds an index (`:89`) | none      | none     | none                                                                      | no             |
| `reference_repo_sweep`        | `is_resume_session` (`:94`)      | fetch + ff every governed clone (`:104-107`)          | none      | none     | YES — writes a per-checkout cache on every run, clean included (`:16-19`) | already has it |
| `remote_docs_staleness`       | `source == "startup"` (`:74-77`) | per-document `stale_after` (`:88`)                    | none      | per-doc  | none (the dead-man's switch is on documents, not runs)                    | no             |
| `deployed_artefact_drift`     | `is_resume_session` (`:97`)      | deployed file vs template, now (`:106-110`)           | none      | none     | none                                                                      | no             |
| `secret_file_hygiene_checker` | `is_resume_session` (`:94`)      | git-tracked/ignored/mode of protected paths (`:150`)  | none      | none     | none                                                                      | no             |

(Line numbers are within each file under
`src/claude_code_hooks_daemon/handlers/session_start/`.)

CONFIRMED: not one of the six has a cadence, an interval, or a run record.
The property they share — new-session gate, silent when clean, advisory — is
`SessionStartHandlerBase` plus `is_resume_session`, and they share it today.
The one that DOES record (`reference_repo_sweep`) already implements D4's
split by itself: in-repo nothing, per-checkout cache in `untracked/`. What a
Routine would add to each of them is (a) a run row per session, which is §1.4's
bloat, and (b) an interval they cannot use, per §2.4. Zero of six migrate
without contortion; the plan's own Non-Goals (`PLAN.md:92-95`) already decline
to migrate them, so within this plan the abstraction has exactly one consumer.

**The honest alternative.** `CLAUDE/Routine/security-review/` (no number),
`RUNS/` under it, one row or file per run carrying interval + scope + check
set + outcome, and one new SessionStart handler that reads the last run and
speaks when it is overdue. That is Phase 3 plus Task 2.5. It needs none of
Task 2.2's numbering and scaffolding: Plans are numbered because there are 412
of them and they are created concurrently; there will be a handful of Routines
ever, created by hand. Numbering solves a collision that cannot occur at that
population. If a second consumer appears with a real interval, generalise
then, from a working instance.

## 4. Missing cases

### 4.1 CONFIRMED: `failed` has no writer

`DESIGN.md:226`: `failed` = "started and did not finish". If the writer died,
who writes the row? Nothing in the design starts a record before the run.
The fix is a two-row protocol: append `started` (with `from`, intended `to`,
scope, definition hash) before the run; append the outcome after. A `started`
row with no matching outcome past grace IS `failed`, inferable by the QA sweep
(Task 2.4) without anyone writing it. The same row is what §1.3 needs to see a
run in progress.

### 4.2 CONFIRMED: concurrent appends to one yearly ledger conflict in git

Demonstrated in `untracked/scratch/ledger-merge-demo/`: seed `RUNS-2026.md`,
append one row on `feature`, one row on `main`, `git merge --no-ff feature` →
`CONFLICT (content): Merge conflict in RUNS-2026.md`. Two runs anywhere near
each other on different branches — the worktree pattern this project uses —
conflict every time. Per-run files never do.

The precedent DESIGN.md offers for concurrency (`DESIGN.md:359-360`, "the lock
that `mkplan.bash` already uses") is an atomic-`mkdir` lock on
`$plan_dir/.mkplan.lock` (`CLAUDE/Plan/mkplan.bash:58,218`). It is per
checkout. Two worktrees are two checkouts with two locks; it serialises
nothing between them.

### 4.3 CONFIRMED: the "append-only guarantee" is an advisory

D14 and Q2 lean on the journal subsystem's append-only property
(`DESIGN.md:288-289, 355-356`). `plan_qa/checks/journal_append_only.py:13-15`:
"Advisory FOREVER (Decision 4) … `mode: block` never escalates this check",
and it is Stage 1 (edit-time) only. A ledger row can be rewritten with a
one-line advisory and no record. For a plan journal that is the right call;
for a run ledger whose entire value is that a `clean` row cannot later become
a different `clean` row, it is not a guarantee at all. Either the Routine
ledger gets its own commit-gate check, or per-run files get archive-style
immutability once committed.

### 4.4 CONFIRMED: a changed definition is not detectable from the rows

D12 lists "criteria or tooling changed" as forcing a full run
(`DESIGN.md:252-253`), but no row records which definition it ran under. Fix:
each row carries the definition's blob hash (`git rev-parse HEAD:<routine>/ROUTINE.md`); consecutive rows with different hashes mark the
boundary across which intervals are not comparable, and the QA sweep can
demand the next run be full. Cheap, and absent.

### 4.5 CONFIRMED: no lifecycle for the Routine itself

D10 is per-run. The audit report's §8.1 says the Routine-level axis is
active / paused / retired (`260915-audit-plan-machinery-sonnet.md:308`).
DESIGN.md has no such vocabulary. A retired routine with a live overdue check
nags forever, and D11 requires that nagging to be loud. `paused-with-reason`
and `retired` are needed before the first overdue check ships.

### 4.6 Cadence change — minor

Only the latest row matters to "overdue", so changing cadence is harmless
there. Any D10-style "N passing runs over N periods" query is ambiguous across
a cadence change unless each row records the cadence in force. Note it; do not
design for it yet.

### 4.7 A run recorded on a branch never merged — consistent

The row lives and dies with the branch. No objection.

## 5. One plan or three?

CONFIRMED, from the task list: Phase 2 (`PLAN.md:120-142`) and Phase 3
(`PLAN.md:144-160`) share nothing but the ledger format. Task 3.4 is
open-ended by construction — every confirmed defect spawns a Detector and a
fix under Defence Before Fix — which is the shape of Plan 00409, not of a
framework build.

There is also an internal contradiction. D14 is DECIDED: share `paths.py`,
the journal subsystem and the numbering layer rather than fork
(`DESIGN.md:273-292`). No task implements that extraction; Task 2.2 says
"mirroring `mkplan.bash`'s atomic git-counter numbering" (`PLAN.md:127-128`),
which is the fork D14 rejects. Either add the refactor tasks (the audit report
sequences them at `:403-412`) or downgrade D14.

Recommended split: (A) the security-review routine on a minimal record, with
its overdue handler — Phase 3 + Task 2.5, this plan; (B) the generic tree,
only when a second interval-shaped consumer exists; (C) the D14 refactor,
which only B needs.

## 6. The four decisions just taken

### Q1 — Routine: sound

Collision argument holds. Textual drift to fix: `DESIGN.md:137` and `:207`
still say `run-job`; `PLAN.md:64` says `run-routine`; D13 and D14 still say
"Job" throughout.

### Q2 — yearly append-only ledger: the strongest case against

- It conflicts on concurrent runs (§4.2, demonstrated).
- Its append-only property is advisory (§4.3).
- The claimed benefit is not differential. The gap query reads consecutive
  rows; `sorted(RUNS/*.md)` reads consecutive files. The overdue query reads
  the last row; it reads the last file. Neither is "a read of one file" in a
  way that matters.
- The research recommended the other shape: "a Run should be named by the
  interval it covers, not by the date it was executed"
  (`260915-research-jobs-prior-art-sonnet.md:606-611`).
- The two costs DESIGN.md lists as accepted (`:357-360`) — contention and
  unreferenceable runs — are the two that bite; the mitigation named
  (`mkplan`'s lock) does not apply across checkouts.

Recommendation: per-run files, `RUNS/<date>-<from7>-<to7>.md`, interval and
scope in frontmatter, composition done by the sweep. If the ledger stands,
state up front that a merge conflict in it is routine and give the resolution
rule (keep both rows, ordered by `started` time).

### Q3 — DBF conformance declared with a known-gap record: sound

Clause 9.2 reading is consistent with what Task 1.2 vendored. One caution
from D8 itself: clause 3.2 forbids a test as Detector, so Task 2.1's "failing
tests first" is TDD for the algebra, fine, but Task 3.4's Detectors must land
in `scripts/qa/` or as handlers, never only in `tests/`. The plan says
"blocking Detector"; make the location explicit so it is not re-litigated.

### Q4 — whole repository: not achievable as one run under this model

CONFIRMED counts (`git ls-files` at HEAD `2f6d1ae4`): 3,516 tracked files, not
"roughly 1,700" (`DESIGN.md:400`; origin of that figure unknown). Of those:
561 `src/` Python files totalling 140,167 lines; 1,075 test files; 107 shell
scripts (the `bin/` wrappers, `mkplan.bash`, install); 1,453 markdown files —
and for an agent-driven tool the agent prompts, skills and generated guidance
ARE attack surface, so "whole repository" cannot exclude them silently.

No sub-agent holds 140k lines of Python. A whole-repository run is therefore
necessarily many dispatches, each over a path subset. The model has one row
per run and no chunk record, so (a) the run that dies at dispatch 30 of 50
records nothing (§4.1) and restarts from zero, and (b) the record has no
scope dimension to say which paths a dispatch covered (§2.4). Two ways out,
and the plan must pick one:

1. The first "run" is a SERIES of runs, each with a declared path scope, all
   at the same `to` SHA; composition for the baseline is over path scope at a
   fixed commit, not over commits. This needs the scope dimension in the
   algebra.
2. Define what "whole" means for THIS repository's trust boundaries — the
   handlers that spawn shells, the socket server, config loading, install and
   upgrade scripts, remote-docs and reference-repo fetchers, the `bin/`
   wrappers — record THAT as the scope, and treat the remainder as explicitly
   out of the baseline. D3 says a scope must be stated; "whole" is not a
   statement of scope.

## 7. Smaller items

- `dispatch_declaration` recognises only `<plan_dir>/\d{5}-` as a report
  destination (`handlers/pre_tool_use/dispatch_declaration.py:127`). A Routine
  tree is unrecognised; sub-agent reports for a run get pushed toward a plan
  folder. Not in any task.
- D13's second trap (goal ledger never releases a Job) only bites if the
  Routine document is literally `PLAN.md` with `**Status**: In Progress`:
  `handlers/post_tool_use/goal_injection.py:180-182` keys on both. It will not
  be. D13 overstates; the first trap (staleness inverts) stands.
- D7's finding that two of three live crons are undeclared is upstream of
  this plan and untouched by it; fine, but Task 2.5 should not assume the
  assertor sees the routine's cron.
- Resolve `from`/`to` at record time even when the agent supplies a branch
  name; never store a branch name (same reasoning as §2.3).

## 8. What I could not verify

- That Claude Code emits SessionStart with an empty transcript on `/clear`;
  I inferred it from the 100-byte heuristic, not from the harness.
- How soon a rebased-away commit actually becomes unresolvable here (reflog
  expiry defaults to 90 days; nothing in the repo pins it).
- Where "~1,700 files" came from. `src` + `tests` Python is 1,636, which is the
  closest sum I found; if that is it, the figure omits shell, YAML, workflows
  and markdown.
- Whether `cmd_release_slate_check` (`daemon/cli.py:3227`) is a gate a
  `release` trigger could attach to; I located it and did not read it.
- Whether the owner intends markdown (agents, skills, generated guidance) to
  be inside the security scope. I argued it must be; that is a scope call.
- I ran no test suite and changed no code; the one artefact I created is the
  scratch repository under `untracked/scratch/ledger-merge-demo/`.
