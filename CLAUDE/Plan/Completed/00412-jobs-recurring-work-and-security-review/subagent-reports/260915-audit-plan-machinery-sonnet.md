# Plan machinery inventory — what makes PLANS work, and what a JOBS concept would need

Read-only audit for Plan 00412. Every item below is cited by absolute path.
Verdict column: **REUSE** (share the existing code/asset unchanged), **MIRROR**
(Jobs needs its own equivalent), **OMIT** (plan-specific, wrong for a
never-completing recurring Job).

---

## 1. Filesystem contract

| Piece                                     | Where                                                                                                                                                                                                                                                                                         | What it enforces                                                                                                                                                                           | Verdict                                       |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| Plan folder grammar `NNNNN-name`          | `/workspace/src/claude_code_hooks_daemon/plan_qa/model.py:300` (`_PLAN_FOLDER_RE = ^(\d{1,5})-[a-zA-Z]`), duplicated deliberately at `/workspace/src/claude_code_hooks_daemon/handlers/utils/plan_numbering.py:34` and in bash at `/workspace/CLAUDE/Plan/mkplan.bash` (`filesystem_highest`) | 1–5 digits, hyphen, then a **letter** — so a date-shaped dir (`2026-01-12`) is never read as plan 2026                                                                                     | MIRROR (same grammar, different root)         |
| `PLAN.md` required structure              | `/workspace/CLAUDE/core/PlanWorkflow.core.md` ("Plan Document Structure"); parser at `/workspace/src/claude_code_hooks_daemon/plan_qa/model.py:116` (`PlanDoc`)                                                                                                                               | `# Plan NNNNN: Title` + `**Status**:` / `**Created**:` / `**Owner**:` / `**Priority**:` header lines, then Overview / Goals / Non-Goals / Tasks / Success Criteria / Delivery & Milestones | MIRROR (a Job header is different — see §8)   |
| Status tokens                             | `/workspace/src/claude_code_hooks_daemon/plan_qa/model.py:36` (`PlanStatus`) — `Not Started`, `In Progress`, `Complete`, `Blocked`, `Cancelled`, `Superseded`, `Dormant`; terminal set at `:49` (`TERMINAL_STATUSES` = Complete/Cancelled/Superseded)                                         | The vocabulary every coherence/atomicity check keys on                                                                                                                                     | **OMIT wholesale** — see §8                   |
| Task grammar                              | `model.py:65-77` — `- [ ]`/`- [x]` checkboxes plus icons ⬜🔄✅🚫❌; `_LEGACY_MARKERS` (`[✓]`, `[⏳]`, `[~]`) detected as sin E6                                                                                                                                                              | Machine-countable progress, so header/body coherence is computable                                                                                                                         | MIRROR, optional                              |
| `JOURNAL/` day-file naming                | `model.py:305` `_JOURNAL_DAYFILE_RE = ^(\d{1,5})-Journal-(\d{2})-(\d{2})-(\d{2})\.md$`; parser `parse_journal_dayfile_name` at `model.py:366`; calendar validity at `model.py:334`                                                                                                            | `NNNNN-Journal-YY-MM-DD.md`, one file per **local day**, redundant number for grep/copy-paste survival                                                                                     | REUSE the mechanism, MIRROR the name (see §9) |
| Append-only rule                          | `/workspace/src/claude_code_hooks_daemon/plan_qa/checks/journal_append_only.py` (EDIT, advise) — diffs would-be content against `file_content_before`                                                                                                                                         | An edit may only ADD at the end; corrections are new dated entries                                                                                                                         | REUSE                                         |
| Journal entry grammar                     | `/workspace/CLAUDE/PlanJournalling.md` ("Entry grammar"); template `/workspace/CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`                                                                                                                                                                             | `## HH:MM · CATEGORY · REF — title`, categories `action/finding/decision/thought/blocker/handoff`, times increase down the file. **Convention, not policy** except the four checks in §9   | REUSE                                         |
| Supporting docs                           | `/workspace/CLAUDE/PlanJournalling.md` ("The contracts (SSoT)" table)                                                                                                                                                                                                                         | Plain `.md` in the plan folder, edited in place, **unbounded** (read on demand only) — versus `PLAN.md` which is bounded because it is read in full every session                          | REUSE the reasoning verbatim                  |
| `subagent-reports/`                       | `/workspace/CLAUDE/core/PlanWorkflow.core.md` ("Subagent report handoff"); enforced at dispatch by `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/dispatch_declaration.py` and at return by `subagent_report_size_blocker`                                                    | `{yymmdd}-{agent-name}-{model}.md`; a recognised plan-folder member, never a stray finding                                                                                                 | REUSE                                         |
| Plan-root stray-file allowlist            | `model.py:314` `_EXPECTED_ROOT_FILES` = `README.md`, `CLAUDE.md`, `mkplan.bash`, `_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md`, `_planlib.inc.bash`; extendable via `plan_workflow.qa.extra_root_files`                                                                                            | Anything else at the plan root is an orphan note nobody indexes                                                                                                                            | MIRROR                                        |
| `Completed/` + `Cancelled/` archival      | `model.py:281` `PlanLocation` (ROOT / COMPLETED / CANCELLED / OTHER); checks `structure_archive_dirs.py`, `location_status_coherence.py`, `terminal_state_atomic.py`, `archived_status_coherence.py`, `archive_immutability.py`                                                               | Terminal status ⇒ the folder MUST `git mv` into the archive dir **in the same commit** as the status flip, README row and statistics recount                                               | **OMIT** — see §8                             |
| Archive is a record, not maintained truth | `/workspace/CLAUDE/core/PlanWorkflow.core.md` ("Truth is enforced on LIVE plans, never on the historical record")                                                                                                                                                                             | An archived plan is not edited to match today's tree; `path-existence` noise on archived prose is expected                                                                                 | Partially reusable (see §9)                   |

---

## 2. Numbering

| Piece                      | Where                                                                                                                                                                                                                                                                                 | What it enforces                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mkplan.bash`              | `/workspace/CLAUDE/Plan/mkplan.bash` (deployed artefact; template at `/workspace/src/claude_code_hooks_daemon/install/templates/mkplan.bash`)                                                                                                                                         | The only sanctioned way to create a plan. Self-locates its plan dir from `BASH_SOURCE` (symlink-following) or `$MKPLAN_PLAN_DIR`; validates the name to `^[A-Za-z][A-Za-z0-9-]*$`, ≤80 chars; takes an **atomic-`mkdir` lock** (`.mkplan.lock`, 100 attempts × 0.1s, portable — no `flock`) around the whole read-counter → allocate → create → write-counter critical section; releases via an EXIT/INT/TERM trap that only removes a lock this process took.                                                              |
| Counter                    | `git config --local hooksdaemon.latestPlanNumber`, read/written by `/workspace/src/claude_code_hooks_daemon/handlers/utils/plan_numbering.py` (`read_plan_counter`, `write_plan_counter`, `next_plan_number_for_target`, `record_plan_allocation`) and independently by `mkplan.bash` | Authoritative high-water mark, **per repository**, resolved from the *target path* so a nested repo uses its own counter. Lives in `.git/config` so it is stable across branch switches. Bootstraps from a filesystem scan when unset; `record_plan_allocation` is `max()`-semantics so it never goes backwards.                                                                                                                                                                                                            |
| Drift + collision guards   | `mkplan.bash` (post-lock)                                                                                                                                                                                                                                                             | Refuses if the filesystem high-water mark **exceeds** the counter (stale counter ⇒ collision/mis-ordering), printing the exact reconcile command; refuses if `NNNNN-*` already exists active or archived.                                                                                                                                                                                                                                                                                                                   |
| Why bash writes the files  | `mkplan.bash` header comment                                                                                                                                                                                                                                                          | The folder and `PLAN.md` are written with `mkdir`/`cat`, **not** the Write tool, so the daemon's plan-numbering handler never sees the write and cannot double-increment.                                                                                                                                                                                                                                                                                                                                                   |
| Direct-path counter writer | `plan_numbering.record_new_plan_document` (called from `plan_qa_edit.py`)                                                                                                                                                                                                             | An agent hand-writing `NNNNN-name/PLAN.md` still advances the counter — but only for a number in the window `{expected, expected-1}`. The window is load-bearing: recording a typo'd `99999` would raise the counter so high that `counter-sanity` passes everything silently forever.                                                                                                                                                                                                                                      |
| `plan_number_helper`       | `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py` (657 lines, PreToolUse, priority `Priority.PLAN_NUMBER_HELPER`, **terminal DENY** despite the `advisory` tag)                                                                                   | Two jobs: (a) denies bash pipelines that try to *discover* the next number by scanning (`ls -d CLAUDE/Plan/0*` …) and injects the correct number instead — quoted literals are blanked first via `utils.quoted_spans.blank_shell_literal_spans` so prose merely *naming* the dir is not mistaken for a scan; (b) denies `mkdir <plan-dir>/NNNNN-name` outright when `mkplan.bash` is deployed, because `mkdir` claims a number that nothing records until `PLAN.md` lands — the collision surfaces only at the commit gate. |
| Batch counter check        | `/workspace/src/claude_code_hooks_daemon/plan_qa/checks/counter_sanity.py` (COMMIT, block)                                                                                                                                                                                            | A newly-staged plan folder whose number exceeds the git counter is denied.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Collision check            | `checks/no_new_collisions.py` (COMMIT + SWEEP, block)                                                                                                                                                                                                                                 | Two folders must never claim the same number; historic duplicates tolerated via `collision_allowlist` (this repo: `[34, 39, 41]`).                                                                                                                                                                                                                                                                                                                                                                                          |

---

## 3. QA / linting — the `plan_qa` subsystem

**Package**: `/workspace/src/claude_code_hooks_daemon/plan_qa/` — deliberately
daemon-decoupled. Structure:

- `types.py` — `Stage` (EDIT/COMMIT/SWEEP), `Level` (BLOCK/ADVISE), `Finding`, `CheckContext`, `CheckSpec`, and every default constant.
- `model.py` — `PlanDoc` (rigid `PLAN.md` parser, fenced-code-aware), `PlanFolder`, `PlanTree`, journal day-file parsing.
- `readme_index.py` — `ReadmeIndex`: parses the index README into section-classified rows (linked rows, linkless bold rows, multi-number rows) plus the statistics bullets.
- `gitfacts.py` — staged-tree facts for the commit gate.
- `paths.py` — `classify()` returns exactly one `PlanFileKind` (`PLAN_DOCUMENT` / `PLAN_INDEX` / `JOURNAL_DAYFILE` / `JOURNAL_OTHER` / `SUPPORTING_DOC` / `OUTSIDE`). Journal containment is tested **before** the `PLAN.md` filename, so `JOURNAL/PLAN.md` can never be read as plan material. Classification is config-**independent** by design (layout only, never policy).
- `checks/` — 36 check modules, each exposing `CHECK` or `CHECKS`, assembled by `checks/__init__.py:all_checks()`.
- `runner.py` — `run_stage(stage, context)`: filter-and-accumulate, plus the one place `daemon.exclude_paths` is applied.
- `report.py`, `remedy.py` — rendering.
- `close_approval.py` — one-shot human approval tokens.

### 3.1 The three surfaces

| Stage              | Handler                                                                                                             | Mode knob                           | Default                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------------- |
| 1 — edit-time lint | `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_qa_edit.py` (PreToolUse, Write/Edit)            | `plan_workflow.qa.edit_mode`        | `block`                                   |
| 2 — commit gate    | `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_qa_commit_gate.py` (PreToolUse, `git commit`)   | `plan_workflow.qa.commit_gate_mode` | `warn` upstream; **`block` in this repo** |
| 3 — session sweep  | `/workspace/src/claude_code_hooks_daemon/handlers/session_start/plan_qa_sweep.py` (SessionStart, new sessions only) | `plan_workflow.qa.sweep_mode`       | `advise`                                  |

Stage 1 is hot-path cheap: single-file invariants only, no tree scan, no git
subprocess — with one deliberate exception (the counter write described in §2).
Stage 2 never fires for commits inside a foreign repo, and degrades to a
structural warning if the plan dir is missing. Stage 3 is silent on a clean tree.

A fourth consumer exists: `/workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/merge_qa_report.py` re-runs the sweep after a merge.

### 3.2 CLI

`/workspace/src/claude_code_hooks_daemon/daemon/cli.py:5675` (`cmd_plan_qa`), args at `:8207`:

```
hooks-daemon plan-qa --sweep            # whole tree, exit 1 on findings (CI-able)
hooks-daemon plan-qa --check-staged     # staged-tree commit-gate checks
hooks-daemon plan-qa --lint <FILE>      # single-file edit-stage checks
                     [--json] [--project-root PATH]
```

Also: `hooks-daemon approve-plan-close NNNNN` (`:8700`) and
`hooks-daemon deploy-plan-workflow` (`:9027`). Skill doc:
`/workspace/src/claude_code_hooks_daemon/skills/hooks-daemon/plan-qa.md`.

### 3.3 The full check catalogue (36 checks)

Registration order and stage pairing come from
`/workspace/src/claude_code_hooks_daemon/plan_qa/checks/__init__.py:all_checks()`.
All files are under `plan_qa/checks/`.

**Document-level rules — dual EDIT + SWEEP** (written once via
`common.document_rule_checks`; the sweep half is what examines plans already on
disk, so a violation predating the rule is still looked at):

| Check ID                 | Level          | What it enforces                                                                                                                    |
| ------------------------ | -------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `status-line-present`    | BLOCK (A2, E8) | A `PLAN.md` must contain a parseable `**Status**:` line                                                                             |
| `status-enum-and-date`   | BLOCK (A1)     | The value must be one of the seven `PlanStatus` tokens; optional `(YYYY-MM-DD)` qualifier, required only if `require_terminal_date` |
| `header-body-coherence`  | BLOCK (A3, A1) | Header claiming `Not Started`/`In Progress` while the body is all-ticked (or says "ALL DONE")                                       |
| `task-grammar`           | ADVISE (E6)    | Ad-hoc markers `[✓]`/`[⏳]`/`[~]` are unparseable by tooling                                                                        |
| `path-existence`         | ADVISE (E5)    | Backticked `src/...`-style repo paths in a plan that no longer exist                                                                |
| `journal-dayfile-naming` | ADVISE         | Day-file matches `NNNNN-Journal-YY-MM-DD.md`, right plan number, today/yesterday                                                    |
| `journal-entry-ordering` | ADVISE         | Entry times increase down the day-file                                                                                              |

**EDIT-only — checks about the ACT OF WRITING**, with rationale recorded in
`common.WRITE_ACT_ONLY_RULES` for why each has no batch twin:

| Check ID                     | Level                | What it enforces / why edit-only                                                                                                                                                                                                                             |
| ---------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `template-metadata`          | ADVISE (E7)          | Brand-new documents carry the full template header. Scoped to `file_exists_before == False`; everything in a scan already exists                                                                                                                             |
| `terminal-placement-hint`    | ADVISE (C1,C2,C3)    | Header already terminal but folder still in the active root. No sweep twin — `location-status-coherence` already reports it at BLOCK                                                                                                                         |
| `archive-immutability`       | ADVISE (A5)          | An **archived** plan is being edited. An untouched archived plan is the correct state, not a finding                                                                                                                                                         |
| `plan-doc-size`              | tiered ADVISE→BLOCK  | Read-cost tiers: advisory >18,000 B / >350 lines, warning >25,000 / >500, block >35,000 / >900. **Only an edit that GROWS an over-limit doc blocks** — shrinking is silent, same-size only advises. Escape hatch `<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: … -->` |
| `journal-dayfile-is-today`   | **BLOCK by default** | A day-file edit whose embedded date is not exactly today. Own knob `journal.today_only_mode`, deliberately not advise-first                                                                                                                                  |
| `journal-append-only`        | ADVISE               | The edit only appends. No before/after to compare in a batch scan                                                                                                                                                                                            |
| `journal-entry-future-dated` | ADVISE               | An entry timestamped ahead of the clock. Edit-only because after the write the append-only contract forbids fixing it — an unfixable finding trains readers to skim                                                                                          |

**Cross-file tree checks — dual COMMIT + SWEEP:**

| Check ID                    | Level                  | What it enforces                                                                                                                                               |
| --------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no-new-collisions`         | BLOCK (D1)             | Two folders claiming one number                                                                                                                                |
| `row-folder-bijection`      | BLOCK (B1,B2,B7)       | Every folder has exactly one index row and vice versa                                                                                                          |
| `stats-recount`             | BLOCK (B5)             | The README's hand-maintained statistics bullets match reality                                                                                                  |
| `structure-archive-dirs`    | BLOCK (C3)             | Plan dir has a README index (BLOCK) and a `Completed/` (BLOCK); `Cancelled/` missing is ADVISE; folders in `OTHER` locations and stray root files are reported |
| `location-status-coherence` | BLOCK (A1,A5,C1,C2,E8) | Physical folder location matches what `PLAN.md` claims                                                                                                         |

**Plan-index shape — EDIT + COMMIT + SWEEP:**

| Check ID           | Level  | What it enforces                                                                                                                   |
| ------------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `index-row-length` | BLOCK  | ≤500 chars per row (`DEFAULT_INDEX_ROW_MAX_CHARS`). Deliberately **not** config-driven — the batch guard imports the same constant |
| `index-no-log`     | ADVISE | The index states current truth only; it is a pointer table, not a log                                                              |

**Plan-index retention — COMMIT + SWEEP (no EDIT: a mid-archival write is legitimately over):**

| Check ID                 | Level | What it enforces                                                                                                                           |
| ------------------------ | ----- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `index-retention-window` | BLOCK | Main index keeps only the newest 30 completed rows (`DEFAULT_COMPLETED_ROWS_MAX`); older rows move **verbatim** into `Completed/README.md` |

**COMMIT-only:**

| Check ID                      | Level                | What it enforces                                                                                                                                  |
| ----------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `index-at-birth`              | BLOCK (B1,B2,D2,G2)  | A commit creating a new plan folder must stage its README row in the same commit                                                                  |
| `counter-sanity`              | BLOCK (D1)           | A staged plan number must not exceed the git counter                                                                                              |
| `terminal-state-atomic`       | BLOCK (C1,C2,C3,B3)  | A status flip to terminal must ship the `git mv` + README row + stats recount in ONE commit                                                       |
| `archived-status-coherence`   | BLOCK (C1,C2)        | Gap-filler for what `location-status-coherence`'s COMMIT registration cannot see                                                                  |
| `same-commit-plan-doc`        | ADVISE/BLOCK (G1,E1) | A commit message claiming plan N must stage plan N's files                                                                                        |
| `plan-ref-format`             | ADVISE (G3)          | Commit touching the plan dir uses the `Plan NNNNN: …` reference format                                                                            |
| `journal-entry-with-progress` | ADVISE               | A commit changing `PLAN.md` **tasks** should also stage a journal entry                                                                           |
| `journal-completion-entry`    | ADVISE               | A terminal status flip should ship a closing journal entry (`journal.enforce_on_completion`)                                                      |
| `plan-shrink-without-journal` | ADVISE               | A commit shrinking `PLAN.md` sharply while staging neither a journal entry nor a new supporting doc — usually deletion masquerading as relocation |

**SWEEP-only:**

| Check ID                 | Level             | What it enforces                                                                 |
| ------------------------ | ----------------- | -------------------------------------------------------------------------------- |
| `staleness-nag`          | ADVISE (A4,A6,E3) | `In Progress` with no commit activity for `staleness_days` (30)                  |
| `dormant-honesty`        | ADVISE (A6)       | `In Progress` after **twice** the staleness window — say `Dormant` or close it   |
| `claim-spotcheck-queue`  | ADVISE (B3)       | Active-section rows whose status text was only true at the moment it was written |
| `journal-folder-present` | ADVISE            | An `In Progress` plan ≥ `grandfather_before` with no `JOURNAL/`                  |
| `journal-freshness`      | ADVISE            | A plan whose newest day-file is older than `freshness_days` (3)                  |

**Sins catalogue**: `sins=("A1", …)` tags trace each check to the original
31-sin audit spec (provenance noted in `CLAUDE/Plan/README.md` and Plan 00144's
own `PLAN.md`). The spec itself lives outside the repo
(`untracked/hooks-daemon-plan-verify-qa.md`) — the tags are the surviving record.

**Grandfathering**: `common.level_for_plan` downgrades BLOCK→ADVISE for plans
in `legacy_plan_allowlist`; `common.commit_scoped_level` downgrades a whole-tree
finding when the commit did not touch that plan (the fix that made
`commit_gate_mode: block` safe — measured over 253 commits, 18 denials of which
7 were sticky whole-tree failures; after narrowing, 11 denials, all true positives).

---

## 4. Handlers that participate

| Handler                             | File                                                                                   | Event                          | Plan-specific?                                                                                                                                                                                                                                                                                                  |
| ----------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan_workflow`                     | `handlers/pre_tool_use/plan_workflow.py`                                               | PreToolUse                     | **Plan-specific.** Advisory guidance when creating plan files; points at `plan_workflow.workflow_docs`                                                                                                                                                                                                          |
| `plan_number_helper`                | `handlers/pre_tool_use/plan_number_helper.py`                                          | PreToolUse (Bash)              | **Plan-specific**, but the *pattern* (deny ad-hoc allocation, inject the right number, deny hand-`mkdir`) is fully generic                                                                                                                                                                                      |
| `plan_qa_edit`                      | `handlers/pre_tool_use/plan_qa_edit.py`                                                | PreToolUse (Write/Edit)        | Plan-specific shell over a **generic** staged runner                                                                                                                                                                                                                                                            |
| `plan_qa_commit_gate`               | `handlers/pre_tool_use/plan_qa_commit_gate.py`                                         | PreToolUse (Bash `git commit`) | Same                                                                                                                                                                                                                                                                                                            |
| `plan_qa_sweep`                     | `handlers/session_start/plan_qa_sweep.py`                                              | SessionStart                   | Same                                                                                                                                                                                                                                                                                                            |
| `plan_workflow_asset_checker`       | `handlers/session_start/plan_workflow_asset_checker.py`                                | SessionStart                   | **Plan-specific.** Advises when `mkplan.bash` is absent while the workflow is enabled; names `deploy-plan-workflow` as the fix. `mkplan.bash` is the definitive signal (daemon-owned); journal assets are client-owned so their absence alone is not a trigger                                                  |
| `plan_time_estimates`               | `handlers/pre_tool_use/plan_time_estimates.py`                                         | PreToolUse                     | **Plan-specific policy, generic mechanism.** Blocks time estimates in plan docs (`R-PLAN-TIME-ESTIMATE`); explicitly exempts journal files via `plan_qa.paths.is_journal_file`                                                                                                                                  |
| `plan_close_approval`               | `handlers/pre_tool_use/plan_close_approval.py`                                         | PreToolUse                     | **Plan-specific and terminal-status-shaped — OMIT for Jobs.** Gates the *flip* to Complete/Cancelled/Superseded when `close_requires_human_approval`                                                                                                                                                            |
| `recovery_cron_advisor`             | `handlers/post_tool_use/recovery_cron_advisor.py`                                      | PostToolUse                    | **Plan-specific trigger, generic idea.** Fires on the three `PLAN.md` lifecycle moments (creation / task-icon edit / Complete flip) and advises on the failsafe recovery cron. The COMPLETION branch is a terminal-state concept                                                                                |
| `goal_injection`                    | `handlers/post_tool_use/goal_injection.py`                                             | PostToolUse                    | **Plan-specific trigger.** A `PLAN.md` write resulting in `**Status**: In Progress` writes a `<session>.goal-intent` signal the ccy PTY supervisor types as `/goal`                                                                                                                                             |
| goal ledger                         | `utils/goal_ledger.py` (`GoalLedger`, `goal-ledger.json`)                              | —                              | Daemon-side memory of every emitted goal, keyed `(plan_number, session_id)`; detects displacement (Claude Code's `/goal` slot is a single last-writer-wins value) and **retires entries when the plan reaches a terminal status or leaves the active dir**. Status parsing delegated to `plan_qa.model.PlanDoc` |
| `auto_continue_stop`                | `handlers/stop/auto_continue_stop.py:789`                                              | Stop                           | Uses the goal ledger to challenge a stop while any ledgered plan is still `In Progress`                                                                                                                                                                                                                         |
| `markdown_organization`             | `handlers/pre_tool_use/markdown_organization.py`                                       | PreToolUse                     | **Generic with a plan branch.** Redirects flat `{plan_dir}/*.md` writes into the numbered folder (Claude Code's `plansDirectory` mode, `:502-521`); enforces `plansDirectory` ↔ `plan_workflow.directory` sync (`R-MARKDOWN-PLAN-SYNC`, `:656-720`) when `enforce_claude_code_sync`                             |
| `dispatch_declaration`              | `handlers/pre_tool_use/dispatch_declaration.py`                                        | PreToolUse (`Task`)            | **Generic.** Requires every dispatch prompt to declare where long-form output goes — a plan-folder path (⇒ `subagent-reports/`) or an explicit "not plan work" + destination. Advisory by default, `strict` opt-in                                                                                              |
| `subagent_report_size_blocker`      | SubagentStop                                                                           | —                              | **Generic.** The return-side half of the same contract                                                                                                                                                                                                                                                          |
| `merge_qa_report`                   | `handlers/post_tool_use/merge_qa_report.py`                                            | PostToolUse                    | Re-runs the plan (and docs) sweep after a merge                                                                                                                                                                                                                                                                 |
| `deployed_artefact_drift`           | `handlers/session_start/deployed_artefact_drift.py`                                    | SessionStart                   | **Generic.** PLANNING-tagged; reports a deployed file that has drifted from its template (covers `mkplan.bash`)                                                                                                                                                                                                 |
| `failsafe_cron_blockage_suppressor` | `handlers/user_prompt_submit/…`                                                        | UserPromptSubmit               | Generic; PLANNING-tagged                                                                                                                                                                                                                                                                                        |
| `plan_done_requires_holding_area`   | `/workspace/.claude/project-handlers/pre_tool_use/plan_done_requires_holding_area.py`  | PreToolUse                     | **PROJECT-ONLY and terminal-shaped.** Denies a flip to Complete unless Success Criteria name the release holding area                                                                                                                                                                                           |
| `plan-promotion-disposition`        | `/workspace/src/claude_code_hooks_daemon/docs_qa/checks/plan_promotion_disposition.py` | docs_qa STAGED                 | **Terminal-shaped.** At terminal flip, every supporting doc needs a promote/historical/delete disposition in the closing journal entry (R8)                                                                                                                                                                     |

**Config injection**: `/workspace/src/claude_code_hooks_daemon/handlers/registry.py:596-625` — any handler tagged `planning` gets `track_plans_in_project`, `plan_workflow_docs`, `enforce_claude_code_sync`, `_plan_qa` (the whole `qa` policy object) and `close_requires_human_approval` injected, all `None` when `plan_workflow.enabled` is false. **Zero per-handler options.** This DI seam is the single cleanest thing to copy for Jobs.

**Batch guard (not a handler)**: `/workspace/tests/integration/test_plan_index_navigability.py` — bounds total index size and per-row length, importing `DEFAULT_INDEX_ROW_MAX_CHARS` and `DEFAULT_COMPLETED_ROWS_MAX` from `plan_qa.types` so the fast loop and the batch guard cannot disagree. Its docstring records why: a write-time guard never sees what is already on disk (arrives by merge, script, or worktree).

---

## 5. Config

Top-level block, model at `/workspace/src/claude_code_hooks_daemon/config/models.py:824` (`PlanWorkflowConfig`); live values at `/workspace/.claude/hooks-daemon.yaml:1086`.

```
plan_workflow:
  enabled: false                      # OPT-IN (default False since Plan 00137)
  directory: "CLAUDE/Plan"            # repo-relative, validated
  workflow_docs: "CLAUDE/PlanWorkflow.md"
  enforce_claude_code_sync: false     # plansDirectory ↔ directory
  close_requires_human_approval: false
  scripts:                            # PlanWorkflowScriptsConfig :722
    enabled: false
    root_marker: ""                   # REQUIRED when enabled, no default, must not be .git
    delegate / check_flag / force_color_var / scrubber / track_run_logs
  qa:                                 # PlanWorkflowQaConfig :630
    enabled: true
    completed_dir: Completed
    cancelled_dir: Cancelled          # None ⇒ use completed_dir
    edit_mode: block                  # block | warn | off
    commit_gate_mode: warn            # block | warn | off   (this repo: block)
    sweep_mode: advise                # advise | off
    require_terminal_date: false
    staleness_days: 30
    legacy_plan_allowlist: []
    collision_allowlist: []           # this repo: [34, 39, 41]
    extra_root_files: []
    journal:                          # PlanWorkflowQaJournalConfig :487
      enabled: true
      mode: advise                    # only journal-dayfile-naming honours block
      dir_name: JOURNAL
      freshness_days: 3
      enforce_on_completion: false
      grandfather_before: 0           # this repo: 163
      today_only_mode: block          # journal-dayfile-is-today, own knob
    plan_doc_size:                    # PlanWorkflowQaPlanDocSizeConfig :561
      advisory/warning/block × bytes/lines
```

Two subtleties worth carrying into any Jobs config:

1. **Sub-block modes are ceilings, not guarantees** — `journal.mode: block` only denies when `edit_mode` is *also* `block`; `edit_mode: off` disables both journal edit checks regardless of `journal.enabled`. Documented at `models.py:499-506` and pinned by `tests/unit/handlers/pre_tool_use/test_plan_qa_edit.py`.
2. **`root_marker` has no default on purpose** — a wrong default silently resolves to *some* directory and an orchestrator then operates on the wrong repo.

Legacy migration: `models.py:2087-2110` promotes per-handler `track_plans_in_project` options into the top-level block, but only when no explicit `plan_workflow` block exists.

---

## 6. Docs — who owns what

| Doc                                                                      | Owner                                                                               | Owns                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/workspace/CLAUDE/core/PlanWorkflow.core.md`                            | **DAEMON** — overwritten on every deploy, never hand-edit                           | The shared baseline: core principles, the niggles ledger, execution strategies, directory layout, `subagent-reports/` contract, numbering, `PLAN.md` structure, status icons, plan QA overview + CLI + allowed status tokens, "truth is enforced on LIVE plans", TDD integration, the six workflow steps, failsafe recovery cron, **definition of done (merged into main, never released)**, the Plan Completion Checklist, TodoWrite-vs-Plans, four plan templates, best practices, git integration, index shape, AI-agent guidelines |
| `/workspace/CLAUDE/PlanWorkflow.md`                                      | **This project**                                                                    | Opens with a markdown link to the core (deliberately not an `@`-import), then layers only project specifics: self-install path prefix (`bin/hooks-daemon`), the QA suite command, TDD/coverage figures, the 30-row retention window, core-handler-vs-project-handler plan-template deltas                                                                                                                                                                                                                                              |
| `/workspace/CLAUDE/PlanJournalling.md`                                   | Client-owned, seeded from `install/templates/PlanJournalling.md`, never overwritten | Why journal; the three-file SSoT contract table (`PLAN.md` / supporting doc / `JOURNAL/`) with write/content/read/size columns; the read-contract-justifies-write-contract argument; size tiers and the three non-deletion remedies; layout; entry grammar; append-only discipline; hand-off convention; good-vs-noise; lifecycle touchpoints; and a closing **POLICY vs CONVENTION** section naming the only four daemon-enforced checks                                                                                              |
| `/workspace/CLAUDE/Plan/CLAUDE.md`                                       | Client-owned, seeded by the installer                                               | Directory-local conventions: pointers to the two docs above, the niggles-ledger rule, plan sources (GitHub issue linkage), "always commit the plan folder alongside the work", superseded-revision naming (`PLAN-v1.md` + `CRITIQUE-v1.md`), atomic archive moves, the 30-row ageing-out rule                                                                                                                                                                                                                                          |
| `/workspace/CLAUDE/DirectoryRoles.md`                                    | This project                                                                        | The canonical directory-role table; `:84-93` gives the plan directory's role and names its enforcement (`plan_qa_edit`/`plan_qa_commit_gate`/`plan_qa_sweep` + `plan_time_estimates`). States that **directory names are configuration, not truths of the document**                                                                                                                                                                                                                                                                   |
| `/workspace/CLAUDE/Plan/README.md`                                       | Client-owned                                                                        | The index itself: Active / Completed / Blocked / Cancelled sections and the statistics bullets                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `/workspace/src/claude_code_hooks_daemon/skills/hooks-daemon/plan-qa.md` | Daemon                                                                              | The on-demand CLI skill page                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

---

## 7. Deployment into a client project

Entry point: `/workspace/src/claude_code_hooks_daemon/install/plan_workflow.py`.

- `deploy_plan_workflow_if_enabled(project_root, config_path)` at `:480` is the **single decision site**, called identically by `install_version.sh` and **both** `upgrade_version.sh` paths (full + already-at-target fast path). It replaced a `PLAN_WORKFLOW=yes` env gate that was orthogonal to config and never ran on upgrade — the v3.24.0 field bug where `plan_number_helper` pointed at a `mkplan.bash` the upgrade never deployed (Plan 00136). A Jobs system needs exactly this shape or it will reproduce that bug.
- `bootstrap_plan_workflow(project_root, plan_dir_name, deploy_scripts_library)` at `:218` does the work.
- Also reachable on demand: `hooks-daemon deploy-plan-workflow` (`daemon/cli.py:9027`).

What gets deployed, and the **ownership rule for each** (this is the part a Jobs system must replicate item by item):

| Asset                                              | Ownership                                 | Behaviour                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `{plan_dir}/` and `{plan_dir}/Completed/`          | —                                         | `mkdir(parents, exist_ok)`                                                                                                                                                                                                                                                                                                                                   |
| `README.md` (index)                                | **Client**                                | Seeded from `_README_TEMPLATE`; skipped if present                                                                                                                                                                                                                                                                                                           |
| `CLAUDE.md` (lifecycle)                            | **Client**                                | Seeded from `_CLAUDE_MD_TEMPLATE`; skipped if present                                                                                                                                                                                                                                                                                                        |
| `mkplan.bash`                                      | **DAEMON**                                | Overwritten every run, mode `0o755`, so audit fixes reach existing installs. Its absence is the `plan_workflow_asset_checker` trigger                                                                                                                                                                                                                        |
| `_planlib.inc.bash`                                | **DAEMON**, separate opt-in               | Only when `plan_workflow.scripts.enabled`; mode `0o644` — a **separate, less-privileged mode constant** because it is sourced, never executed                                                                                                                                                                                                                |
| `_TEMPLATE_.md`                                    | **Client**                                | Seeded when absent, **never** overwritten. A daemon-owned snapshot `.plan-template-default.md` is kept alongside; diffing it against the new bundled default surfaces upstream template changes on upgrade (capped at 40 diff lines)                                                                                                                         |
| `_JOURNAL_TEMPLATE_.md`                            | **Client**                                | Seeded when absent, never overwritten. Its **presence is the "this project journals" marker** that gates `mkplan.bash`'s `JOURNAL/` scaffolding                                                                                                                                                                                                              |
| `PlanJournalling.md`                               | **Client**                                | Seeded when absent, never overwritten                                                                                                                                                                                                                                                                                                                        |
| `.claude/agents/hooks-daemon-plan-dedupe-scout.md` | **DAEMON**, via `install/agent_assets.py` | Refreshes a pristine copy (current or any previously-shipped revision); never clobbers a customised one, warns loudly instead                                                                                                                                                                                                                                |
| `CLAUDE/core/PlanWorkflow.core.md`                 | **DAEMON**, via a *separate* gate         | **Deliberately not deployed from here** — `install/core_docs.py` gates each core doc on the subsystem whose guidance names it, because `plan_workflow.enabled` is opt-in and hanging core docs off it left stock installs missing `CLAUDE/Worktree.md` while `worktree_file_copy` went on naming it. `hooks-daemon deploy-core-docs` is the dev-loop refresh |

---

## 8. Design question 1 — what is genuinely PLAN-specific and would be WRONG to copy

A Plan is a **one-shot arc with a terminal state**. A Job never completes. Every
piece below encodes "completion" and would be actively harmful — not merely
useless — in a Jobs tree, because each one would either fire forever or never fire.

### 8.1 The status vocabulary and its terminal set — OMIT

`PlanStatus` (`Not Started`/`In Progress`/`Complete`/`Blocked`/`Cancelled`/`Superseded`/`Dormant`) and `TERMINAL_STATUSES` are the root of it. A Job has no `Complete` and no `Not Started` — the meaningful axis is *active / paused / retired*, and its per-run axis is *succeeded / failed / skipped*. Copying `PlanStatus` would force a Job to lie about itself, and every check keyed on it would then be enforcing a lie.

Concretely wrong to copy: `status-enum-and-date`, `header-body-coherence` (a Job's tasks are the **recurring** work — an all-ticked body means "this run finished", not "this job is over"), `terminal-placement-hint`, `archived-status-coherence`, `location-status-coherence`.

### 8.2 Archival — OMIT

`Completed/` + `Cancelled/`, `PlanLocation`, `terminal-state-atomic`, `archive-immutability`, `structure-archive-dirs`' archive half, and the `git mv`-in-the-same-commit rule. A Job never moves. Retiring one is a *rare admin act*, not a lifecycle stage, and it does not need an atomicity invariant spanning four files. The `index-retention-window` rule exists **only** because completed rows accumulate — a Jobs index has a bounded, roughly constant row count (one per job), so the retention machinery has nothing to retain.

### 8.3 The Plan Completion Checklist and everything hanging off it — OMIT

Seven steps in `PlanWorkflow.core.md`, plus:

- `plan_close_approval` (`close_requires_human_approval`) — gates a flip that does not exist.
- `/workspace/.claude/project-handlers/pre_tool_use/plan_done_requires_holding_area.py` — "every release-bound consequence is in the holding area" is a *one-shot delivery* question.
- `docs_qa` `plan-promotion-disposition` — "at terminal flip, disposition every supporting doc" has no trigger. **But the underlying concern is real for Jobs and needs a different trigger**: a Job accretes supporting docs forever, so it needs a *periodic* disposition review, not a terminal one. This is the one place where the Plan rule is right in substance and wrong in mechanism.
- `journal-completion-entry`.
- The "definition of done: merged into main, never released" section — a Job has no done.

### 8.4 Staleness and dormancy nags — OMIT (they invert)

`staleness-nag` fires when a plan claims `In Progress` with no commits for 30 days; `dormant-honesty` fires at 60. For a Job, *quiet is the normal state between runs* — a monthly security review is silent for 29 days by design, and both checks would nag every single day of it.

The Jobs equivalent is the **opposite polarity**: nag when a job has *missed its schedule* — "this job's cadence is monthly and the last run was 47 days ago". That needs the job's declared cadence, which Plans have no concept of. Same for `journal-freshness` (3 days): for a Job, freshness is measured against the schedule, not against a fixed window.

### 8.5 The `In Progress` → goal-injection coupling — OMIT as written

`goal_injection` fires on a `PLAN.md` write producing `**Status**: In Progress`, and the goal ledger **retires an entry when the plan reaches a terminal status**. A Job would enter the ledger once and never leave, so `auto_continue_stop` would challenge every stop forever. If Jobs want goal injection at all, the lifetime must be the **run**, not the job.

### 8.6 `recovery_cron_advisor`'s COMPLETION branch — OMIT

The creation/progress branches translate fine. The completion branch ("keep the cron while the session is live") has no analogue.

### 8.7 `index-at-birth` and `counter-sanity` — REUSE, unchanged in substance

These are the two that survive the transition untouched: a new job folder must stage its index row in the same commit, and a staged number must not exceed the counter. Neither mentions completion.

---

## 9. Design question 2 — what is really generic, and the refactor

Strip the plan-specific policy away and what remains is a reusable subsystem I would name **"numbered document tree with journals and QA"**. Roughly two-thirds of the machinery is already this, and three of its four layers are already policy-free.

### 9.1 Already generic today (share as-is, no refactor needed)

| Component                                                               | Why it is already generic                                                                                                                                                                                            |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan_qa/types.py` `Stage`/`Level`/`Finding`/`CheckSpec`/`CheckContext` | Pure data. `CheckContext` carries policy as **plain values** precisely so the package stays daemon-decoupled                                                                                                         |
| `plan_qa/runner.py`                                                     | 40 lines of filter-and-accumulate plus exclusion. Knows nothing about plans                                                                                                                                          |
| `plan_qa/checks/common.py` `document_rule_checks`                       | The EDIT+SWEEP dual-registration adapter — write a rule once against a `DocumentTarget`, get both surfaces                                                                                                           |
| `plan_qa/gitfacts.py`                                                   | Staged-tree facts. Nothing plan-shaped                                                                                                                                                                               |
| The three-surface pattern itself                                        | Edit lint (cheap, single-file) / commit gate (cross-file, at the moment drift becomes history) / session sweep (whole-tree, advisory). This is the single most valuable transferable idea here                       |
| The mode ladder                                                         | `block`/`warn`/`off` per surface, `advise`/`off` for sweep, plus allowlist grandfathering                                                                                                                            |
| `dispatch_declaration` + `subagent_report_size_blocker`                 | Already destination-agnostic — `dispatch_declaration` explicitly supports "not plan work + declared destination". **A Jobs folder should be added as a recognised declaration target, not given a parallel handler** |
| `install/agent_assets.py`                                               | Already a generic asset-deploy subsystem with a pristine-vs-customised ownership rule                                                                                                                                |
| `registry.py` tag-based config injection                                | `"planning" in instance.tags` → inject the config object. A `"jobs"` tag costs ~15 lines                                                                                                                             |

### 9.2 Near-generic — the concrete refactor I would recommend

Three modules are *structurally* generic but *textually* plan-named. This is where duplication would actually hurt.

**(a) `plan_qa/paths.py` → a shared `document_tree/paths.py`.**
`classify()` already answers a purely structural question: given a path, a tree root, and a journal dir name, which of {document, index, journal day-file, journal other, supporting doc, outside} is it? Its own docstring insists classification is **config-independent by design**. The only plan-specific things in it are the constants `PLAN.md` and `README.md` — parameters, not logic. A Jobs copy would be the same 160 lines with `JOB.md` substituted, and the `JOURNAL/PLAN.md`-ambiguity defect the module exists to prevent by construction would then need preventing twice.

**(b) The journal subsystem → shared outright.**
`parse_journal_dayfile_name`, `_scan_journal`, `JournalDayfileName`, and the four journal checks (`journal-dayfile-naming`, `journal-append-only`, `journal-folder-present`, `journal-freshness`) plus the two newer ones (`journal-entry-ordering`, `journal-entry-future-dated`) and `journal-dayfile-is-today` are entirely about *an append-only dated log inside a numbered folder*. Nothing in them is plan-shaped except the `NNNNN-Journal-` filename prefix and, in `journal-folder-present`, the `In Progress` gate.

This is the single strongest share case, because a **Job's journal is more load-bearing than a Plan's**: it is the per-run record, which is the whole point of the Jobs concept. Duplicating it means the append-only guarantee — the property the whole design rests on — exists in two implementations that will drift.

**(c) The numbering/counter layer → parameterise the git-config key.**
`handlers/utils/plan_numbering.py` is generic apart from one constant (`hooksdaemon.latestPlanNumber`) and the `PLAN.md` filename in `_plan_number_of_new_document`. `mkplan.bash` is generic apart from `PLAN.md`, `_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md` and the counter key — it *already* parameterises its own root via `$MKPLAN_PLAN_DIR`, and it *already* renders a client-owned template with `{{PLACEHOLDER}}` substitution.

**Recommended shape**: `mkjob.bash` as a thin symlink-or-wrapper over the same script driven by four env vars (root, doc filename, template name, counter key) rather than a forked copy. The script's own header already documents the symlink-vs-real-file subtlety (`BASH_SOURCE` resolves through symlinks, so a symlink *into* the tree pointing at a file *outside* it needs the explicit `MKPLAN_PLAN_DIR` override) — that is exactly the packaging a shared scaffolder lands in, and it is already handled.

### 9.3 The cost of not doing it

Concrete, in descending severity:

1. **The lock/counter/drift-guard logic gets copied.** That block in `mkplan.bash` is ~60 lines of genuinely subtle concurrency code: atomic-`mkdir` lock, trap that only releases a lock this process owns, stale-counter drift guard, explicit collision check, high-water-mark write *after* a successful write. A second copy will be forked, then one of the two will get a fix. The failure mode is silent number collision discovered at the commit gate — which is precisely the incident `plan_number_helper`'s `mkdir` deny exists to prevent.

2. **Two counter writers, two windows.** `record_new_plan_document`'s `{expected, expected-1}` window has a documented reason (a typo'd `99999` would raise the counter so high that `counter-sanity` silently stops checking). A Jobs copy written without that reasoning is a plausible regression that reports clean while having stopped checking.

3. **Two journal append-only implementations.** The one guarantee both systems depend on, verified twice, drifting independently.

4. **The `JOURNAL/PLAN.md` class of defect returns.** `paths.py` removes it *by construction* by testing journal containment before the document filename. A hand-written Jobs predicate is unlikely to get that ordering right first time, and the symptom (plan/job rules applied to journal content, or vice versa) is quiet.

5. **The two-definitions drift `DEFAULT_INDEX_ROW_MAX_CHARS` was written to prevent.** Its comment spells out the trap: a configurable value raised to 800 while the batch guard still failed at 500. Two independent index-row limits reproduce it across subsystems instead of within one.

6. **Doubling the surface `registry.py` must inject into, and the config a client must keep in sync.** Today one tag drives five injected values into eleven handlers with zero per-handler options. Two parallel trees means two of everything, and `plansDirectory`-style sync bugs (`R-MARKDOWN-PLAN-SYNC`) get a second instance.

### 9.4 What I would *not* share

- **The check catalogue itself.** The 36 checks encode *plan* policy. Jobs needs its own catalogue registered against the same `CheckSpec`/`Stage`/`Level` types and run by the same runner. Sharing the framework and forking the policy is the correct split — and it is already the shape `docs_qa` uses (`docs_qa/types.py` mirrors `plan_qa/types.py` with its own `CheckStage`/`Severity`), so there is in-repo precedent for the *wrong* direction too: `docs_qa` duplicated the type layer rather than sharing it. That duplication is a warning, not a licence.
- **The workflow docs.** `PlanWorkflow.core.md` is ~1,000 lines of plan-lifecycle prose. A `JobWorkflow.core.md` should be written fresh and be much shorter — a Job's contract is genuinely simpler, because most of the plan document is about completing and archiving.
- **`_planlib.inc.bash`.** Independent opt-in, orthogonal to either concept.

### 9.5 Suggested sequencing

If the refactor is judged worth it, the lowest-risk order is:

1. Extract `paths.py` + the journal model/checks into a shared module, parameterised by (tree root, document filename, journal dir name, day-file prefix), with `plan_qa` re-exporting for back-compat. No behaviour change, fully covered by existing tests.
2. Parameterise `plan_numbering.py`'s counter key and document filename; add a `mkjob.bash` wrapper over the same `mkplan.bash` body.
3. Add a `jobs` handler tag and the `job_workflow` config block, reusing `registry.py`'s injection pattern verbatim.
4. Write the Jobs check catalogue against the existing `CheckSpec` types — schedule-adherence in place of staleness, run-outcome in place of terminal status, no archival checks at all.

If the refactor is judged *not* worth it now, the one piece I would still share rather than fork is the **journal subsystem** (9.2b), because it is the property the Jobs concept is built on and the one whose drift would be least visible.

---

## 10. Loose ends worth flagging to the plan author

- The 31-sin audit catalogue the `sins=` tags reference lives at `untracked/hooks-daemon-plan-verify-qa.md` — untracked, so it is not in the repo. The tags in `checks/*.py` are now the only surviving record of that mapping. If Jobs wants an equivalent provenance trail, decide where it lives *before* writing the checks.
- `docs_qa` duplicated `plan_qa`'s type layer (`Stage`→`CheckStage`, `Level`→`Severity`) rather than sharing it. Jobs would make three. Worth a deliberate ruling rather than a default.
- `plan_workflow.enabled` defaults to **False**; the whole subsystem is opt-in and a stock install deploys nothing. Jobs should match — and, per the `core_docs.py` note at `install/plan_workflow.py:253-260`, a `JobWorkflow.core.md` must be gated by its *own* subsystem gate, not hung off the Jobs bootstrap, or a stock install ends up with guidance naming a document it never received.
