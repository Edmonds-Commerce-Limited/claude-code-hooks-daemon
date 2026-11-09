# Plan 00574 critique v1: adversarial review of PLAN.md and DESIGN.md

Supporting doc for [PLAN.md](PLAN.md) and [DESIGN.md](DESIGN.md). Reviewer
brief: find what is wrong, missing, over-built or self-defeating. Findings are
ranked by severity, each with a concrete fix. Code citations are against `main`
at review time.

## Verdict

The goal is sound, but the plan as written would not do what it is meant to do:

- it treats decisions as the main cause of PLAN.md bloat, and the corpus says otherwise;
- it reintroduces the single-file merge conflict that Plan 00543 removed from journals;
- it forks the existing `DECISIONS.md` convention under a new name;
- it quietly weakens two existing plan-QA signals.

A much smaller version gets most of the value. See "Minimum viable version" at the end.

## Measurements (angle 1)

Method: split every `PLAN.md` on `## ` headings and attribute bytes. The
corpus is 551 plans, 68 live and 483 Completed.

| Population                              | Count | Notes                                                                                                                                                                                                                               |
| --------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plans at or over 18,000 B (advisory)    | 52    | 1.27 MB in H2 sections. **Tasks ~48%**, sections headed decision/design/rationale/options **~11%**, progress/log ~8%, evidence/research ~7%, criteria ~5%, other ~21%                                                               |
| Plans numbered 00400 or higher          | 175   | Only **11** reach 18,000 B and 30 reach 12,000 B. The size rules already work for most new plans                                                                                                                                    |
| Largest recent plans                    | -     | Tasks section share: 00470 is 23.1 of 25.7 KB, 00463 is 22.8 of 31.0 KB, 00408 is 22.6 of 24.9 KB, 00400 is 18.5 of 22.7 KB, 00421 is 19.4 of 29.1 KB                                                                               |
| Inside Tasks (32 plans: 00300+, 15 KB+) | -     | Rough keyword classification of each task block: post-delivery outcome/status narrative dominates ~46%, spec and test lists ~30%, decision-dominant ~23%. The first-match ordering biases this, so read it as an order of magnitude |

Inspection confirms the pattern. For example, 00463 Task 1.1 is a 25-line
`Outcome: ... The questions were: ...` block. Some of that is a decision
outcome, but most of it is delivery narrative and the original question list.
Task 1.2 is an inline test specification. Decisions do appear, but as a
minority. They show up most clearly as `Open questions for the owner` sections
(00483 5.6 KB, 00479 2.3 KB, 00502 1.5 KB) and `Rulings` sections (00501).

Conclusion: **decisions are not the main driver.** The main drivers are task
bodies that carry specification detail, and post-delivery "Outcome:" or status
narrative that is never moved out once a task is ticked. The plan's Overview
sentence "Long-form decisions are what push plans over those limits" is
asserted, not measured. A decisions log alone will relieve some pressure, not
most of it.

## Findings

### H1 (high): the plan targets a minority cause of PLAN.md size

See Measurements. Nothing in the plan addresses the two larger drivers:

- inline task specification;
- "Outcome:" narrative left under ticked tasks. This is dated narrative that
  belongs in `JOURNAL/` or Delivery & Milestones.

**Fix:**

- Rewrite the Overview claim with the measured shares.
- Add a task that changes the remedy wording to name the ticked-task outcome
  pattern explicitly. A ticked task keeps one outcome line and moves the rest to
  JOURNAL. The remedy wording SSoT is `plan_qa/remedy.py` (see H6).
- Optionally add an advisory sweep check for ticked tasks whose body exceeds N
  lines. It points at the remedy, and it hits the actual bulk.
- Keep the decisions log, but present it honestly as one of three levers.
- Make the open-questions and rulings sections the log's primary migration
  target. That is where decision bulk really sits.

### H2 (high): the ID scheme and single-file append break under the worktree workflow

DESIGN §3 and §8 propose sequential `D-NNNN` ids allocated by
`mkplan.bash --decision`, made safe by "the lock mkplan already takes". This
fails in four ways:

- **The lock does not solve this.** It lives in the common git dir
  (`mkplan.bash:39-57`), so it serialises processes on one clone. It cannot make
  two branches agree on content. Worktree A and worktree B each read their own
  branch's copy of the file, and both allocate `D-0007`.
- **It contradicts mkplan's own design.** `run_journal_mode` deliberately does
  NOT take the lock (`mkplan.bash:503-508`, Plan 00427 D6a), because appends are
  frequent and must not contend with plan-number allocation. The design copies
  the journal writer but reverses that decision without saying so.
- **Both branches appending at EOF always conflicts.** This is exactly the
  failure Plan 00543 removed from journals by moving to one file per entry
  (`CLAUDE/PlanJournalling.md:159`, `:244-257`). The design acknowledges the
  conflict and leaves it to `decision-id-unique`, which only fires after the
  conflict has already been resolved by hand.
- **Renumbering after a collision corrupts references permanently.** Once
  `D-0007` is renumbered, any journal entry that said `see D-0007` points at the
  wrong decision. Journal entries are append-only and cannot be fixed (DESIGN §6
  requires journal entries to cite D-ids). The same applies to PLAN.md task links
  and commit messages.

**Fix:** use collision-free ids that need no allocator.

- One option is a UTC timestamp plus short hex, as the journal entry filenames
  already use (`mkplan.bash:489-497`), for example
  `D-261107T1432-a3f`. Display order then comes from file order or the stamp.
- To keep a single readable file, declare the file `merge=union` in
  `.gitattributes`, or extend `mkplan.bash --resolve-conflict` to accept it.
  `--resolve-conflict` already writes the union for legacy day-files.
- Either way, drop the lock claim.
- If short sequential ids are a hard owner requirement, the plan must say how
  they are reconciled across branches. A plan-number-style counter is per clone
  and lags, as `CLAUDE.md` notes for `hooksdaemon.latestPlanNumber`, so it
  does not solve this either.

### H3 (high): pre-creating the file silently disables the shrink guard (false claim)

DESIGN §1, row "Shrink guard", and §7 claim that extracting into the log
satisfies `plan-shrink-without-journal`. It does not.
`has_staged_supporting_doc` counts only a NEW (`A`-status) `.md` file
(`plan_qa/checks/common.py:584-614`, docstring `:595-603`: "Only `Added` status
counts (not `Modified`)").

Because mkplan pre-creates `PLAN-DECISIONS.md`, every later extraction into it
is a Modify. The result:

- a genuine extraction into the log is reported as a possible deletion;
- agents learn to ignore that advisory, so the guard loses its value for real
  deletions too.

**Fix:** in the same plan, teach `has_staged_supporting_doc` (or a sibling
predicate) to accept a staged modify to the decisions log whose added lines
include at least one new decision heading. Then rewrite DESIGN §1 and §7
accordingly. Add a test: an extraction-shaped commit into a pre-existing log
produces no finding.

### H4 (high): a new name forks an existing convention

The doc that "has no scaffold" already exists by name. `DECISIONS.md` appears
in 16 plan folders: 00100, 00236, 00237, 00234, 00245, 00260, 00266, 00271,
00273, 00326, 00334, 00335, 00403, 00422, 00486 and 00487. It is also named in:

- the remedy SSoT, `plan_qa/remedy.py:48-49`;
- `CLAUDE/PlanJournalling.md:111-113`.

Its headings are already converging on `## Decision N: <title>` and `## DN: <title> (decider)` (00486 uses `## D1: ... (agent ruling, coordinator)`).

Introducing `PLAN-DECISIONS.md` creates two names for one concept. Every
existing pointer, and the remedy text, then names the wrong one. Agents will
also find both kinds of file in the tree and copy whichever they saw last.

The `PLAN-` prefix also collides with the superseded-revision convention
`PLAN-v1.md` (`CLAUDE/Plan/CLAUDE.md`, "Superseded revisions"). A `PLAN*.md`
glob or a reader's eye picks up both.

**Fix:**

- Formalise `DECISIONS.md`. Adopt the existing `## DN:`-like shape, with the
  H2 collision fix.
- Grandfather plans at or below 00574 from grammar checks, using the same
  scoping mechanism as `journal_in_commit_scope`. The 16 legacy files are then
  neither migrated nor flagged.
- Drop the `PLAN-` prefix.

### H5 (high): a third home for the same fact, with nothing retired

Today a decision can land in any of these:

- a JOURNAL `decision` entry;
- `DESIGN.md`;
- `DECISIONS.md`;
- `DECISION-<topic>.md` (00412 has four);
- `OWNER-RULINGS-*.md` (00474);
- `OWNER-DECISIONS.md` (00560);
- the outcome of a CRITIQUE file;
- inline in PLAN.md.

The plan adds a log but retires nothing. DESIGN §6 even requires a double write
("Journal `decision` entries for task-linked choices say `see D-NNNN`"). That is
two writes for one fact: exactly the DRY violation the owner wants gone.

`CLAUDE/PlanJournalling.md`'s routing table also currently says "Why was option
B rejected mid-flight? → `JOURNAL/`" (around `:41`). That directly contradicts
the new routing, and Task 4.1 does not list that row.

**Fix:** write an explicit routing rule into the one SSoT doc, and have the
plan change the stale rows:

- **Decision with rationale, about this plan's work:** goes in `DECISIONS.md`
  and nowhere else. The JOURNAL may record the action ("recorded D-x") in one
  line, never the reasoning.
- **JOURNAL `decision` category:** keep it only for transient in-session choices
  that do not outlive the session.
- **`DESIGN.md`:** describes the chosen design as current state. Options and
  rejected alternatives go in the log, linked by id.
- **`OWNER-RULINGS-*.md` and `DECISION-<topic>.md`:** stop creating them for new
  plans. An owner ruling is a log entry with decider `owner` and the verbatim
  quote in the body.
- **`OWNER-DECISIONS.md` (a briefing that asks questions):** may remain as a
  question document. The answers land in the log as entries.
- **`CRITIQUE-vN.md`:** stays as a review artefact. Accepted critique points
  that change the plan become entries.

### H6 (high): the agent-behaviour lever is missing, and one hint regresses

Agents write where the error message tells them to. The plan never touches:

- `plan_qa/remedy.py`, the declared SSoT for remedy wording, rendered into the
  `plan-doc-size` finding and the CLAUDE.md guidance (`plan_doc_size.py:68-72`);
- the `plan_workflow` handler guidance.

Without that, the size error keeps saying "e.g. `RESEARCH-*.md`, `DECISIONS.md`"
and the new file is invisible at the exact moment it matters.

Worse, pre-creating any `.md` file silences `_FOLDER_SHAPE_HINT`.
`_folder_has_supporting_docs` (`plan_doc_size.py:127-142`) returns true for any
non-PLAN `.md` in the folder. After this plan, every new plan has one, so the
"this plan has no supporting documents, you are using it as a notepad" hint
never fires again.

**Fix:**

- Add a task that edits `remedy.py`. The EXTRACT remedy should name the
  plan's actual decisions file path, and the size finding should name it with
  the plan folder interpolated.
- Change `_folder_has_supporting_docs` to ignore the scaffolded log while it
  holds no decision entries, or ignore it unconditionally. Add a test.
- Have `_TEMPLATE_.md` carry a `**Decisions**: [DECISIONS.md](DECISIONS.md)`
  header line, so the pointer is visible in the one file every session reads.

### M1 (medium): tooling weight is disproportionate

The plan proposes a writer (`--decision`), a lookup CLI with four filters and
JSON, a parser module, a new `PlanFileKind`, four QA checks and a migration
recipe. That is a lot for a convention problem. The repo already has 43 checks
in `plan_qa/checks/`.

The writer exists mainly to allocate ids (H2 shows that is broken) and to
enforce append-only behaviour (M4 argues against it). The lookup CLI duplicates
the documented `grep '^## D'` fallback (DESIGN §4). On a file of a few dozen
entries, a well-formed heading line already gives one-command lookup.

**Fix:** see "Minimum viable version". Defer the writer, the CLI, and
`decision-supersede-resolves` until real use shows grep is not enough.

### M2 (medium): task-id keying misfits a large class of plans

`decision-task-exists` and the `T2.3` field assume decisions hang off
`Task N.N`. They often do not:

- **Niggle ledgers.** There are 17 `niggles-ledger` folders. They key decisions
  by niggle id: 00474's rulings table is keyed by `N280`, `N330`, `N333` and so
  on, while its PLAN.md has one Task line.
- **Planning-time decisions.** These shape the task list before tasks exist.
- **Renumbering.** Tasks are inserted and renumbered (see the recent "Task 2.6"
  inserts in Plan 00571). An append-only heading that cites `T2.3` then goes
  stale, and the rules forbid editing it.
- **Loose grep.** The DESIGN §2 lookup `grep 'T2\.3'` also matches `T2.30`.

**Fix:**

- Make the reference field free-form but typed: `Task 2.3`, `N330`, `plan`.
- Make the existence check advisory and sweep-only.
- Document an anchored lookup that matches the whole token: `grep -E '^## D.*[ ,](T|Task )2\.3([ ,]|$)'`.

### M3 (medium): a hybrid third contract

PlanJournalling's contracts table is the SSoT for three file kinds:

- PLAN.md is edited in place;
- supporting docs are edited in place and unbounded;
- JOURNAL entries are append-only, one file each.

The log adds a fourth contract: append-only, but a single file, with one
permitted in-place heading edit and an open alternative of a `--decision-status`
command. This is the kind of special case agents get wrong. It also needs a new
`PlanFileKind` (Task 1.3) only to apply rules a supporting doc does not have.

**Fix:**

- Treat the log as an ordinary supporting doc, edited in place, with git as the
  history. That is what the contract table already promises.
- Make the grammar the only addition: heading shape, unique ids, and a
  `Superseded-by` line.
- Detect it by filename inside the existing `SUPPORTING_DOC` kind. This drops
  Task 1.3. Consumers of `PlanFileKind` are few (`plan_qa/checks/common.py`,
  `index_*`, `cli.py:8696`), but the safest change is none.

### M4 (medium): client deployment drift, and a second plan-creation path

- **The grammar SSoT will not reach existing installs.** DESIGN §8 puts it in
  `PlanJournalling.md` or `PlanWorkflow.md`. `PlanJournalling.md` is
  client-owned, seeded only when absent, and never overwritten
  (`install/plan_workflow.py:62-66`, `:344-360`), so existing installs never
  receive the grammar. `_TEMPLATE_.md` (Task 2.4) is also client-owned; clients
  only see a snapshot diff.
- **The decisions template auto-enables with no explanation.** It is client-owned
  and seeded when absent, so every existing client gets it on upgrade, without
  the doc that explains it.
- **mkplan is not the only way a plan folder is created.** `markdown_organization`
  planning mode creates `NNNNN-name/PLAN.md` directly
  (`handlers/pre_tool_use/markdown_organization.py:863-870`), so those plans get
  no log. Goal 1 ("for every new plan") is false for that path.
- **Path citations are shorthand.** `install/plan_workflow.py`,
  `install/core_docs.py` and `install/templates/...` live under
  `src/claude_code_hooks_daemon/`. This is shorthand and not wrong, but an
  executor will waste a lookup on it.

**Fix:**

- Put the grammar in the daemon-owned core doc
  `src/claude_code_hooks_daemon/install/templates/core/PlanWorkflow.core.md`,
  deployed by `core_docs.py`. Have the seeded template carry a one-line grammar
  comment that points there, as `_JOURNAL_TEMPLATE_.md` does with its
  entry-grammar line.
- Either scaffold the log from the planning-mode path too, or scaffold lazily
  (L1).
- Spell out full paths.

### L1 (low): an empty stub in every plan

Most plans never record a decision: 535 of 551 have no `DECISIONS.md` today.
A pre-created empty file:

- is noise in every folder;
- triggers H3 and H6;
- makes `plan-links-decisions` reason about empty files.

**Fix:** decide this deliberately in Task 1.1. Lazy creation (the first entry
creates the file from the template) avoids H3 and H6 entirely. Pre-creation is
justified only if the owner values discoverability over those costs. It is a
real trade-off, and the plan should record which side it took.

### L2 (low): the `D-` id namespace clashes with existing usage

Short `DN` ids are already scattered through code comments and docs as
plan-local decision references: "Plan 00427 D5" and "D6a" in `mkplan.bash`,
"Decision 5" in `plan_qa/paths.py`, and "D17" in 00326. Without the plan number
attached, a bare `D-0007` in a commit message or journal entry is ambiguous
across plans.

**Fix:** outside the file itself, always cite with the plan number
(`00574/D-...`). State that rule once, in the SSoT doc.

## False or unsupported claims (angle 6)

| Claim                                                                                                                          | Status                                                                                          | Evidence                                    |
| ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- | ------------------------------------------- |
| "Long-form decisions are what push plans over those limits" (PLAN Overview)                                                    | Unsupported; measured as a minority                                                             | Measurements above                          |
| Extracting into the log satisfies `plan-shrink-without-journal` (DESIGN §1, §7)                                                | False once the file is pre-created                                                              | `plan_qa/checks/common.py:595-603`          |
| `--decision` id allocation is safe under "the lock mkplan already takes" (DESIGN §8)                                           | False across branches. Also reverses the deliberate no-lock decision for appends                | `mkplan.bash:39-57`, `:503-508`             |
| "`mkplan.bash` creates `PLAN-DECISIONS.md` for every new plan" (Goal 1)                                                        | Incomplete: planning mode bypasses mkplan                                                       | `markdown_organization.py:863-870`          |
| "that doc has no scaffold, no grammar ... every plan invents its own shape"                                                    | Half true: there is no scaffold, but `DECISIONS.md` exists in 16 plans with converging headings | H4                                          |
| Task 4.1's doc list is complete                                                                                                | Incomplete: misses `plan_qa/remedy.py` (wording SSoT) and the PlanJournalling routing row       | `plan_doc_size.py:68-72`, `remedy.py:48-49` |
| Other citations (`types.py:60-62`, `paths.py` kinds, `model.py:369`, `cli.py:8609`, `task_grammar.py`, mkplan template gating) | Verified                                                                                        | -                                           |

## Minimum viable version

1. **Name and grammar.** Formalise `DECISIONS.md` (H4). Grammar: one H2 per
   entry, `## D-<stamp> · <refs> · <status> · <decider> — <title>`, where
   `<refs>` is free-form typed (`Task 2.3`, `N330`, `plan`). The body is the
   existing Context/Options/Decision/Consequences shape. The file is edited in
   place as a supporting doc (M3). The grammar lives once, in
   `PlanWorkflow.core.md` (M4).
2. **Scaffold.** Add `_DECISIONS_TEMPLATE_.md`, either copied by mkplan or
   created lazily (L1). Add the `_TEMPLATE_.md` header pointer line.
3. **Agent levers.** Edit `remedy.py` so the EXTRACT remedy names the decisions
   file, and the ticked-task outcome bloat goes to JOURNAL (H1, H6). Fix the
   shrink predicate (H3) and the folder-shape hint (H6). Fix the routing rows in
   PlanJournalling and the core doc (H5).
4. **Merge safety.** Use stamp ids plus a union merge or `--resolve-conflict`
   support (H2).
5. **QA.** One check, `decisions-grammar`: heading well-formed and ids unique,
   at edit and commit, with the grandfather threshold. Everything else is
   deferred.
6. **Lookup.** A documented, anchored grep (M2). The CLI waits until it is
   proven necessary.

Items 1 to 6 deliver the owner's stated goal: a long-form, unbounded log that
is quick to search, pre-placed and interlinked. They also fix the larger bloat
driver, at roughly a third of the proposed surface.
