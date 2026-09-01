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

- [x] ✅ **Task 1.1**: Map every place a project learns about handler
  configuration during install/upgrade today: the `optimise` and
  `configure` skills, `LLM-INSTALL.md`/`LLM-UPDATE.md`, upgrade script
  output, UPGRADES/ truth-changes and config-changes manifests, and any
  session-start checkers (e.g. project_handler_load_checker,
  tool_disable_advisor). Record in a findings doc where the gap is — why
  the owner still has to prompt manually every time. Findings:
  `subagent-reports/260901-implementation-sonnet.md`.

### Phase 2: Formalise the step

- [x] ✅ **Task 2.1**: Promoted the existing `optimise` skill as the
  canonical step rather than adding a parallel `config-optimisation`
  subcommand (rationale + full decision record in the findings doc). Added
  a Step 0 to `.claude/skills/optimise/invoke.sh` that reads
  `CLAUDE/UPGRADES/config-changes/v*.yaml` manifests newer than the last
  recorded run and folds new `handlers.*` entries into the recommendation
  list.
- [x] ✅ **Task 2.2**: Already satisfied structurally by the pre-existing
  `optimise` apply flow (explicit "apply all"/"apply N,M"/"skip"
  confirmation, then restart + verify) — no silent config writes.

### Phase 3: Wire it into the upgrade (and install) flow

- [x] ✅ **Task 3.1**: `src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md`
  gained a mandatory Step 8 invoking `/optimise`; `scripts/upgrade.sh` /
  `scripts/upgrade_version.sh` accept and forward `--skip-config-optimisation`
  and print the mandatory-next-step banner; `LLM-UPDATE.md`'s manual 5-step
  walkthrough replaced with one numbered mandatory step pointing at `/optimise`.
- [x] ✅ **Task 3.2**: New SessionStart handler `config_optimisation_reminder`
  (priority 67) + `config_optimisation` state module + CLI subcommand
  `record-config-optimisation-run`. Fires (advisory, fail-open) when the
  installed version differs from the last recorded run. This is the fallback
  for when Task 3.1's automatic invocation is skipped, opted out of, or
  reached via a path with no agent in the loop — not a duplicate of it.
- [x] ✅ **Task 3.3**: Added "Post-Installation: Run the Config-Optimisation
  Review (MANDATORY)" section to `LLM-INSTALL.md`.

### Phase 4: Dogfood and client-verify

- [x] ✅ **Task 4.1**: Dogfooded from the worktree (informational, see the
  venv caveat in the dispatch instructions); enabled the new handler in this
  repo's own `.claude/hooks-daemon.yaml`. Full findings, and what remains for
  live verification by the coordinator, are in the findings doc.

## Success Criteria

- [x] Running the single formal command (`/optimise`) reproduces what the
  owner's manual "enable all relevant handlers…" prompt achieves today —
  it already did; this plan formalised the invocation, not the analysis.
- [x] `/hooks-daemon upgrade`'s workflow doc ends with a mandatory
  per-handler recommendation step (`/optimise`) without extra prompting,
  unless `--skip-config-optimisation` was passed. Live end-to-end
  verification (a real upgrade run) is left for the coordinator — see the
  findings doc.
- [x] A skipped post-upgrade review is surfaced at the next session start
  (`config_optimisation_reminder`, live-verification steps in the findings
  doc).
- [x] No config change is ever applied without explicit user confirmation
  (unchanged `optimise` apply-flow contract).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00308-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
