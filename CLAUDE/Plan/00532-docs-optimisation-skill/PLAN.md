# Plan 00532: docs optimisation skill

**Status**: Not Started (rulings recorded in RULINGS-fable.md; Fable rulings
under the owner's delegation, not owner rulings)
**GitHub Issue**: #123
**Created**: 2026-10-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet (Opus for Phase 1, the loading-rules contract)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #123 asks for a daemon-shipped, daemon-maintained skill that restructures
a client project's agent instruction files (root `CLAUDE.md`, `@`-imported
files, `.claude/rules/`, nested `CLAUDE.md`) for one canonical home per fact
and progressive disclosure. Its rules should track how the installed Claude
Code version loads those files, and it should be flagged for re-audit when
that loading behaviour changes.

What exists today is the audit half, not the restructure half. The
`documentation` subsystem (Plan 00284) ships the SSoT ruleset as
`CLAUDE/core/DocumentationStrategy.core.md` and deterministic checks under
`src/claude_code_hooks_daemon/docs_qa/checks/` (`at_import_census` for R6,
`module_doc_budget` for R7d, `duplicate_block`, `rules_file_shape` for R7a);
the `docs-qa` skill is a shim that dispatches the read-only
`hooks-daemon-docs-qa` agent. Nothing proposes a split, and nothing records
which Claude Code loading behaviour the rules assume. The hooks contract
(`contracts/claude-code-hooks/META.json` with
`last_audited_claude_code_version`, and the `contract_staleness` SessionStart
advisory) is the precedent for that second half.

Two facts found while planning shape the decisions. First, Claude Code now
ships `/doctor prompt-audit` (v2.1.283+: a report with proposed edits, applied
only on request) and a `/doctor` checkup that proposes `CLAUDE.md` trims
(`remote-docs/code.claude.com/docs/en/memory.md`), so part of the ask overlaps
a built-in. Second, the daemon's own ruleset already embeds loading
assumptions that the vendored doc contradicts or does not match. R7a
prescribes a `description` frontmatter field on rules files, but Claude Code
reads only `paths` and ignores any other field. `rules_file_shape` scopes to
files directly inside `.claude/rules/`, while Claude Code discovers rules
recursively. Those are exactly the drift a pinned loading-rules contract would
surface, and they are inputs to Phase 1 whatever the rulings.

## Goals

- A versioned, vendored record of how Claude Code loads instruction files
  (the "loading-rules contract"), audited against a named Claude Code version,
  that the restructure guidance and the docs_qa checks cite instead of
  restating.
- A re-audit signal when the installed Claude Code is newer than that record,
  following the `contract_staleness` precedent.
- A client-facing restructure capability (shape per QUESTIONS.md Q1 and Q2)
  that measures the always-loaded footprint and proposes moves toward
  progressive disclosure, without duplicating the docs-qa skill or the
  docs_qa checks.
- The daemon's own ruleset and checks reconciled with the contract where they
  disagree (the R7a `description` field, the non-recursive rules scope).

## Non-Goals

- Restructuring the daemon-injected `<hooksdaemon>` block in a client's
  `CLAUDE.md`. It is daemon-owned, regenerated on restart, and its size is
  Plan 00116's subject.
- Re-implementing what `/doctor prompt-audit` already does (outdated
  instructions, missing references, contradictions), beyond what QUESTIONS.md
  Q8 rules.
- Changing the SSoT ruleset's substance (R1 to R14) other than the
  contract-driven corrections above.
- Auto-refreshing the contract from upstream prose. Extraction is verified by
  review, as for the hooks contract (Plan 00271 Decision 3).
- Managing auto memory (`MEMORY.md`), which Claude writes itself.

## Tasks

Phases 1 to 5 are cut to the rulings in RULINGS-fable.md (Q1 C, Q2 B-only,
Q3 A, Q4 B, Q5 D+E, Q6 C, Q7 A, Q8 D, Q9 A). The apply path, the
`InstructionsLoaded` verification, the G6 variants group and a client-side
staleness advisory are named follow-ups there, outside this plan.

### Phase 0: Rulings

- [x] ✅ **Task 0.1**: Put QUESTIONS.md to the ruling agent; record each
  ruling in QUESTIONS.md and RULINGS-fable.md and re-cut Phases 1 to 5 to
  match.

### Phase 1: Loading-rules contract

- [x] ✅ **Task 1.1** (d8e00958e): Define the contract's schema at
  `contracts/claude-code-instructions/` (Q3 A): a `META.json` with the same
  keys as the hooks contract's, and one facts file in which each fact carries
  an id, the pinned statement, its anchor in the vendored `memory.md`
  (heading slug plus quoted phrase), and the minimum Claude Code version
  where the page states one; plus an `unmodelled` list naming the G6 inputs
  (Q4).
- [x] ✅ **Task 1.2** (d8e00958e): Populate groups G1 to G5 (Q4 B) from
  `remote-docs/code.claude.com/docs/en/memory.md`, and add the refresh
  procedure as a section of `docs/guides/HOOK-CONTRACT-REFRESH.md` so both
  contracts share one procedure.
- [x] ✅ **Task 1.3** (d8e00958e): Tests (written first) that load the contract and fail
  when a fact lacks a source anchor, the audited version is missing, or the
  `META.json` version disagrees with the hooks contract's and with
  `claude-code-versions.yaml` (extend
  `tests/integration/test_claude_code_version_record.py`).
- [ ] ⬜ **Task 1.4**: Reconcile the ruleset and checks with the contract:
  R7a's frontmatter wording, `rules_file_shape`'s directory scope, and any
  other disagreement the population turns up, each as its own tested change.

### Phase 2: Re-audit trigger

- [ ] ⬜ **Task 2.1**: Extend `contract_staleness` (Q5 D+E) to read the
  instructions contract's `META.json` and, in the daemon repository only,
  produce one advisory per version when the installed Claude Code is newer
  than its audited version; the client branch is unchanged (follow-up F4).
- [ ] ⬜ **Task 2.2**: Extend release Step 1c and the
  `claude-code-changelog-reviewer` brief to flag instruction-loading changes
  against the contract, with the vendored page's hash in `META.json` as the
  evidence the refresh records.

### Phase 3: Footprint measurement

- [ ] ⬜ **Task 3.1**: `hooks-daemon docs-qa --footprint [--json]` (Q1 C), a
  deterministic measurement that resolves, per the contract, what loads at
  session start (root and ancestor `CLAUDE.md`, `.claude/CLAUDE.md`,
  `CLAUDE.local.md`, unscoped rules found recursively, imports to the pinned
  depth) versus on demand (nested `CLAUDE.md`, `paths:`-scoped rules), with
  line and byte totals against the contract's size guidance, the contract's
  audited version beside the installed Claude Code version, and the
  contract's `unmodelled` list.
- [ ] ⬜ **Task 3.2**: Count but never propose (Q9 A): the daemon-injected
  `<hooksdaemon>` block, daemon-deployed artefacts, `CLAUDE.local.md`, and
  user-scope files under `~/.claude/`.

### Phase 4: Restructure skill

- [ ] ⬜ **Task 4.1**: Skill source at
  `src/claude_code_hooks_daemon/skills/docs-optimise/` (Q1 C, Q7 A: deployed
  to every client by `install/skills.py` with no config gate), written as a
  shim per R7b that points at the core document and the contract rather than
  restating them.
- [ ] ⬜ **Task 4.2**: The proposal procedure (Q2 B, Q6 C): classify each
  always-loaded section as resident, path-scopable, nested-module, or
  on-demand under the ruleset that applies (`documentation.enabled` true:
  the daemon ruleset, R6/R7a/R7d; otherwise Claude Code's guidance), state
  which applied, and write the proposed new files plus a unified patch under
  `untracked/scratch/docs-optimise/<run-id>/`, never touching a tracked file
  and never adding an allowlist entry.
- [ ] ⬜ **Task 4.3**: The report's closing hand-offs (Q8 D): `/docs-qa`
  scoped to the touched files for SSoT re-verification, and
  `/doctor prompt-audit` for content audit, neither re-implemented.
- [ ] ⬜ **Task 4.4**: Dogfood on this repository's root `CLAUDE.md` and on a
  synthetic client fixture run under both Q6 modes; record the before and
  after footprint.

### Phase 5: Documentation and release

- [ ] ⬜ **Task 5.1**: Point the core document and
  `CLAUDE/DocumentationStrategy.md` at the contract and the skill (pointers
  only, R1).
- [ ] ⬜ **Task 5.2**: Release notes and any config-changes manifest entry in
  the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.

## Success Criteria

- [ ] Every QUESTIONS.md question carries a recorded ruling.
- [ ] The loading-rules contract exists, every fact cites its upstream anchor,
  and it names the Claude Code version it was audited against.
- [ ] An installed Claude Code newer than that version produces a re-audit
  advisory; an equal or older one produces none (tested).
- [ ] The R7a frontmatter wording and the `rules_file_shape` scope agree with
  the contract, with tests.
- [ ] `docs-qa --footprint` reports the session-start and on-demand footprint
  of this repository and of a fixture client, prints the audited and
  installed versions and the `unmodelled` list, and excludes the daemon-owned
  block, `CLAUDE.local.md` and user-scope files from proposals.
- [ ] The `docs-optimise` skill deploys to a client `.claude/skills/` through
  `install/skills.py`, and on the fixture writes its proposal under
  `untracked/scratch/docs-optimise/` with no tracked file modified (tested
  by a clean `git status` after the run).
- [ ] Release-bound consequences (new skill, new advisory, any new config key)
  are recorded in the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.
- [ ] Targeted QA passes on the branch; the coordinator's full gate passes.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00532-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Planned; decisions pending.
