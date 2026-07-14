# Plan 00163: Plan Journalling — first-class per-plan JOURNAL/ support

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plans capture WHAT and WHY; they cannot carry the linear time-series of what
actually happened — findings, dead-ends, in-flight decisions, hand-off state.
Today that stream is crammed informally into `## Notes & Updates` (see 00158,
00161), where it strains the section and gets compressed away. This plan makes
**plan journalling a first-class daemon feature**: every plan folder
`CLAUDE/Plan/NNNNN-name/` gains a **`JOURNAL/`** subfolder holding per-day,
append-only files **`NNNNN-Journal-YY-MM-DD.md`** — a chronological activity
log COMPLEMENTARY to `PLAN.md` (PLAN.md = the plan; JOURNAL = the lifecycle
log that grounds future agents in ways PLAN.md structurally cannot, especially
roads-not-taken and hand-off context).

The daemon supports and encourages the habit through the existing **plan_qa**
machinery (no new handler, no new event): the edit-stage handler learns to lint
journal files, the SessionStart sweep learns presence/freshness nudges, and the
commit gate later learns progress/completion coupling. `mkplan.bash` scaffolds
`JOURNAL/` plus a seeded day-1 file. Everything ships **advise-first** and only
day-file naming may ever ratchet to block — journalling is a habit to
encourage, not work to gate.

Rollout follows the house pattern: **dogfood in THIS repo first** (starting
with this very plan's own journal), then deploy to clients with a copyable,
customisable reference doc `CLAUDE/PlanJournalling.md` (ours is a reference,
not set in stone). Synthesised from two Opus brainstorms preserved in this
folder: `BRAINSTORM-datamodel.md` (data model & lifecycle) and
`BRAINSTORM-enforcement.md` (daemon enforcement & handlers).

## Goals

- `JOURNAL/` + `NNNNN-Journal-YY-MM-DD.md` per-day append-only files as the
  canonical plan activity log, scaffolded by `mkplan.bash` with a
  project-owned `_JOURNAL_TEMPLATE_.md`.
- First-class plan_qa support: journal checks registered in the shared check
  catalogue and surfaced through the existing three stages
  (`plan_qa_edit`, `plan_qa_commit_gate`, `plan_qa_sweep`), all advise-first,
  config-driven under `plan_workflow.qa.journal.*`.
- A documented entry grammar (`## HH:MM · category · REF`) with a small fixed
  category set, append-only discipline, and worked good/noise examples.
- Reconcile `## Notes & Updates` with the journal: the diary stream moves to
  JOURNAL; PLAN.md keeps a thin curated `## Delivery & Milestones` stub
  (delivery commit hashes stay in PLAN.md so the completion checklist and
  plan_qa story are unchanged).
- Dogfooded in this repo (this plan journals itself from day 1), then rolled
  out to clients with `CLAUDE/PlanJournalling.md` as a copy-and-customise
  reference.

## Non-Goals

- No blocking enforcement at first ship — every journal check lands ADVISE;
  only `journal-dayfile-naming` is a ratchet candidate, and only after a clean
  dogfood period.
- No backfill: existing plans (00001–00162) are never nagged to grow a
  `JOURNAL/` (grandfather threshold); freshness nudges apply only where a
  `JOURNAL/` already exists.
- No new hook event or new handler — journalling rides the three existing
  plan_qa surfaces.
- Not a heartbeat or per-tool-call log: entries record meaningful events
  (findings, decisions, blockers, hand-offs), never tick-spam.
- No `CLAUDE/Journal/` top-level directory — journals live inside plan
  folders only (Plan 00132 merely reserves that name; do not conflate).
- Sub-agent direct journalling is out of scope for v1: the orchestrator
  journals on behalf of sub-agents (they return summaries; concurrent
  same-file appends from multiple writers are deferred — see Decision 9).

## Context & Background

- Two Opus brainstorms feed this plan: `BRAINSTORM-datamodel.md` (naming,
  entry grammar, Notes & Updates reconciliation, lifecycle touchpoints,
  reference-doc TOC, policy-vs-convention split) and
  `BRAINSTORM-enforcement.md` (which plan_qa stage hosts each check, the
  append-only prefix test, config knobs, grandfathering, dogfood slice).
- The plan_qa machine (Plan 00144) already provides everything needed:
  `CheckSpec`/`Stage`/`Level`/`Finding` in `plan_qa/types.py`, the catalogue
  in `plan_qa/checks/__init__.py::all_checks()`, three surfaces calling
  `run_stage(stage, ctx)`, `PlanFolder`/`PlanTree` in `plan_qa/model.py`, and
  policy threading via the `QaPolicy` Protocol from `PlanWorkflowQaConfig`
  (`src/claude_code_hooks_daemon/config/models.py`).
- `plan_qa_edit` currently matches only `PLAN.md`
  (`handlers/pre_tool_use/plan_qa_edit.py`) and reconstructs would-be content
  via `_would_be_content()` — the fiddly part journal checks will reuse.
- `mkplan.bash` scaffolds with pure bash (mkdir/cat, never the Write tool) and
  already renders a project-owned `_TEMPLATE_.md` (Plan 00144) — the exact
  mechanism `_JOURNAL_TEMPLATE_.md` mirrors.
- `markdown_organization` already allows the whole `CLAUDE/Plan/` subtree, so
  journal writes need zero config change there.
- Live datapoint: the originating session crossed local midnight
  (07-13 → 07-14) mid-run — day rollover mid-session is real, so the naming
  check must accept "yesterday or today", not strictly `date.today()`.

## Tasks

### Phase 1: Minimal dogfoodable slice (all ADVISE mode)

- [x] ✅ **Task 1.1**: Config — nested `journal` block on
  `PlanWorkflowQaConfig` (`PlanWorkflowQaJournalConfig`: `enabled`/`mode`/
  `dir_name`/`freshness_days`/`enforce_on_completion`/`grandfather_before`)
  threaded into `CheckContext` via one typed `_with_journal` helper
  (`dataclasses.replace` — no suppression). `JournalPolicy` Protocol added.
  This repo's config sets `grandfather_before: 163`.
- [x] ✅ **Task 1.2**: Model — `PlanFolder.has_journal` +
  `latest_journal_date` (filename parse only) via `parse_journal_dayfile_name`
  (`JournalDayfileName` splits regex-match from calendar validity —
  `is_valid_date` uses stdlib `calendar`, NOT a caught ValueError, so
  error_hiding stays clean). `journal_dir_name` threaded through `scan`.
- [x] ✅ **Task 1.3**: Context — added `file_content_before: str | None` and
  `today` to `CheckContext` / the EDIT builder; `plan_qa_edit` threads the
  pre-edit on-disk content so the append-only check stays pure.
- [x] ✅ **Task 1.4**: EDIT checks — `journal_dayfile_naming` (ADVISE,
  ratchet-able to BLOCK via `mode: block`) and `journal_append_only` (ADVISE
  forever), registered in `all_checks()`. Naming validates grammar +
  number-match + today/yesterday; append-only is the trailing-newline
  prefix test (creation/append OK; shrink → truncation; else → rewrite).
- [x] ✅ **Task 1.5**: `plan_qa_edit.matches()` broadened from PLAN.md-only to
  also lint `{dir_name}/*.md` journal day-files; `handle()` threads
  `file_content_before` + `today`. Checks self-select via `journal_edit_target`.
  ONE handler, no duplicated would-be-content reconstruction. Also exempted
  journal day-files from `markdown_table_formatter` (Decision 6) so the live
  append-only check is not tripped by the formatter.
- [x] ✅ **Task 1.6**: SWEEP checks — `journal_folder_present` (In Progress,
  number ≥ `grandfather_before`, no `JOURNAL/`) and `journal_freshness`
  (In Progress WITH a `JOURNAL/` whose newest day-file name is older than
  `freshness_days`, filename-based). Both ADVISE. Verified `plan-qa --sweep`
  reports ZERO journal findings in this repo (legacy plans grandfathered).
- [x] ✅ **Task 1.7**: `mkplan.bash` (bundle + deployed, byte-identical,
  shellcheck clean) scaffolds `JOURNAL/` + `NNNNN-Journal-$(date +%y-%m-%d).md`
  after PLAN.md, rendering `_JOURNAL_TEMPLATE_.md` (`{{PLAN_NUMBER}}`,
  `{{PLAN_TITLE}}`, `{{DATE}}`, `{{TIME}}`, `{{OWNER}}`). Gated on the
  template's presence so journal-less projects get clean plans (Decision 10).
  Two tests in `test_plan_workflow.py` (present→scaffolds; absent→gated).
- [x] ✅ **Task 1.8**: Shipped `_JOURNAL_TEMPLATE_.md` (bundle
  `src/claude_code_hooks_daemon/install/templates/` + dogfood `CLAUDE/Plan/`), seed `action` entry +
  grammar crib header. NOTE: the `markdown_table_formatter` JOURNAL/ exemption
  is deferred to the append-only-check task (T1.4) where the byte-invariant
  actually matters — no journal has tables yet.
- [ ] ⬜ **Task 1.9**: Dogfood — journalled THIS plan in
  `JOURNAL/00163-Journal-26-07-14.md` from this session (done). PENDING:
  live-verify mkplan scaffolds on a scratch plan and that edit-stage advisories
  fire on a bad name / non-append rewrite and the sweep stays silent for
  grandfathered plans — needs the checks (T1.4/T1.6) first.

### Phase 2: Reference doc + template reconciliation

- [ ] ⬜ **Task 2.1**: Write `CLAUDE/PlanJournalling.md` (British double-l,
  canonical) per the BRAINSTORM-datamodel §6 TOC: purpose
  (PLAN.md vs JOURNAL), layout, entry grammar, append-only discipline,
  lifecycle touchpoints table, Notes & Updates migration, good-vs-noise
  worked examples, and an explicit **POLICY (daemon-enforced, with the exact
  `plan_workflow.qa.journal.*` knob) vs CONVENTION (client-tunable)** split.
  Framed as copy-and-customise for client projects.
- [ ] ⬜ **Task 2.2**: Reconcile `_TEMPLATE_.md` — replace `## Notes & Updates`
  with a curated `## Delivery & Milestones` stub (milestone lines + delivery
  commit hashes). Update `CLAUDE/PlanWorkflow.md`, `CLAUDE/Plan/CLAUDE.md`,
  and the completion checklist so "cite delivery commit hashes" points at the
  new section; verify no plan_qa check asserts a Notes & Updates section.
  Legacy plans keep theirs untouched.
- [ ] ⬜ **Task 2.3**: Docs — `docs/guides/HANDLER_REFERENCE.md` journal
  options; `get_claude_md()` updates for the three plan_qa surfaces so the
  injected guidance mentions journal advisories; regenerate docs.

### Phase 3: Commit-gate coupling + ratchet review (post-dogfood)

- [ ] ⬜ **Task 3.1**: COMMIT checks — `journal-entry-with-progress` (commit
  changes a plan's PLAN.md tasks but stages nothing under that plan's
  `JOURNAL/`) and `journal-completion-entry` (terminal status flip without a
  closing journal entry staged), both ADVISE, via
  `GitFacts.staged_paths_under()`; honour `enforce_on_completion`.
- [ ] ⬜ **Task 3.2**: Ratchet review — after a clean dogfood period, decide
  with the user whether `journal-dayfile-naming` escalates to BLOCK under
  `mode: block`; presence/freshness/append-only stay ADVISE forever. Record
  the outcome here as a Technical Decision.

### Phase 4: Client rollout

- [ ] ⬜ **Task 4.1**: Deploy — installer/upgrade seeds `_JOURNAL_TEMPLATE_.md`
  (never overwrites) and `CLAUDE/PlanJournalling.md` alongside the existing
  `deploy_plan_workflow_if_enabled` path (mkplan already deploys there);
  decide default-on vs opt-in for clients with the user (open question 1).
- [ ] ⬜ **Task 4.2**: Release plumbing — `config-changes` manifest for
  `plan_workflow.qa.journal.*` (recommended: true), `truth-changes` entry for
  the Notes & Updates → Delivery & Milestones convention shift, acceptance
  tests via `get_acceptance_tests()` on the touched surfaces, playbook
  regeneration, full QA, release via `/release`.

## Technical Decisions

### Decision 1: Naming and layout (user-fixed, confirmed by both brainstorms)

`JOURNAL/` (upper-case landmark, sibling of PLAN.md) inside the plan folder;
day-files `NNNNN-Journal-YY-MM-DD.md` with the redundant NNNNN kept
deliberately (survives copy/paste, greps cleanly). **`YY-MM-DD` honoured as
the user specified** — the datamodel brainstorm's `YYYY-MM-DD` alternative
(reuses plan_qa's existing date regex) is noted but not taken; the journal
filename parser gets its own two-digit-year pattern. One file per LOCAL day
(midnight-to-midnight, matching `date +%F` semantics elsewhere); multiple
entries append to that day's file; **a day with no activity has NO file**
(sparse-by-design — never scaffold empty day-files). Because `JOURNAL/` lives
inside the plan folder, archive `git mv` carries it for free and
`terminal-state-atomic` needs no change.

### Decision 2: Entry grammar (from BRAINSTORM-datamodel §2)

Per-entry unit = a heading with fixed grammar + free markdown body:

```
## HH:MM · CATEGORY · REF   [— optional short title]
```

- `HH:MM` local 24h (date lives in the filename); times monotonic within a
  file.
- `CATEGORY` ∈ `action | finding | decision | thought | blocker | handoff`
  (fixed core set; clients may extend — convention, not policy).
- `REF` optional task/phase ref (`T2.1`, `P2`, `—`).
- Bodies may embed fenced logs/diffs with a one-line takeaway above the
  fence. Corrections are NEW entries, never rewrites. The optional HTML
  machine header (`<!-- j ts=… -->`) is documented as advisory only — the
  heading is the single grammar the daemon may ever lint.
- `handoff`-at-tail convention: the resumer's entry point is the last entry
  of the newest day-file.

### Decision 3: Notes & Updates is SUBSUMED, with a curated milestone stub

Adopt the datamodel brainstorm's recommendation: JOURNAL takes the whole
blow-by-blow stream; `_TEMPLATE_.md` retires free-form `## Notes & Updates` in
favour of a thin `## Delivery & Milestones` (milestones + delivery commit
hashes), keeping the completion checklist and plan_qa story unchanged — no
check asserts Notes & Updates exists. Two live diaries would guarantee drift;
one diary (JOURNAL) + one curated summary (PLAN.md). Legacy plans are never
rewritten. (This plan itself still carries Notes & Updates — it predates the
template change; the section will hold only milestones.)

### Decision 4: Advise-first enforcement; naming is the only ratchet candidate

Adopt the enforcement brainstorm's stance wholesale: journalling is a habit to
encourage, not work to gate. All six checks ship ADVISE under
`plan_workflow.qa.journal.mode: advise` (master switch, plus global
`plan_workflow.qa.enabled`). Presence, freshness, append-only, and the commit
couplings stay advisory FOREVER (a false block on someone's log is worse than
a missed nudge; same-day typo fixes are legitimate non-appends). Only
`journal-dayfile-naming` may escalate to block, and only after the Phase 3
dogfood review — the same warn→block path `commit_gate_mode` took.

### Decision 5: Check catalogue additions (IDs fixed now)

| check_id                      | stage       | level                    |
| ----------------------------- | ----------- | ------------------------ |
| `journal-dayfile-naming`      | EDIT        | ADVISE (ratchet-able)    |
| `journal-append-only`         | EDIT        | ADVISE (forever)         |
| `journal-folder-present`      | SWEEP       | ADVISE (threshold-gated) |
| `journal-freshness`           | SWEEP       | ADVISE                   |
| `journal-entry-with-progress` | COMMIT      | ADVISE (Phase 3)         |
| `journal-completion-entry`    | COMMIT/EDIT | ADVISE (Phase 3)         |

No `journal-moves-with-plan` check: the folder layout makes archive moves
free and `terminal-state-atomic` already asserts the folder move. No new
handler and no new hook event — the three existing plan_qa surfaces host
everything.

### Decision 6: Append-only detection = prefix test + formatter exemption

`after.startswith(before)` on trailing-newline-normalised content, with
`file_content_before` threaded into `CheckContext` from `plan_qa_edit`'s
existing read. New file → creation, OK. Shrink → truncation warning; other
mismatch → rewrite warning. To keep the invariant sound,
`markdown_table_formatter` exempts `JOURNAL/` day-files (journals stay
byte-stable; auto-alignment matters less in an append-only log than a stable
prefix). Escape hatches are unnecessary while the check is advisory.

### Decision 7: Grandfathering = number threshold + presence-scoped freshness

Adopt enforcement brainstorm options (a)+(c): `journal-folder-present` fires
only for plans numbered ≥ `grandfather_before` (set to 163 in this repo — the
plan that introduces journalling); `journal-freshness` fires only where a
`JOURNAL/` already exists regardless of number. The ~160 existing journal-less
plans are never nagged. No backfill (datamodel open question 10: no-backfill
is cleanest).

### Decision 8: Freshness reads day-file NAMES, not git dates

Journals are often uncommitted mid-plan; `GitFacts.last_commit_date` would
under-report. `latest_journal_date` parses filenames on disk (cheap, no file
reads). `freshness_days` (default 3) is deliberately separate from the plan
`staleness_days` (30) — journals nag sooner.

### Decision 9: Single-writer journals in v1; orchestrator writes for the team

Sub-agents return summaries; the orchestrator (main thread) writes journal
entries on their behalf, optionally tagging actor as a trailing `— @agent` or
in the advisory HTML header. Per-actor day-files
(`NNNNN-Journal-YY-MM-DD-<actor>.md`) are explicitly deferred until concurrent
team-writes are a demonstrated problem (YAGNI; cf. Plan 00159's thread-safe
tmp naming for the shape of that fix if needed).

### Decision 10: Scaffolding stays in bash, template stays project-owned

`mkplan.bash` writes `JOURNAL/` + day-1 file with mkdir/cat (never the Write
tool) for the same reason it does PLAN.md — the daemon's plan-number/write
handlers must not see the write. `_JOURNAL_TEMPLATE_.md` mirrors the Plan
00144 `_TEMPLATE_.md` contract exactly: seeded on deploy, never overwritten,
pure-bash placeholder substitution, and its presence doubles as the "this
project journals" marker for mkplan.

## Dependencies

- Builds on: Plan 00144 (plan_qa system — check catalogue, three surfaces,
  `QaPolicy` threading), Plan 00130/00136 (mkplan distribution + config-SSoT
  deploy path).
- Related: Plan 00132 (reserves `CLAUDE/Journal/` naming — distinct concept,
  keep excluded), Plan 00159 (thread-safe writer pattern if per-actor files
  ever land).

## Success Criteria

- [ ] `mkplan.bash` scaffolds `JOURNAL/` + a seeded, grammar-conformant day-1
  file from `_JOURNAL_TEMPLATE_.md`; journal-less projects are unaffected.
- [ ] All Phase-1 checks registered and live through the existing three
  surfaces, ADVISE-only, config-driven under `plan_workflow.qa.journal.*`;
  no new handler, no hardcoded `"JOURNAL"` in checks.
- [ ] Grandfathering verified: `plan-qa --sweep` reports zero journal findings
  for plans 00001–00162; this plan's own journal keeps the sweep clean for
  00163\.
- [ ] Append-only advisory verified live: a rewrite of an earlier entry
  surfaces the advisory; a pure append and a new day-file do not.
- [ ] This plan is itself journalled (dogfooding evidence in
  `JOURNAL/00163-Journal-*.md`).
- [ ] `CLAUDE/PlanJournalling.md` shipped with the POLICY/CONVENTION split and
  copy-and-customise framing.
- [ ] 95%+ coverage maintained; full QA passes; daemon restart RUNNING after
  every handler change.

## Risks & Mitigations

| Risk                                                                | Impact | Probability | Mitigation                                                                              |
| ------------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------- |
| Nag spam across ~160 legacy plans erodes trust in plan_qa           | High   | High        | `grandfather_before` threshold + freshness scoped to existing JOURNALs (Decision 7)     |
| `markdown_table_formatter` rewrites break the append-only invariant | Medium | High        | Exempt `JOURNAL/` from the formatter (Decision 6); revisit if formatting is missed      |
| Midnight rollover mid-session flags a "wrong date" filename         | Low    | Medium      | Naming check accepts today OR yesterday (observed live in the originating session)      |
| Journalling becomes tick-spam / heartbeat noise                     | Medium | Medium      | Reference doc names the anti-patterns; cadence is convention, never enforced per-event  |
| Two diaries (Notes & Updates + JOURNAL) drift                       | Medium | Medium      | Template retires Notes & Updates for a milestone stub (Decision 3)                      |
| Hot-path cost in `plan_qa_edit` for large journal files             | Low    | Low         | Single-file checks only; model scan is filename-parse-only; no whole-tree reads at edit |

## Notes & Updates

### 2026-07-14

- Plan scaffolded via `mkplan.bash` (counter → 163) by a Fable synthesis
  agent, converging two Opus brainstorms copied into this folder as
  `BRAINSTORM-datamodel.md` and `BRAINSTORM-enforcement.md`.
- Recovery-cron advisory fired during scaffolding; this synthesis ran in a
  subagent context without CronCreate — the orchestrator session owns the
  failsafe recovery cron and should record its ID here when implementation
  starts.
- Open questions needing the user's call before/at Phase 1:
  1. Client rollout default — `plan_workflow.qa.journal.enabled` default ON
     (scaffolds JOURNAL/ in every client's next plan) vs opt-in (Task 4.1).
  2. Confirm `YY-MM-DD` over `YYYY-MM-DD` as final (Decision 1 honours the
     user's spec; 4-digit would reuse the existing plan_qa date regex).
  3. Notes & Updates fate — confirm subsume + `## Delivery & Milestones`
     stub (Decision 3) vs keeping Notes & Updates as-is for milestones.
  4. `markdown_table_formatter` exemption for JOURNAL/ vs a
     whitespace-tolerant append check (Decision 6 picks the exemption).
  5. Whether `journal-dayfile-naming` should ever ratchet to block
     (Phase 3 Task 3.2 review point).
