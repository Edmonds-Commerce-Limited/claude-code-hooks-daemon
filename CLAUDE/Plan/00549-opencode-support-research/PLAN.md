# Plan 00549: opencode support research

**Status**: In Progress
**Created**: 2026-10-22
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #136

## Overview

The owner asked whether the hooks daemon can support **opencode** (sst/opencode) as a host alongside Claude Code.
This plan is research only. Its findings are the foundation for a new epic of work, so it must be broad, cited and
honest about what opencode cannot do.

Four questions frame it:

1. Does opencode have a hooks system, or something equivalent? What can a harness like this daemon hook into, and
   which of those points can block or rewrite a tool call rather than only observe it?
2. Can the plan workflow be provisioned or enforced under opencode? That covers plan folders, `mkplan.bash`, journals
   and the stop gates.
3. Can one repository be worked on with both opencode and Claude Code? That covers instruction files, config,
   skills, agents and commands, and MCP.
4. How is opencode fundamentally the same as Claude Code, and how is it different?

Plan 00292 (Codex CLI dual-host research, Complete) answered the same question for Codex CLI. Its
`RESEARCH-daemon-couplings.md`, `MAPPING-events.md` and `OPTIONS-abstraction.md` are starting material, to be cited
and refreshed rather than re-derived. Plan 00169's prior-art survey touched opencode in passing.

## Goals

- A cited inventory of opencode's extension surface: plugins, events, permissions, custom tools, MCP, LSP and
  formatters. Each entry notes the opencode version or commit it was read from.
- An event mapping from every Claude Code hook event the daemon handles to its opencode counterpart. For each one,
  record whether the counterpart can deny, rewrite, inject context, or only observe, or that there is none.
- A plan-workflow feasibility analysis: which of the daemon's plan and stop-gate behaviours can be reproduced under
  opencode, and by what mechanism.
- A dual-tool repository guide: which files each tool reads, where they conflict, and what one repository needs in
  order to serve both.
- A same/different architecture comparison.
- An options paper and an epic proposal: the candidate shapes of support, their trade-offs, a recommendation, and
  the open questions for the owner.

## Non-Goals

- Any code, config or handler change. This plan is research only.
- Implementing an opencode adapter. That is the epic this plan proposes.
- Re-doing Plan 00292's Codex research.

## Tasks

### Phase 1: Parallel research sweep

- [ ] ⬜ **Task 1.1**: opencode extension surface → `RESEARCH-opencode-extension-surface.md`.
- [ ] ⬜ **Task 1.2**: opencode architecture and lifecycle: client/server split, sessions, agents and sub-agents,
  modes, compaction, providers, headless and SDK use → `RESEARCH-opencode-architecture.md`.
- [ ] ⬜ **Task 1.3**: dual-tool repositories: instruction files, config files, skills, commands, agents, MCP and
  permissions; what each tool reads and where they collide → `RESEARCH-dual-tool-repos.md`.
- [ ] ⬜ **Task 1.4**: daemon couplings refresh. Start from Plan 00292's inventory and re-check it against today's
  tree. List every Claude Code assumption: event names, payload shapes, response JSON, forwarders, settings,
  transcripts, plan workflow and status line → `RESEARCH-daemon-couplings.md`.

### Phase 2: Mapping and options

- [ ] ⬜ **Task 2.1**: Event and capability mapping → `MAPPING-events.md`.
- [ ] ⬜ **Task 2.2**: Plan-workflow and enforcement feasibility under opencode → `ANALYSIS-plan-workflow.md`.
- [ ] ⬜ **Task 2.3**: Abstraction options and a recommendation → `OPTIONS-support.md`.

### Phase 3: Synthesis and gate

- [ ] ⬜ **Task 3.1**: `FINDINGS.md`: answers to the four questions, the same/different comparison, and an epic
  proposal broken into candidate plans.
- [ ] ⬜ **Task 3.2**: A fact-check of the findings against opencode's source and docs and this repository. Fix
  anything refuted.
- [ ] ⬜ **Task 3.3**: Comment the findings on #136. Owner questions go up only where an adviser cannot rule.

## Success Criteria

- [ ] Each of the four questions has a cited answer in `FINDINGS.md`.
- [ ] Every Claude Code event the daemon handles appears in `MAPPING-events.md` with a capability verdict.
- [ ] The options paper gives the owner enough to decide whether to start the epic, and in what shape.
- [ ] No release-bound consequences: research only, with no change a client sees, so nothing goes to
  `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area).

## Delivery & Milestones

- Plan filed; Phase 1 dispatched.
