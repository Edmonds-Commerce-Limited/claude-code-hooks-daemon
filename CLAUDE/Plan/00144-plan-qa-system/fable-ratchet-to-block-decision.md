# Ratchet-to-block decision: `commit_gate_mode` (Plan 00144) and `journal-dayfile-naming` (Plan 00163)

Decision record for the sole open task in each of two Dormant plans. Both
plans parked on the same sentence — "the blast radius is every installing
project, so this is not an agent's call" — and this document tests that
sentence against the repository rather than repeating it. The companion
pointer lives at
`CLAUDE/Plan/00163-plan-journalling/fable-ratchet-to-block-decision.md`.

Nothing here has been implemented: no config edited, no task ticked. The
plan closer acts on the decisions; this document is the evidence they rest on.

## Question 1 — Plan 00144 Task 4.4: flip `plan_workflow.qa.commit_gate_mode` from `warn` to `block`

### Decision

**Yes — and it already happened.** Plan 00343 delivered exactly this task on
commit `de978425`; the remaining work on 00144 is to record that delivery and
close, not to decide anything.

### Measured evidence

1. **The flip is live in this repository.** `.claude/hooks-daemon.yaml:1174`
   reads `commit_gate_mode: block`, with the measurement that justified it in
   the comment directly above (`:1166-1173`). `git log -S'commit_gate_mode: block' -- .claude/hooks-daemon.yaml` returns one commit: `de978425`
   ("Plan 00343 Phase 3-4: a commit is answerable for the plans it touches").
2. **Task 4.4's own wording is satisfied by that commit.** `PLAN.md:294-295`
   says "flip THIS repo's config to `block` (separate commit)". 00343 Task 4.2
   (`CLAUDE/Plan/Completed/00343-plan-qa-commit-gate-warn-to-block/PLAN.md:197-205`)
   did it in a separate commit, restarted the daemon, and confirmed
   `plan-qa --check-staged` clean afterwards.
3. **The precondition 00144 set — "when clean" — was met by measurement, not
   assertion.** 00343 replayed every commit-stage check over 253 commits: 18
   denials, 7 false positives (39%), all one shape (whole-tree checks blaming a
   commit for inherited state). Six checks were narrowed to "BLOCK what this
   commit introduced, ADVISE what it inherited"; the identical replay then
   produced 11 denials and zero false positives (00343 `PLAN.md:71-105`,
   `:186-195`). The seven commits that stopped being denied are the seven
   false positives by hash; nothing was traded away.
4. **The gate has run in `block` since, without incident.**
   `git rev-list --count de978425..HEAD` = 1,049 commits, of which 642 touch
   `CLAUDE/Plan`. The daemon's verdict log (`untracked/logs/hooks/verdicts.jsonl`,
   a rolling sample of 31,202 verdicts across 9,513 sessions) records
   `plan-qa-commit-gate`: **444 allow, 0 deny**.
5. **The tree is clean today.** `bin/hooks-daemon plan-qa --sweep` on this
   checkout: `Plan QA: 0 findings — plan tree is clean.` across 407 plan
   folders (root + `Completed/` + `Cancelled/`).
6. **The blast-radius premise in the blocker is wrong for this task.**
   `.claude/hooks-daemon.yaml` is this project's own file; it is not deployed
   to clients. What clients receive is the MODEL default at
   `src/claude_code_hooks_daemon/config/models.py:678-681`, which is still
   `warn`. Flipping this repo's key touched nobody else — which is why 00343
   could do it without a human gate, and did.

### Migration consequence for an existing installing project

None. Task 4.4 changes a per-project config key in this repository. A client
running the shipped default keeps `commit_gate_mode: warn`
(`models.py:679`), and the v3.32.0 manifest's promise — "warn-first; flip to
block when clean" (`CLAUDE/UPGRADES/config-changes/v3.32.0.yaml:29`, `:60-62`)
— remains a promise about the default, not about this repository.

### The separate question 00144 does not own: the shipped default

The blocker's fear belongs to a different change: flipping the MODEL default
so every client without an explicit key starts denying commits on upgrade.
That is real, and it is not Task 4.4. Recording the position so it is not
re-derived:

- **What is already in clients' favour.** The 00343 narrowing is code, and
  ships. A client with an accumulated-drift tree (00144's own origin story
  was a client with 54 folders and 41 index rows, `PLAN.md:16-19`) would be
  denied only for breakage a commit itself introduces — with two deliberate
  exceptions. `structure-archive-dirs` still blocks unconditionally on "no
  README index" and "no completed archive" (00343 `PLAN.md:177-182`),
  because without them half the check suite silently no-ops. A client whose
  plan directory lacks either would have every plan-touching commit denied
  until they create it; the sweep has been advising them of exactly that
  since v3.32.0.
- **What is missing.** Every false-positive measurement is against THIS
  repository's commit habits. No client tree has been replayed. That is a
  measurement gap, not an unknowable.
- **How a default change is recorded here.** Precedent exists:
  `CLAUDE/UPGRADES/config-changes/v3.26.0.yaml:8-32` changed the
  `plan_workflow.enabled` model default with a `changed:` entry and a
  migration note. A default flip of `commit_gate_mode` takes the same shape,
  with the one-key escape hatch (`commit_gate_mode: warn`) in the note.
- **Recommendation.** File it as its own plan when wanted, following 00343's
  replay method against at least one non-dogfood tree. Do not fold it into
  00144: that plan's task is done, and a nine-week-old blocker sentence should
  not keep a delivered feature Dormant.

### Strongest argument against, stated fairly

"Zero denials in the verdict sample proves nothing — the sample is roughly a
day, and a gate that never fires is either working perfectly or matching
nothing." True on its own. The reply is that the gate has three independent
proofs of teeth, none of them from the sample: the 253-commit replay produced
11 true-positive denials it would have issued; 00343's journal records the
gate catching its own plan within a minute of going live (00343
`JOURNAL/00343-Journal-26-09-07.md:196-201`); and the shape of finding that
motivated the whole exercise — an advisory that fired on commit `923fd583`
and was scrolled past for five days (00343 `PLAN.md:22-25`) — is exactly what
`warn` mode permits and `block` mode does not.

### Does a genuine human gate remain?

**No.** The task was executed nine days before this review, by a plan that
measured before acting, and the measurement has held. Nothing in the
remaining work turns on risk appetite or on a commitment to users: this
repository's config is this repository's. The only human-adjacent item is the
shipped default, which is (a) out of 00144's scope and (b) a measurement
question with a defensible technical procedure, not a gate.

### Stale artefacts the closer should correct (not edited here)

- `CLAUDE/Plan/00144-plan-qa-system/PLAN.md:3-4` — Status/Blocker describe
  a warn-mode gate that has not existed since `de978425`.
- `CLAUDE/Plan/00144-plan-qa-system/PLAN.md:294-295` — Task 4.4 is delivered
  by 00343; tick it citing `de978425`.
- `CLAUDE/Plan/README.md:79` — row says "blocked only on a human go/no-go".
- `.claude/hooks-daemon.yaml:571` — the `plan_qa_commit_gate` handler comment
  still reads "Warn-first rollout (plan_workflow.qa.commit_gate_mode: warn)"
  and contradicts `:1174` in the same file.

## Question 2 — Plan 00163 Task 3.2: escalate `journal-dayfile-naming` to BLOCK via `journal.mode: block`

### Decision

**Yes, for this repository's config** (`plan_workflow.qa.journal.mode: block`
at `.claude/hooks-daemon.yaml:1190`). The shipped model default
(`models.py:532-535`, `advise`) stays where it is, for the same reason
`commit_gate_mode`'s default did after 00343: dogfood first, default later,
and only with a `changed:` manifest.

### Measured evidence

1. **Zero findings, three ways.**
   - Sweep: `journal-dayfile-naming` is registered at SWEEP as well as EDIT
     (Plan 00230; `plan_qa/checks/journal_dayfile_naming.py:17-19`, `:101-104`),
     so today's `0 findings` across 407 plan folders covers it. A re-check
     outside the daemon agrees: 306 day-files in 256 `JOURNAL/` directories,
     0 grammar mismatches, 0 embedded-number mismatches with the enclosing
     folder.
   - Whole git history: 325 distinct journal day-file paths ever added, 0
     with a non-conformant name. 234 renames and 19 delete/add pairs are all
     archive moves that preserve the basename (every "deleted" file still
     exists under `Completed/` or `Cancelled/`). There has never been a
     corrective rename of a misnamed day-file.
   - Verdict sample: `plan-qa-edit` 273 allow / 9 deny. The check is ADVISE
     in this repo's config so it cannot have produced any of the 9 (only
     `Level.BLOCK` findings deny, `handlers/pre_tool_use/plan_qa_edit.py:209-210`);
     they belong to other block-level checks.
2. **Zero findings means zero false positives are POSSIBLE under block on this
   tree.** A check that has never fired on 325 real files cannot have a
   false-positive rate to worry about; every conformant name passes by
   construction. The ratchet costs nothing measurable.
3. **The benefit is real precisely because the failure is silent downstream.**
   A malformed day-file name is dropped by `_scan_journal`
   (`plan_qa/model.py:405-410`: only well-formed names contribute to
   `latest_journal_date`), and `journal-dayfile-is-today` returns nothing for
   an unparseable name (`plan_qa/checks/journal_dayfile_is_today.py:78-80`).
   So a misnamed file is invisible to the freshness nudge, invisible to the
   today-only guard, and reachable only by this one check. Under `advise` it
   is a nudge an agent mid-write is free to scroll past — the exact failure
   Plan 00341 documented for the commit gate. Under `block` it is denied at
   creation, the one moment a rename is free.
4. **The subordination rule does not shrink this decision here.**
   `journal.mode: block` only denies when `edit_mode` is also `block`
   (`models.py:499-506`; enforced at `plan_qa_edit.py:209-210`). This repo
   has `edit_mode: block` (`.claude/hooks-daemon.yaml:1165`) and so does the
   shipped default (`models.py:674-676`). Here the ratchet is a real one.
   For any client that has chosen `edit_mode: warn`, the same rule degrades
   it to advisory automatically — the blast radius self-limits.
5. **A stricter sibling already ships BLOCK by default and has been lived
   with.** `today_only_mode` defaults to `block` (`models.py:552-558`), fires
   on every stale-day append (a far more common event than a malformed
   name), and the config comment at `.claude/hooks-daemon.yaml:1195-1200`
   records the one time it had to be relaxed for a redaction pass — visibly,
   in the config, with the reason. That is the escape hatch working as
   designed, not a guard being quietly switched off.
6. **The hook cannot see the scaffolder.** `mkplan.bash` creates the first
   day-file with `mkdir`/`cat` (00163 `PLAN.md:348-355`), which no PreToolUse
   handler observes. The block therefore only ever touches a day-file an
   agent hand-creates with `Write`/`Edit` — the case where a wrong name is
   plausible and a denial is cheapest.

### Migration consequence for an existing installing project

None from this decision: `.claude/hooks-daemon.yaml:1190` is this repo's
key, and the shipped default stays `advise`. Were the DEFAULT later flipped,
a client on `edit_mode: block` would be denied when hand-writing a `.md`
directly inside `JOURNAL/` whose name is not `NNNNN-Journal-YY-MM-DD.md`; a
client on `edit_mode: warn` would see no change. The one-key escape hatch is
`journal.mode: advise`.

### Strongest argument against, stated fairly

"A check that has fired zero times in 325 files is not protecting anything;
ratcheting it is ceremony, and every ratchet is one more key somebody will
one day flip to `advise` and forget — `guard-self-disablement-unwatched`."
The first half is the honest cost-benefit: the demonstrated benefit is zero.
Two replies. First, the asymmetry: the cost is also zero, and the failure it
guards is silent (evidence point 3), which is the category where advisory
enforcement has already been shown not to work. Second, the self-disablement
worry is now partly watched: `guard_config_commit_gate`
(`.claude/hooks-daemon.yaml:590-592`, Plan 00412 class 2a) reports guard
weakenings at commit time, so a later `block → advise` in this repo is
named in the commit, not lost. There is also a documentation-honesty cost to
NOT deciding: `models.py:493-495` and 00163 Decision 4 both promise a ratchet
"after a clean dogfood period"; 00343's journal called that shape "a document
promising a state that does not exist" and the same applies here.

A second fair objection: a project might legitimately keep a non-day-file
(`JOURNAL/README.md`) directly inside `JOURNAL/`, and `block` would deny it.
The grammar already answers this — anything nested one level deeper is
journal territory the checks leave alone (`plan_qa/checks/common.py:295-299`)
— and no such file exists in this tree today, so it is a documentation
point for `CLAUDE/PlanJournalling.md`, not a reason to hold the ratchet.

### Does a genuine human gate remain?

**No.** Every input is in the repository: the fire rate (zero), the
false-positive ceiling (zero), the silent-failure mechanism it closes, the
self-limiting subordination rule, the escape hatch, and the shape of the
decision (dogfood config now, default unchanged). No commitment to users is
touched because the shipped default does not move. Task 3.2's own text says
"decide with the user"; the deferral was reasonable in v3.40.0 with no
evidence, and is not reasonable now that the evidence is unanimous.

### Stale artefacts the closer should correct (not edited here)

- `CLAUDE/Plan/00163-plan-journalling/PLAN.md:190-193` — Task 3.2; the
  outcome above is the Technical Decision it asks to have recorded.
- `CLAUDE/Plan/00163-plan-journalling/PLAN.md:408-410` — says "Plan stays
  **In Progress** until that decision lands" while the header (`:3`) reads
  Dormant.
- `CLAUDE/Plan/README.md:73` — row still names Task 3.2 as open.

## What the closer does with this (procedure, not implementation here)

1. **00144**: tick Task 4.4 citing `de978425` and Plan 00343; flip Status to
   Complete; `git mv` to `Completed/` with the README row and stats in the
   same commit (the gate this plan built will insist on that). Fix the
   `.claude/hooks-daemon.yaml:571` comment in the same stroke.
2. **00163**: set `plan_workflow.qa.journal.mode: block` at
   `.claude/hooks-daemon.yaml:1190`, restart the daemon and verify RUNNING,
   run `bin/hooks-daemon plan-qa --sweep` (expect 0 findings), record the
   Technical Decision in `PLAN.md`, tick Task 3.2, close and archive as
   above. Journal the flip in `JOURNAL/00163-Journal-<today>.md`.
3. **Neither plan** changes a shipped default. If the owner wants
   `commit_gate_mode` or `journal.mode` to default to `block` for clients,
   that is a new plan with a `changed:` manifest entry (precedent
   `v3.26.0.yaml`) and, for the commit gate, a 00343-style replay on at least
   one client tree first.
