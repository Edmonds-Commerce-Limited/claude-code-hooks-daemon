# Plan 00144: Plan QA System — Real-Time Plan Validation & Drift Enforcement

**Status**: In Progress
**Created**: 2026-07-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Planning is fundamental to how every daemon-managed project works, and the plan
tree rots silently: status headers never flipped, folders never indexed, plans
finished but marked `Not Started`, number collisions, completed work loitering
in the active root. A 2026-07-07 audit of a large client project (spec:
`untracked/hooks-daemon-plan-verify-qa.md`) catalogued **31 distinct evidenced
sins** — 54 plan folders vs 41 indexed, 13 folders absent from the index, a
live production bug rendered invisible because its plan was unindexed.

This plan builds a first-class **plan QA subsystem** into the daemon: a pure,
unit-testable `plan_qa` core (parsers + check registry) consumed by three
enforcement surfaces — an edit-time PreToolUse handler, a commit-time gate on
`git commit`, and a whole-tree sweep (SessionStart advisory + `plan-qa` CLI
subcommand usable in CI). It also enforces the structural preconditions the
lifecycle depends on: the plan directory must contain the archive
subdirectories (`Completed/`, optionally `Cancelled/`) and a `README.md` index.

Key insight from the sin catalogue: **most rot is cross-file** (PLAN.md ↔
folder location ↔ README row ↔ git state). A single Write/Edit hook cannot see
the whole invariant, so enforcement needs three stages with different powers,
sharing one core.

## Goals

- One pure-Python `plan_qa` core package (no daemon coupling) that parses the
  plan tree, PLAN.md documents, and the README index, and evaluates a
  registered catalogue of checks — every check has an id, stage, and level.
- Stage 1: edit-time feedback — block malformed **new** plan material at
  Write/Edit time (missing/invalid `**Status**:`, header contradicting an
  all-ticked body); advise on legacy material.
- Stage 2: commit gate — cross-file invariants over the **staged** tree
  (index-at-birth, no number collisions, terminal-status flips must be atomic
  with the `git mv` + README update). Ships in `warn` mode, flips to `block`
  via config.
- Stage 3: sweep — full-tree drift report at SessionStart (rate-limited
  advisory) and via `$PYTHON -m ...daemon.cli plan-qa --sweep` (exit 1 on
  drift, CI-able).
- Structural enforcement: plan dir must contain the configured archive dirs
  (`Completed/`, `Cancelled/` where enabled) and `README.md`; terminal-status
  plans must live in the matching archive dir.
- Dogfooded in this repo, with this repo's own plan-tree drift fixed.
- 95%+ coverage, acceptance tests via `get_acceptance_tests()`, accurate
  `get_claude_md()` guidance on every new handler.

## Non-Goals

- Semantic truth of prose (sins A7/B4/B6/B8 — "row understates progress") —
  not mechanically checkable; mitigated by keeping status in PLAN.md and rows
  short.
- SPEC-vs-code drift (sins F1/F2) — belongs to a client project's own
  defence-before-fix tests, not plan QA.
- Cross-repo claims verification.
- Rewriting `PlanWorkflow.md` conventions — QA enforces the existing template
  grammar, it does not invent a new one.
- Auto-fixing violations (no rewriting of plan files by the daemon beyond the
  existing markdown_table_formatter behaviour). QA reports and blocks;
  the agent remediates.

## Context & Background

- Full sin catalogue, check-by-check mapping, and coverage matrix:
  `untracked/hooks-daemon-plan-verify-qa.md` (Parts 1–3). Check ids in this
  plan reference that catalogue.
- Existing daemon machinery this builds on (must not duplicate):
  - `PlanWorkflowConfig` (`config/models.py:381`) — `enabled`, `directory`,
    `workflow_docs`; the registry injects `plan_dir` into every handler tagged
    `HandlerTag.PLANNING` (`handlers/registry.py:334-350`).
  - `handlers/utils/plan_numbering.py` — authoritative plan-number counter
    logic shared with `plan_number_helper` / `validate_plan_number` /
    `mkplan.bash`.
  - Existing plan handlers: `plan_number_helper` (33), `validate_plan_number`
    (41), `plan_time_estimates` (45), `plan_workflow` (46),
    `plan_completion_advisor` (48), `recovery_cron_advisor` (PostToolUse 30),
    `markdown_organization` (50).
  - `markdown_table_formatter` (PostToolUse 26) rewrites every `.md` we write —
    all plan_qa parsers MUST tolerate mdformat-gfm output.
  - CLI `cmd_*` subcommand pattern in `daemon/cli.py` (exemplars:
    `format-markdown`, `generate-docs`, `harvest-background`).

## Technical Decisions

### Decision 1: Built-in daemon feature, not project handlers

**Context**: The originating spec (written from the client repo's perspective)
suggested `.claude/project-handlers/`.
**Decision**: Build as **built-in handlers + core package** in
`src/claude_code_hooks_daemon/`. The plan workflow is already a first-class
daemon domain (five built-in plan handlers, `PlanWorkflowConfig`, `mkplan.bash`
distribution); building it in gives every install the feature, full QA/typing/
coverage machinery, acceptance-test integration, and dogfooding here.

### Decision 2: One pure core, three thin consumers

**Context**: Three enforcement surfaces need the same parsing and rules.
**Decision**: New package `src/claude_code_hooks_daemon/plan_qa/`:

```
plan_qa/
  model.py        # PlanTree (scan root + archive dirs), PlanDoc (parse a PLAN.md)
  readme_index.py # ReadmeIndex: sections, rows, stats table
  gitfacts.py     # staged-diff inspection, counter read, folder last-commit dates
  checks/         # one module per check; registry entries: (id, stage, level, sins)
  report.py       # findings -> block reason / advisory text / CLI report
  runner.py       # run(stage, context) -> [Finding]
```

Handlers and the CLI contain zero rule logic — they build a context (file
content being written / staged tree / HEAD tree) and render findings. Checks
are registered declaratively so the catalogue is greppable and the docs
(`get_claude_md`, HANDLER_REFERENCE) can be generated from it.

### Decision 3: Configuration lives in `PlanWorkflowConfig.qa`

**Context**: Checks span three handlers plus the CLI; per-handler `options`
dicts would fragment a single policy.
**Decision**: Extend the typed `PlanWorkflowConfig` with a nested `qa` model
(pydantic, `extra="forbid"`):

```yaml
plan_workflow:
  enabled: true
  directory: CLAUDE/Plan
  qa:
    enabled: true
    completed_dir: Completed        # archive dir name (some projects use Done)
    cancelled_dir: Cancelled        # optional; null = cancelled plans go to completed_dir
    edit_mode: block                # block | warn | off   (Stage 1, new material only)
    commit_gate_mode: warn          # block | warn | off   (Stage 2 — ships as warn)
    sweep_mode: advise              # advise | off          (Stage 3 SessionStart)
    staleness_days: 30              # Stage 3 staleness nag threshold
    legacy_plan_allowlist: []       # plan numbers held to advise-only
    collision_allowlist: []         # historic number collisions to tolerate
```

The registry already injects plan config into `PLANNING`-tagged handlers; the
`qa` sub-model rides the same injection. Per-handler `options` remain empty.

### Decision 4: Ratcheted enforcement rollout

**Context**: The commit gate has the highest value and the highest blast
radius; blocking commits on day one with unproven parsers would be reckless.
**Decision**: Build order = core → sweep+CLI (zero blocking risk, validates
parsers against real trees) → edit-time handler (block for new material only)
→ commit gate (default `warn`; flip this repo's config to `block` after a
clean dogfooding period; client projects opt in via config). Legacy plans get
`advise` not `block` (allowlist and/or missing-`Created:`-header heuristic).
Quality ratchets one way.

### Decision 5: Sweep surfaces are SessionStart + CLI; Stop-time sweep deferred

**Context**: The spec proposed SessionStart + Stop + CLI. v3.31.0/v3.31.1 just
shipped urgent fixes for a Stop/SubagentStop advisory-context infinite loop.
**Decision**: Ship SessionStart advisory (rate-limited, compact) + `plan-qa`
CLI now. A Stop-time sweep adds marginal coverage and non-trivial regression
risk to the most sensitive event in the daemon; defer it to a follow-up plan
if session-boundary coverage proves insufficient.

### Decision 6: Structural preconditions are themselves checks

**Context**: The lifecycle (and several checks) presuppose
`{plan_dir}/Completed/` etc. exist; the user explicitly wants directory
enforcement.
**Decision**: A `structure-archive-dirs` check (Stage 3 advise; Stage 2 block
when a terminal flip is staged and the target dir is missing) verifies the
configured archive dirs and `README.md` exist, and that no plan folder sits
outside root/archive locations. Remediation text tells the agent exactly what
to create/move.

### Decision 7: mkplan template externalised to a tracked `_TEMPLATE_.md`

**Context**: User side-mission (2026-07-07, approved with plan execution):
projects should manage their own plan template while still receiving hints
from daemon defaults. Today the PLAN.md skeleton is a heredoc hard-coded
inside `mkplan.bash` — projects cannot customise it without forking a
daemon-owned (overwrite-on-upgrade) script.
**Decision**:

- **New bundled asset** `install/templates/_TEMPLATE_.md` — the canonical
  daemon default plan template, containing `{{PLAN_NUMBER}}`,
  `{{PLAN_TITLE}}`, `{{CREATED_DATE}}`, `{{OWNER}}` placeholders.
- **mkplan.bash** reads `{plan_dir}/_TEMPLATE_.md` when present and
  substitutes placeholders via bash parameter expansion (no sed). When
  absent it falls back to the built-in heredoc (script stays drop-in
  self-contained for bare projects).
- **Deploy/upgrade** (`bootstrap_plan_workflow`): `_TEMPLATE_.md` is
  **create-if-missing** (client-owned content, like README/CLAUDE.md —
  never overwritten). A daemon-owned reference snapshot
  `{plan_dir}/.plan-template-default.md` is overwritten on every deploy;
  before overwriting, the old snapshot is diffed against the new bundled
  default and any changes are surfaced in `BootstrapResult.messages` so
  the project can adopt them into its own `_TEMPLATE_.md` if wanted.
- **plan_qa alignment**: the Stage 1 `template-metadata` check derives
  required header fields from the project's `_TEMPLATE_.md` when present,
  falling back to the daemon default. `PlanTree` ignores `_TEMPLATE_.md`,
  the snapshot dotfile, and other non-plan files at the plan root.

## Handler / Surface Specification

| Surface             | Event / entry                       | ID                    | Priority | Behaviour                                                                              |
| ------------------- | ----------------------------------- | --------------------- | -------- | -------------------------------------------------------------------------------------- |
| Stage 1 edit lint   | PreToolUse (Write/Edit on plan dir) | `plan_qa_edit`        | 44       | Terminal block (new material) / advisory (legacy), per `edit_mode`                     |
| Stage 2 commit gate | PreToolUse (Bash `git commit`)      | `plan_qa_commit_gate` | 44       | Block or warn per `commit_gate_mode`; evaluates staged tree via `gitfacts`             |
| Stage 3 sweep       | SessionStart                        | `plan_qa_sweep`       | 57       | Advisory, one compact drift report, rate-limited per session                           |
| CLI                 | `daemon.cli plan-qa`                | —                     | —        | `--sweep` (HEAD tree, exit 1 on findings), `--check-staged`, `--lint <file>`, `--json` |

Check catalogue (ids, stages, levels, sin mapping) is specified in Part 2 of
`untracked/hooks-daemon-plan-verify-qa.md` and will be transcribed into
`plan_qa/checks/` docstrings as the single in-repo source of truth:

- **Stage 1**: `status-line-present`, `status-enum-and-date`,
  `header-body-coherence`, `template-metadata`, `task-grammar`,
  `terminal-placement-hint`, `archive-immutability`, `path-existence`.
- **Stage 2**: `index-at-birth`, `no-new-collisions`, `counter-sanity`,
  `terminal-state-atomic`, `same-commit-plan-doc`, `row-folder-bijection`,
  `stats-recount`, `plan-ref-format`, `structure-archive-dirs`.
- **Stage 3**: `full-tree-consistency` (entire Stage 2 set vs HEAD),
  `staleness-nag`, `dormant-honesty`, `structure-archive-dirs`.

Feedback UX: every block/advisory names the check id, the violated invariant,
and the **exact remediation** ("this commit must also contain: `git mv …`;
README row for 00144; stats 41→42") — same self-correction pattern as
`plan_number_helper`.

## Tasks

### Phase 1: `plan_qa` core (parsers + checks + runner)

- [ ] ⬜ **Task 1.1**: TDD `model.py` — `PlanDoc` parser (status line + enum +
  terminal-date, task/checkbox/icon counts incl. legacy grammars, done-marker
  detection, template metadata) against fixtures **round-tripped through
  mdformat-gfm** (markdown_table_formatter compatibility)
- [ ] ⬜ **Task 1.2**: TDD `model.py` — `PlanTree` scanner (root + configured
  archive dirs, number extraction, collision detection, misplaced-folder
  detection, structure checks)
- [ ] ⬜ **Task 1.3**: TDD `readme_index.py` — sections, rows (number, link
  target, status text), stats table
- [ ] ⬜ **Task 1.4**: TDD `gitfacts.py` — staged file list/diff, staged-tree
  file reads, counter read (reuse `handlers/utils/plan_numbering.py`), folder
  last-commit dates
- [ ] ⬜ **Task 1.5**: TDD check registry + `runner.py` + `report.py`;
  implement the full check catalogue, each check its own module + test file
- [ ] ⬜ **Task 1.6**: Extend `PlanWorkflowConfig` with the `qa` sub-model +
  registry injection + config schema tests
- [ ] ⬜ **Task 1.7**: QA suite green; checkpoint commit

### Phase 2: Stage 3 — sweep CLI + SessionStart advisory

- [ ] ⬜ **Task 2.1**: TDD `plan-qa` CLI subcommand (`--sweep`,
  `--check-staged`, `--lint <file>`, `--json`; exit 1 on findings)
- [ ] ⬜ **Task 2.2**: Run `plan-qa --sweep` against THIS repo's plan tree;
  triage findings (known candidates: stray `idempotent-chasing-wadler.md` at
  plan root, legacy 3-digit `002-`/`003-` folders in Completed/, any index
  drift); fix real drift, allowlist grandfathered legacy
- [ ] ⬜ **Task 2.3**: TDD `plan_qa_sweep` SessionStart handler (advisory,
  rate-limited, compact report; `get_claude_md`, `get_acceptance_tests`)
- [ ] ⬜ **Task 2.4**: Register handler (constants, default config,
  dogfooding config), daemon restart verification, QA, checkpoint commit

### Phase 3: Stage 1 — edit-time handler

- [ ] ⬜ **Task 3.1**: Capture real Write/Edit event flow on plan files with
  `./scripts/debug_hooks.sh` (confirm tool_input shapes for Write vs Edit vs
  new-file-vs-existing)
- [ ] ⬜ **Task 3.2**: TDD `plan_qa_edit` PreToolUse handler — Stage 1 checks
  on the would-be file content (for Edit: apply old/new to current content);
  block new material, advise legacy, honour `edit_mode`
- [ ] ⬜ **Task 3.3**: `get_claude_md()` guidance + acceptance tests;
  register, restart daemon, live-test against real plan edits in this repo
- [ ] ⬜ **Task 3.4**: QA green; checkpoint commit

### Phase 4: Stage 2 — commit gate (land last, warn-first)

- [ ] ⬜ **Task 4.1**: TDD `plan_qa_commit_gate` PreToolUse handler — matches
  Bash `git commit` when staged tree touches plan dir or message references
  `[Pp]lan \d{5}`; runs Stage 2 checks via `gitfacts`; `warn` renders
  advisory context, `block` denies with the diffable TODO list
- [ ] ⬜ **Task 4.2**: Guard rails: never fire on `git commit` inside
  worktrees other than the project root's repo; bounded runtime on huge
  staged diffs; graceful no-op when plan_workflow disabled
- [ ] ⬜ **Task 4.3**: `get_claude_md()` + acceptance tests; register with
  `commit_gate_mode: warn` in this repo; restart daemon; QA; checkpoint commit
- [ ] ⬜ **Task 4.4**: Dogfood in warn mode across real commits; when clean,
  flip THIS repo's config to `block` (separate commit)

### Phase 5: mkplan template externalisation (`_TEMPLATE_.md`)

- [ ] ⬜ **Task 5.1**: TDD bundled default template — add
  `install/templates/_TEMPLATE_.md` with `{{PLAN_NUMBER}}` /
  `{{PLAN_TITLE}}` / `{{CREATED_DATE}}` / `{{OWNER}}` placeholders;
  content matches the current mkplan heredoc skeleton
- [ ] ⬜ **Task 5.2**: Update `install/templates/mkplan.bash` — use
  `{plan_dir}/_TEMPLATE_.md` with bash parameter-expansion substitution
  when present; keep the heredoc as fallback; cover both paths in
  `tests/unit/install/` (script invoked against fixture plan dirs)
- [ ] ⬜ **Task 5.3**: TDD `bootstrap_plan_workflow` changes —
  create-if-missing `_TEMPLATE_.md`, always-overwrite
  `.plan-template-default.md` snapshot, diff old snapshot vs new default
  and surface changes in `BootstrapResult.messages`
- [ ] ⬜ **Task 5.4**: Align plan_qa `template-metadata` check + `PlanTree`
  scanner with project templates (read `_TEMPLATE_.md` when present;
  ignore template/snapshot files as non-plans)
- [ ] ⬜ **Task 5.5**: Deploy to THIS repo (run the bootstrap, commit
  `CLAUDE/Plan/_TEMPLATE_.md`), verify mkplan uses it; QA; checkpoint
  commit

### Phase 6: Docs, dogfooding hardening, release prep

- [ ] ⬜ **Task 6.1**: Update `docs/guides/HANDLER_REFERENCE.md`,
  `CLAUDE/PlanWorkflow.md` (QA section), regenerate `.claude/HOOKS-DAEMON.md`
- [ ] ⬜ **Task 6.2**: Stage `UNRELEASED/config-changes/` manifest
  (`plan_workflow.qa` added, `recommended: true`) and
  `UNRELEASED/truth-changes/` entries (plan template now sourced from
  `_TEMPLATE_.md`; any other documented workflow statement that changed)
- [ ] ⬜ **Task 6.3**: Full acceptance playbook run for the three new
  handlers; full QA; final checkpoint commit

## Dependencies

- Depends on: existing `plan_numbering` utilities, `PlanWorkflowConfig`
  injection (both shipped)
- Blocks: future "plan QA in CI" wiring for client projects; potential
  Stop-time sweep follow-up plan
- Related: Plan 00130 (mkplan.bash distribution), Plan 00138
  (plan_number_helper false positives)

## Success Criteria

- [ ] `plan_qa` core passes unit tests with 95%+ coverage; parsers proven
  against mdformat-round-tripped fixtures and this repo's real plan tree
- [ ] `plan-qa --sweep` runs clean on this repo (real drift fixed, legacy
  grandfathered explicitly)
- [ ] All three handlers registered, daemon restart verified RUNNING,
  acceptance tests pass in a live session
- [ ] Editing a new PLAN.md without a valid `**Status**:` line is blocked
  with actionable remediation; a terminal-status flip without the matching
  `git mv` + README update is caught at commit time (warn mode)
- [ ] Missing `{plan_dir}/Completed/` (or configured archive dirs) is
  reported by the sweep with exact remediation
- [ ] Full QA suite passes; `./scripts/qa/run_all.sh` green
- [ ] Handler docs (`get_claude_md`) accurate per the Step 11 release audit
  standard

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                                             |
| ----------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------ |
| Commit gate false positives block legitimate commits        | High   | Medium      | Ship `warn` first; flip to `block` only after clean dogfooding; `off` escape in config                 |
| Parsers break on mdformat output or unusual-but-valid plans | Medium | Medium      | Fixtures round-trip through the formatter; sweep validated against two real trees before any blocking  |
| Overlap/conflict with existing plan handlers                | Medium | Low         | Explicit non-duplication review vs plan_number_helper / validate_plan_number / plan_completion_advisor |
| Commit-gate latency on large staged diffs                   | Low    | Low         | `gitfacts` reads only plan-dir paths + README from the index; bounded file count                       |
| Legacy plan noise makes advisories ignorable                | Medium | Medium      | Grandfather allowlist; rate-limited compact sweep report; block-level reserved for new material        |

## Notes & Updates

### 2026-07-07

- Plan scaffolded via mkplan.bash (counter → 144).
- Originating spec: `untracked/hooks-daemon-plan-verify-qa.md` (31-sin
  catalogue from the client-project audit; check catalogue + coverage matrix).
- Failsafe recovery cron created: ID `8b5312b4` (hourly at :23, non-durable).
- Proposal committed (`4019054`) and pushed; **user approved execution**.
- Scope addition (user side-mission, same session): mkplan template
  externalisation to tracked `{plan_dir}/_TEMPLATE_.md` — Decision 7 +
  Phase 5; former docs/release phase renumbered to Phase 6.
- Status flipped to In Progress; Phase 1 (plan_qa core) begun.
