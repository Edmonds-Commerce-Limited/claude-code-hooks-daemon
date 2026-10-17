# Plan 00532: docs optimisation skill

**Status**: Not Started (decisions pending: see QUESTIONS.md)
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

Phases 2 to 4 take their shape from the QUESTIONS.md rulings; the tasks below
assume the recommended options and are re-cut once the rulings land.

### Phase 0: Rulings

- [ ] ⬜ **Task 0.1**: Put QUESTIONS.md to the ruling agent; record each
  ruling in QUESTIONS.md and re-cut Phases 2 to 4 to match.

### Phase 1: Loading-rules contract

- [ ] ⬜ **Task 1.1**: Define the contract's schema and location (Q3, Q4): the
  facts it pins, each with its source anchor in the vendored `memory.md`, the
  minimum Claude Code version where the doc states one, and the audited
  version in a `META.json` mirroring the hooks contract.
- [ ] ⬜ **Task 1.2**: Populate it from
  `remote-docs/code.claude.com/docs/en/memory.md` and `sub-agents.md`, and
  write the refresh procedure as a guide alongside
  `docs/guides/HOOK-CONTRACT-REFRESH.md`.
- [ ] ⬜ **Task 1.3**: Tests (written first) that load the contract and fail
  when a fact lacks a source anchor or the audited version is missing.
- [ ] ⬜ **Task 1.4**: Reconcile the ruleset and checks with the contract:
  R7a's frontmatter wording, `rules_file_shape`'s directory scope, and any
  other disagreement the population turns up, each as its own tested change.

### Phase 2: Re-audit trigger

- [ ] ⬜ **Task 2.1**: Extend the staleness signal (Q5) so an installed Claude
  Code newer than the contract's audited version produces one advisory per
  version, in the daemon repository and in a client install where the
  contract ships.
- [ ] ⬜ **Task 2.2**: Record the contract's audited version in the release
  step that writes `CLAUDE/development/claude-code-versions.yaml`, and extend
  the `claude-code-changelog-reviewer` brief to flag instruction-loading
  changes against the contract.

### Phase 3: Footprint measurement

- [ ] ⬜ **Task 3.1**: A deterministic measurement (Q1 decides CLI verb or
  bundled script) that resolves, per the contract, what loads at session start
  (root and ancestor `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`,
  unscoped rules, imports to the pinned depth) versus on demand (nested
  `CLAUDE.md`, `paths:`-scoped rules), with line and byte totals against the
  contract's size guidance; JSON output for the skill.
- [ ] ⬜ **Task 3.2**: Exclude the daemon-injected block and the daemon's
  deployed artefacts from the proposable set while still counting their size.

### Phase 4: Restructure skill

- [ ] ⬜ **Task 4.1**: Skill source under `src/claude_code_hooks_daemon/skills/`
  (Q1, Q7), deployed by `install/skills.py`, written as a shim per R7b that
  points at the core document and the contract rather than restating them.
- [ ] ⬜ **Task 4.2**: The proposal procedure (Q2, Q6): classify each
  always-loaded section as resident, path-scopable, nested-module, or
  on-demand, and propose the move with its target home, honouring R7a's
  create-the-home-first rule.
- [ ] ⬜ **Task 4.3**: Hand-off to docs-qa (Q8) so a proposed or applied
  restructure is re-verified by the existing checks and agent.
- [ ] ⬜ **Task 4.4**: Dogfood on this repository's root `CLAUDE.md` and on a
  synthetic client fixture; record the before and after footprint.

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
- [ ] The measurement reports the session-start and on-demand footprint of
  this repository and of a fixture client, and excludes the daemon-owned block
  from proposals.
- [ ] The skill deploys to a client `.claude/skills/` through
  `install/skills.py`, and on the fixture produces the outcome Q2 rules
  without touching a file the ruling does not permit.
- [ ] Release-bound consequences (new skill, new advisory, any new config key)
  are recorded in the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.
- [ ] Targeted QA passes on the branch; the coordinator's full gate passes.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00532-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Planned; decisions pending.
