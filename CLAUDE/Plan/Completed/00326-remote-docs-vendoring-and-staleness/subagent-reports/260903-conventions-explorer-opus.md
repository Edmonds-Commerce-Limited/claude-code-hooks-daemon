# Plan + markdown house conventions (baseline for Plan 00326's PLAN.md)

Report for the team lead. All paths absolute.

---

## 0. The 00326 scaffold as it stands on disk

`/workspace/CLAUDE/Plan/00326-remote-docs-vendoring-and-staleness/` already
contains `PLAN.md`, `JOURNAL/` and a `BRAINSTORM.md`. The scaffolded `PLAN.md`
is the daemon template rendered verbatim:

```markdown
# Plan 00326: remote docs vendoring and staleness

**Status**: Not Started
**Created**: 2026-09-03
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

<!-- 2-3 paragraphs: what this plan achieves and why. -->

## Goals

- <!-- clear, measurable goal -->

## Non-Goals

- <!-- what this plan will NOT do -->

## Tasks

### Phase 1: <!-- phase name -->

- [ ] ⬜ **Task 1.1**: <!-- description -->

## Success Criteria

- [ ] <!-- criterion that must be met -->

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00326-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
```

Two consequences for how you fill it in:

- The scaffold was written by bash inside `mkplan.bash`, not the Write tool, so
  `plan_qa_edit` has never seen it. Your first hand edit is linted as an
  **existing** file (`file_exists_before` is true), which means the
  `template-metadata` check — new-file-only — will not fire. Every other
  edit-time check does.
- `BRAINSTORM.md` already exists in the folder, so `plan-doc-size`'s
  "this plan folder has no supporting documents" hint will not be appended to
  any size finding. Push depth there rather than into `PLAN.md`.

---

## 1. `CLAUDE/Plan/mkplan.bash`

**File:** `/workspace/CLAUDE/Plan/mkplan.bash` (daemon-owned; do not edit)

```bash
CLAUDE/Plan/mkplan.bash "descriptive-kebab-name"
```

**What it does:** validates/normalises the name (must start with a letter,
`[A-Za-z0-9-]`, \<=80 chars, no number prefix); takes an atomic `mkdir` lock on
the plan dir; reads the git counter `hooksdaemon.latestPlanNumber`; refuses if
the filesystem high-water mark exceeds the counter or the number collides;
creates `CLAUDE/Plan/NNNNN-name/`; renders `PLAN.md` from
`/workspace/CLAUDE/Plan/_TEMPLATE_.md` (substituting `{{PLAN_NUMBER}}`,
`{{PLAN_TITLE}}`, `{{CREATED_DATE}}`, `{{OWNER}}` — owner from
`git config user.name`); creates `JOURNAL/NNNNN-Journal-YY-MM-DD.md` from
`_JOURNAL_TEMPLATE_.md` (gated on that template existing — it does here);
advances the counter.

Title comes from the slug with hyphens -> spaces, hence the lowercase
`# Plan 00326: remote docs vendoring and staleness`, matching 00317/00322/00324.

**What it prints:** the creation report on **stderr**, and the absolute target
folder path on **stdout** (so `dir=$(CLAUDE/Plan/mkplan.bash "…")` works).

**What the author must still do by hand:**

- Fill in `PLAN.md`.
- **Add the README index row** in `/workspace/CLAUDE/Plan/README.md` under
  `## Active Plans` — the script does not, and the commit gate's
  `index-at-birth` check expects it in the same commit as the new folder.
- (Suggested) run the `hooks-daemon-plan-dedupe-scout` agent before investing.

**Real Active-Plans row, copied verbatim** from
`/workspace/CLAUDE/Plan/README.md:7`:

```markdown
- [00319: supervisor release review followups](00319-supervisor-release-review-followups/PLAN.md) - Not Started (the ten non-blocking findings surviving the v3.60.0 code-review gate, grouped into silent failures, unbounded per-session growth, and writer/reader contract drift; the three BLOCKING siblings shipped in 55dd5b2e)
```

Shape: `- [NNNNN: title words](NNNNN-folder/PLAN.md) - <Status> (one parenthesised clause)`. Rows are separated by blank lines. Newest-highest number
goes at the top of `## Active Plans`; the file also carries topic sub-headings
(`### Core / Hook Coverage`, `### Plan Workflow / QA`, …) — the ungrouped rows
sit directly under `## Active Plans` before the first `###`. Completed rows (for
later) look like `README.md:175`, with `Completed/` in the link path and often
`- Complete at <hash>`.

---

## 2. Plan QA checklist

Package: `/workspace/src/claude_code_hooks_daemon/plan_qa/`; checks in `checks/`
(one module per check, `CHECK_ID` at the top). Policy:
`/workspace/.claude/hooks-daemon.yaml` lines 964-1001 — `edit_mode: block`,
`commit_gate_mode: warn`, `sweep_mode: advise`, `require_terminal_date: false`,
`journal.mode: advise`, `journal.grandfather_before: 163`,
`journal.today_only_mode` left at its `block` default.

Three surfaces: **EDIT** (`plan_qa_edit`, PreToolUse on Write/Edit), **COMMIT**
(`plan_qa_commit_gate`, PreToolUse on `git commit`, staged tree), **SWEEP**
(`plan_qa_sweep`, SessionStart).

### Checks that fire on a PLAN.md Write/Edit (the ones that can block you)

| check_id                                             | Level                              | Demands                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status-line-present`                                | BLOCK                              | A parseable `**Status**:` line must exist.                                                                                                                                                                                                                                                                                    |
| `status-enum-and-date`                               | BLOCK                              | Status in `Not Started, In Progress, Complete, Blocked, Cancelled, Superseded, Dormant`. Terminal-date qualifier **not** required here (`require_terminal_date: false`).                                                                                                                                                      |
| `header-body-coherence`                              | BLOCK                              | Header `Not Started`/`In Progress` must not coexist with an all-ticked body or prose completion claims.                                                                                                                                                                                                                       |
| `task-grammar`                                       | BLOCK on new material, else ADVISE | No ad-hoc markers (tick-in-brackets, tilde, hourglass). Use `- [ ] ⬜ **Task N.N**: …` / `- [x] ✅ …`.                                                                                                                                                                                                                        |
| `plan-doc-size`                                      | tiered                             | Trips on **bytes OR lines**: advisory above 18,000 bytes / 350 lines; warning above 25,000 / 500; **BLOCK above 35,000 / 900**. Only a *growing* edit can block; shrinking is silent, same-size only advises. Escape hatch: `<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->` (a bare marker with no reason does not count). |
| `template-metadata`                                  | ADVISE, **new files only**         | `**Created**`, `**Owner**`, `**Priority**` present. Will not fire on 00326 — see section 0.                                                                                                                                                                                                                                   |
| `path-existence`                                     | ADVISE                             | Backticked `src/…`, `tests/…` paths in inline code must exist. **Exempt when status is `Not Started`, `Blocked` or `Dormant`** — so 00326 naming files it intends to create is fine while it stays Not Started.                                                                                                               |
| `terminal-placement-hint`                            | ADVISE                             | Terminal status while the folder is still in the active root.                                                                                                                                                                                                                                                                 |
| `archive-immutability`                               | ADVISE                             | Do not edit an archived `PLAN.md`.                                                                                                                                                                                                                                                                                            |
| `plan-time-estimate` (separate handler, not plan_qa) | **DENY**                           | See below.                                                                                                                                                                                                                                                                                                                    |

### On `CLAUDE/Plan/README.md` edits

| check_id           | Level                     | Demands                                                                                                                                                 |
| ------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `index-row-length` | BLOCK (EDIT/COMMIT/SWEEP) | **Every line** \<= 500 chars (`DEFAULT_INDEX_ROW_MAX_CHARS`), not just parsed rows. Worsening-edit-only at EDIT. A row is a link + status + one clause. |
| `index-no-log`     | ADVISE                    | No ledger grammar: a bullet whose bold lead-in is `Before that`, `Prior to that`, `Previously`, or a bold ISO date.                                     |

### Journal checks

| check_id                                       | Stage                      | Demands                                                                                   |
| ---------------------------------------------- | -------------------------- | ----------------------------------------------------------------------------------------- |
| `journal-dayfile-naming`                       | EDIT + SWEEP, ADVISE       | `NNNNN-Journal-YY-MM-DD.md` inside `JOURNAL/`.                                            |
| `journal-dayfile-is-today`                     | EDIT, **block by default** | You may only write today's day-file. Editing a stale-dated one is denied.                 |
| `journal-append-only`                          | EDIT, ADVISE               | Never edit/remove an earlier entry; corrections are new entries at the bottom.            |
| `journal-folder-present` / `journal-freshness` | SWEEP, ADVISE              | Active plan has a `JOURNAL/`; it has not gone quiet (`freshness_days: 3`).                |
| `journal-entry-with-progress`                  | COMMIT                     | A commit changing PLAN.md task counts must stage a journal entry under that folder.       |
| `journal-completion-entry`                     | COMMIT                     | A terminal flip must stage a closing journal entry (`enforce_on_completion: false` here). |

### Commit-gate checks (currently `warn`, but they are the contract)

- `index-at-birth` — a commit creating a new plan folder **must stage the README
  row in the same commit**.
- `counter-sanity` — new plan number must not exceed the git counter.
- `no-new-collisions` — BLOCK; number claimed by two folders
  (`collision_allowlist: [34, 39, 41]`).
- `row-folder-bijection` — every folder has a row, every row a folder, in the
  right section, link resolves.
- `stats-recount` — `## Plan Statistics` totals must match the tree.
- `terminal-state-atomic` / `archived-status-coherence` /
  `location-status-coherence` — a terminal flip ships `git mv` into `Completed/`
  - README row + stats in ONE commit, and the *staged* blob must carry the
    terminal status.
- `structure-archive-dirs` — BLOCK; plan dir has `README.md` and `Completed/`;
  **no stray files at the plan root**; no plan folder outside root/archive.
- `plan-ref-format` — ADVISE; a commit touching `CLAUDE/Plan/` must contain a
  `Plan \d{5}` reference. Message format: `Plan 00326: <description>`.
- `same-commit-plan-doc` — a commit message citing a plan number alongside code
  must stage that plan's doc.
- `plan-shrink-without-journal` — shrinking PLAN.md without staging a journal
  entry or a new supporting doc.

### No time estimates — `R-PLAN-TIME-ESTIMATE`

Handler
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_time_estimates.py`.
Fires on Write/Edit to any path containing `/Plan/` ending `.md`, **except
anything under `JOURNAL/`**. Returns `Decision.DENY`.

**This file proved it the hard way**: an earlier draft of this report was
DENIED, because `subagent-reports/` sits inside the plan folder and the draft
quoted the blocked patterns literally. The shapes below are therefore described
rather than reproduced — read the `ESTIMATE_PATTERNS` list in the handler for
the exact regexes.

Blocked shapes, matched **per line**:

- An `Estimated Effort` / `Estimated time` / `Total Estimated Time` header line
  (bold or plain) whose value names a unit of hours, minutes, days or weeks.
- A `Target Completion` or `Completion` line carrying an ISO calendar date.
- A verb from take / takes / require / requires / need / needs / approximately /
  about, followed by a number (single or hyphenated range) and a unit of hours,
  minutes, days, weeks or months.
- A `Phase N` heading whose text carries a parenthesised number-plus-unit
  duration.
- A `Total` / `Overall` / `Combined` line whose value is a number plus a unit.
- A number plus unit immediately followed by work / implementation /
  development / effort / time.
- An `ETA` / `timeline` / `deadline` / `due date` label followed by a digit.

Exemption is **line-scoped**: a line containing `TTL`, `cache`, `timeout`,
`retention`, `window`, `expiry`, `session`, `rate limit`, `API`, `period`,
`trial`, `rolling`, `usage`, `policy` or `tracking` is spared. This matters for
00326 specifically — a *staleness* plan legitimately discusses refresh windows
and cache TTLs, and those words are on the exemption list, so a sentence about a
staleness window survives while a sentence estimating how long the work will
take does not. Practical rule: never put a work duration or a target date in
`PLAN.md` or any plan-folder file outside `JOURNAL/`.

**Verify before committing:**
`bin/hooks-daemon plan-qa --lint CLAUDE/Plan/00326-remote-docs-vendoring-and-staleness/PLAN.md`
(add `--json`), then `--check-staged` and `--sweep`.

---

## 3. Exemplary PLAN.md structure

### `/workspace/CLAUDE/Plan/Completed/00322-post-upgrade-optimise-deferral-and-client-noise/PLAN.md` (155 lines)

```
# Plan 00322: post upgrade optimise deferral and client noise

**Status**: Complete
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview
## Goals
## Non-Goals
## Tasks
### Phase 1: Post-upgrade banner stops deferring
### Phase 2: `contract_staleness` becomes install-mode aware
### Phase 3: Ship phases 1-2
### Phase 4: `optimise` stops squatting a generic top-level name
## Success Criteria
## Delivery & Milestones
```

### `/workspace/CLAUDE/Plan/Completed/00317-supervisor-host-thin-shim/PLAN.md` (105 lines)

Identical skeleton;
`**Execution Strategy**: Single python-developer agent, TDD; audit first`
(the field is free prose, not an enum). Phases named lowercase:
`### Phase 1: audit`, `### Phase 2: refactor`, `### Phase 3: verification`.

### `/workspace/CLAUDE/Plan/Completed/00324-skill-invoke-scripts-never-referenced/PLAN.md` (77 lines)

Same skeleton; phases `### Phase 1: Lock the contract`,
`### Phase 2: Reference the scripts`, `### Phase 3: Ship`.

**House style observed across all three recent plans:**

- Header block is six `**Key**: value` lines, no blank lines between them.
- `## Overview` is 2-4 prose paragraphs stating the defect and its cause,
  hard-wrapped near 72 columns. It names the evidence (a field report, a prior
  plan, a measurement) rather than asserting.
- `## Goals` — outcome bullets ("X does Y"), not tasks. `## Non-Goals` —
  explicit exclusions, often with the reason.
- Tasks: `- [ ] ⬜ **Task N.N**: <imperative>` (one task per phase is normal;
  sub-bullets optional). Completed form `- [x] ✅ **Task N.N**: …`. Tasks name
  concrete file paths in backticks and say "RED first" where TDD applies. Phases
  routinely end with a ship phase: *"QA, daemon restart + verification,
  CHANGELOG entry, commit and push."*
- `## Success Criteria` — `- [ ]` checkboxes with **no** status icon (icons are
  for Tasks only).
- `## Delivery & Milestones` — retains the HTML comment from the template, then
  `` - `hash` — what shipped `` bullets. Never a date.
- Optional sections used when warranted (00272): `## Context & Background`,
  `## Dependencies`, `## Technical Decisions` (with `### Decision N: Title` /
  `**Context**:` / `**Options Considered**:` / `**Decision**:` / a `**Date**:`
  line), `## Risks & Mitigations` (table). A `**Date**:` inside a Decision block
  is fine — the time-estimate handler keys on completion/target labels, not on
  every date.

### Supporting docs

Plan 00272's folder
(`/workspace/CLAUDE/Plan/Completed/00272-secret-file-read-blocker/`) holds
`PLAN.md` (580 lines), `BRAINSTORM.md` (305), `RESEARCH-read-routes.md`,
`REVIEW-2026-08-26-draft-plan.md`, `JOURNAL/`. Naming is `SCREAMING-kebab` with
an optional topic suffix.

`BRAINSTORM.md` opens with a one-line statement of its relationship to PLAN.md
("Deep analysis supporting `PLAN.md`. This document is the durable record of the
threat model, honest limits, and design decisions' reasoning."), then free-form
`##` sections:

```
# Brainstorm — Secret File Read Blocker (Plan 00272)

## Problem statement
## Threat model — every route content can enter context
### Existence testing
### The trusted-consumer problem
## Honest limits — what a PreToolUse deny CANNOT guarantee
## The metadata helper
### Does hashing leak?
### Size, key hygiene and the extraction-oracle boundary (draft-review finding 5)
## Config shape
## No escape hatch — same reasoning as artifact_publish_blocker
## Reverse direction, deletion, scope decisions
## Daemon-owned artefacts — the guard must not worsen the footprint
## OS-level boundary — one shippable piece
## Interaction with existing handlers
## Handler shape
## Acceptance-test note
```

`RESEARCH-read-routes.md` uses `## Purpose`, `## Classification legend`,
`## Route inventory` + `###` per route class,
`## Phase 1 verification checklist (no assumptions)`, and a dated
`## Conclusion (implementation pass, …)`. `REVIEW-….md` uses severity headings:
`## Critical` / `## Important` / `## Minor` / `## What is already right` /
`## Suggested order`.

Plan 00317 also demonstrates `AUDIT.md` and `subagent-reports/` (the latter is a
recognised plan-folder member for plan QA — its presence never triggers a
stray-file finding; filename `{yymmdd}-{agent-name}-{model}.md`).

### The three contracts (`plan_workflow` handler)

Source:
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_workflow.py:79`

|             | `PLAN.md`                                                                  | `SOME-DOC.md`                                                                                      | `JOURNAL/NNNNN-Journal-YY-MM-DD.md`                           |
| ----------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| **Write**   | Commit if dirty, edit in place, commit. Rewrite freely — git holds history | Edit in place, freely                                                                              | **Append only.** Never edit or remove an earlier entry        |
| **Content** | Lean, surgical, current truth only: goals, decisions, task tree, status    | Durable current detail too big for the task list: research, findings, decision reasoning, evidence | What happened: dated progress, findings, incidents, hand-offs |
| **Read**    | In full, every session                                                     | On demand, only when its link is followed                                                          | Never whole — `tail -n N`, grep, or a sub-agent               |
| **Size**    | Bounded (tiers above)                                                      | Unbounded                                                                                          | Unbounded                                                     |

Journal entry grammar (`/workspace/CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`):
`## HH:MM · category · REF — optional short title`, category in
`action|finding|decision|thought|blocker|handoff`, REF like `T1.2`/`P1`/`—`.
End a session with a `handoff` entry.

---

## 4. `R-MARKDOWN-WRONG-LOCATION`

Handler:
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`,
`_check_builtin_paths()` at line 1105. **Write/Edit tool only — no Bash
detection** for the location rule.

Allowed (built-in), checked in order:

1. `src/claude_code_hooks_daemon/guides/**.md`
2. `src/claude_code_hooks_daemon/skills/**.md`
3. **Plan dir** `CLAUDE/Plan/…` — the first segment must be `NNN…-` (>=3 digits)
   or an archive dir (`Completed`, `Cancelled`, `archive`) whose *second*
   segment is; files directly at the plan root are allowed by this handler (but
   `structure-archive-dirs` flags strays).
4. **Anything under `CLAUDE/`**
5. **Anything under `docs/`**
6. `untracked/`, `RELEASES/`, `eslint-rules/**.md`
7. Anywhere: `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `.claude/skills/**`,
   `.claude/commands/**`, `.claude/rules/**`, `.claude/agents/**`
8. Project **root only**: `CONTRIBUTING.md`, `LICENSE.md`, `SECURITY.md`,
   `CODE_OF_CONDUCT.md`, `AUTHORS.md`, `NOTICE.md`, `MAINTAINERS.md`
9. Project extras (this repo, `/workspace/.claude/hooks-daemon.yaml:538`):
   `^\.github/.*\.md$`, `^BUG_REPORTING\.md$`, plus daemon template assets.

**Verdict for `docs/remote/`: NOT blocked.** Step 5 is a plain prefix test on
`docs/` with no allowlist beneath it, so `docs/remote/anything.md` — and any
other new subdirectory of `docs/` — is allowed with no config change. Only a
genuinely *new top-level* directory (e.g. `remote/guide.md`,
`design-notes/x.md`) would be denied.

Two riders that are not `markdown_organization` but do apply to a new `docs/`
subtree: the human-tree register rule (terse, summarising, pointing into
`CLAUDE/` for depth — `/workspace/CLAUDE/DirectoryRoles.md:66` and
`/workspace/.claude/rules/human-docs.md`), and the `docs_qa` catalogue
(edit-time, commit gate, session sweep) which applies in full to anything under
`docs/`.

To add a location that genuinely is outside the allowlist:
`handlers.pre_tool_use.markdown_organization.options.extra_allowed_markdown_paths`
— a list of **regexes** matched with `re.match(..., re.IGNORECASE)` against the
project-relative path, **additive** on top of the built-ins (a blocked path is
rescued if any pattern matches). It is `re.match`, i.e. anchored at the start;
existing entries anchor explicitly with `^…$`. The legacy
`allowed_markdown_paths` **replaces** all built-ins — do not use it.

---

## 5. `docs/` layout

Routing SSoT is `/workspace/docs/CLAUDE.md`:

| Topic                                 | Canonical file                     |
| ------------------------------------- | ---------------------------------- |
| Per-handler options, values, defaults | `docs/guides/HANDLER_REFERENCE.md` |
| Configuration format & structure      | `docs/guides/CONFIGURATION.md`     |
| Installation & first-use              | `docs/guides/GETTING_STARTED.md`   |
| Troubleshooting                       | `docs/guides/TROUBLESHOOTING.md`   |
| QA suite (human overview)             | `docs/QA.md`                       |
| Plan system (human overview)          | `docs/PLAN_SYSTEM.md`              |

**`docs/` root** holds subsystem overview pages (`PLAN_SYSTEM.md`, `QA.md`,
`CONFIG-VALIDATION.md`) — short, human-register, pointing into `CLAUDE/` for
depth (`/workspace/docs/PLAN_SYSTEM.md` is 80 lines and opens by naming
`CLAUDE/PlanWorkflow.md` as canonical). **`docs/guides/`** holds task-oriented
reference guides (`AGENT_ASSETS.md`, `CREATING_REPORTS.md`,
`HOOK-CONTRACT-REFRESH.md`, `VERDICT_LOG.md`, …), and **`docs/guides/handlers/`**
holds per-handler deep docs linked from `HANDLER_REFERENCE.md`.

### HANDLER_REFERENCE.md entry template

Verbatim, `/workspace/docs/guides/HANDLER_REFERENCE.md:2376-2411`. Entries are
`####` under an `###` band (`### Workflow Handlers (Priority 30-55)`), separated
by `---`:

````markdown
#### markdown_organization

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `markdown_organization` |
| **Priority**   | 35                      |
| **Type**       | Blocking                |
| **Event**      | PreToolUse              |

**Full documentation:** [`docs/guides/handlers/markdown_organization.md`](handlers/markdown_organization.md)

Enforces markdown file organization rules, plan tracking, allowed paths, and monorepo support. To allow extra locations, prefer the additive `extra_allowed_markdown_paths` option over the legacy `allowed_markdown_paths` full override. See per-handler docs for all options, monorepo interaction, and examples.

**Key options** (the full set is in the per-handler doc linked above):

| Option                          | Type        | Default | Description                                                                                                    |
| ------------------------------- | ----------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `extra_allowed_markdown_paths`  | `list[str]` | `[]`    | Additive allowlist of extra locations where markdown may be written. Prefer this over the legacy full override. |

The default of `false` is deliberate: durable knowledge belongs in tracked project docs …

```yaml
handlers:
  pre_tool_use:
    markdown_organization:
      enabled: true
      priority: 35
      options:
        allow_untracked_claude_memory: false
        extra_allowed_markdown_paths:
          - "design-notes/**"
```

---
````

A simpler variant (`#### validate_instruction_content`, line 2417) drops the
options table and uses `**Description:**` + `**Config example:**`. Two
constraints on this file: the **Priority** number must match
`src/claude_code_hooks_daemon/constants/priority.py` and the handler must exist
— `scripts/qa/check_handler_reference.py` fails QA otherwise. Tables are
auto-aligned by the `markdown_table_formatter` handler.

---

## Gotchas worth knowing before you write

- Write `PLAN.md` and supporting docs with **Write/Edit**, not heredocs — the
  content guards (and the plan QA lint) only see tool writes, and
  `pipe_blocker`/`sed_blocker` judge Bash commands regardless of destination.
- Stage the README row **in the same commit** as the plan folder, and put
  `Plan 00326:` in the commit message.
- Keep `PLAN.md` under 350 lines / 18,000 bytes to stay clear of even the
  advisory tier; push depth into the folder's existing `BRAINSTORM.md` or a new
  `RESEARCH-*.md` beside it.
