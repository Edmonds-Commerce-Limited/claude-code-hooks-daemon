# Plan 00531: project tuned plan fact checker

**Status**: Not Started
**Created**: 2026-10-17
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked, during the v3.70.0 release, that the plan fact-checker work in client projects the way the
daemon's other deployed Claude Code config does: ship a generic agent, tell the project to tune it for its own
codebase, and keep track of which shipped version a tuned copy started from.

v3.70.0 already ships the generic agent: `hooks-daemon-plan-fact-checker` is deployed into `.claude/agents/` when
`plan_fact_check_feed` is enabled (callout 045). A pristine copy is refreshed on upgrade, and an edited copy is
classified customised and never touched (`install/agent_assets.py`). Three gaps remain:

- The template tells a project to customise by copying the agent to a new name. The feed always tells the session
  to dispatch the generic name, so a tuned copy is never used.
- Nothing prompts a project to tune the agent. A generic checker does not know the project's layout, test
  commands or vocabulary, so it checks less well than it could.
- A tuned copy does not record which shipped version it started from, so the project is never told when the
  generic template has improved and its copy may want the same change.

## Goals

- The feed dispatches the project's tuned fact-checker when one is configured, and the generic one otherwise.
- A project is told, once and in a way it can act on, how to tune the agent and where to record the tuned name.
- A tuned copy records the generic version it was derived from, and the project is told when a newer generic
  version ships.

## Non-Goals

- Tuning the agent for any particular client project.
- Changing the never-touch-customised rule for daemon-owned agents.

## Tasks

### Phase 1: Design and build

- [ ] ⬜ **Task 1.1**: Read `plan_fact_check_feed`, `utils/plan_fact_check.py`, `install/agent_assets.py`, the
  agent template and `deployed_artefact_drift`, and record the design in this plan: how a tuned agent is named
  and configured, how the derived-from version is recorded, and which existing handler reports a newer generic
  version.
- [ ] ⬜ **Task 1.2**: The feed names the configured tuned agent when set and present, the generic one otherwise
  (TDD).
- [ ] ⬜ **Task 1.3**: The tuning instruction: the template's header comment and the place a client reads it say
  how to tune and how to record the derived-from version (TDD where behaviour changes).
- [ ] ⬜ **Task 1.4**: A newer generic version than a tuned copy's derived-from version is reported to the project
  (TDD).
- [ ] ⬜ **Task 1.5**: Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/` (a release-notes
  callout, and a post-upgrade task telling client projects to tune the agent).

## Success Criteria

- [ ] With a tuned agent configured, the feed's instruction names it; without one, it names the generic agent.
- [ ] A client project is told how to tune the agent, and is told when the generic template moves past its copy.
- [ ] The release-bound consequences are in the pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/`).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00531-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened at the owner's request during the v3.70.0 release.
