# Plan 00308: post upgrade config optimisation autorun

**Status**: In Progress
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner field report: client projects are not encouraged enough to properly
enable and configure handlers when installing or upgrading the hooks daemon.
In practice the owner has to prompt, near-verbatim every time: "enable all
relevant handlers and ensure optimal configuration making best use of hooks
daemon features relevant to this project". A capability the project never
enables might as well not have shipped — the upgrade path delivers new
handlers dark by default and nothing pushes the project to look at them.

The `optimise` skill already exists (analyses configuration and recommends
improvements across Safety, Stop Quality, Plan Workflow, Code Quality and
Daemon Settings), so this plan is NOT about building analysis from scratch.
It is about formalising the owner's recurring prompt as a first-class step —
`/hooks-daemon config-optimisation` (or promoting `/optimise`) — and making
the upgrade flow invoke it AUTOMATICALLY, so every upgrade ends with a
concrete "here is what you are not using, and what enabling it would give
you" pass instead of silence.

## Goals

- One formal entry point for "enable all relevant handlers and ensure
  optimal configuration for this project" — discoverable, repeatable, and
  the same whether run manually or post-upgrade.
- The upgrade path (`/hooks-daemon upgrade`, `LLM-UPDATE.md`, and the
  upgrade scripts' printed next-steps) automatically runs or explicitly
  hands off to that step, so no upgrade ends without a configuration review.
- New-in-this-release handlers are surfaced with their default state and a
  per-project enable/skip recommendation, not just a CHANGELOG mention.

## Non-Goals

- Auto-ENABLING handlers without a human decision — the autorun produces a
  reviewed recommendation set (and can apply it on explicit confirmation),
  it never silently flips config.
- Rewriting the `optimise` skill's analysis dimensions (extend, don't fork).
- Fresh-install scope creep beyond wiring the same step into the install
  guide's final steps (the mechanism must work for install too, but upgrade
  is the driving case).

## Tasks

### Phase 1: Audit the current encouragement surface

- [ ] ⬜ **Task 1.1**: Map every place a project learns about handler
  configuration during install/upgrade today: the `optimise` and
  `configure` skills, `LLM-INSTALL.md`/`LLM-UPDATE.md`, upgrade script
  output, UPGRADES/ truth-changes and config-changes manifests, and any
  session-start checkers (e.g. project_handler_load_checker,
  tool_disable_advisor). Record in a findings doc where the gap is — why
  the owner still has to prompt manually every time.

### Phase 2: Formalise the step

- [ ] ⬜ **Task 2.1**: Define `/hooks-daemon config-optimisation` (or
  promote/alias the existing `optimise` skill) as the canonical
  "enable-and-configure review": inventory disabled-but-relevant handlers,
  compare current config against the release's capabilities (using the
  UPGRADES/ config-changes manifests for what is new since the installed
  version), and emit a prioritised recommendation list with per-handler
  enable/skip rationale and ready-to-apply config snippets.
- [ ] ⬜ **Task 2.2**: Make it apply-capable: on explicit user
  confirmation, write the agreed config changes and restart/verify the
  daemon — the same acceptance discipline as the `configure` skill.

### Phase 3: Wire it into the upgrade (and install) flow

- [ ] ⬜ **Task 3.1**: `/hooks-daemon upgrade` ends by invoking the
  config-optimisation step automatically (with an opt-out flag), and the
  upgrade scripts' printed next-steps say so; `LLM-UPDATE.md` makes it a
  numbered mandatory step rather than a suggestion.
- [ ] ⬜ **Task 3.2**: Post-upgrade session-start reinforcement: a
  session-start advisory (or extension of an existing checker) that fires
  when the installed version changed since the last config-optimisation
  run, so a skipped autorun is surfaced in the next session instead of
  being lost.
- [ ] ⬜ **Task 3.3**: Add the same closing step to `LLM-INSTALL.md` so
  fresh installs get the review too.

### Phase 4: Dogfood and client-verify

- [ ] ⬜ **Task 4.1**: Run the formalised step against this repo (dogfood)
  and against a client-mode test project (per
  CLAUDE/development client-mode testing docs); journal what it
  recommended and whether the recommendations were correct and actionable.

## Success Criteria

- [ ] Running the single formal command reproduces (or beats) what the
  owner's manual "enable all relevant handlers…" prompt achieves today.
- [ ] A `/hooks-daemon upgrade` in a test project ends with a concrete
  per-handler recommendation list without any extra prompting.
- [ ] A skipped post-upgrade review is surfaced at the next session start.
- [ ] No config change is ever applied without explicit user confirmation.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00308-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
