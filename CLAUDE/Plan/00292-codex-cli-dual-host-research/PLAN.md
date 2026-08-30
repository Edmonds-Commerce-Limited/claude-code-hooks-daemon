# Plan 00292: codex cli dual host research

**Status**: In Progress
**Created**: 2026-08-30
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**Research only — no code changes.** Owner direction (2026-08-30): investigate
how this project could be upgraded to support BOTH Claude Code and OpenAI's
Codex CLI as host agents. Dig into where the two hook surfaces are compatible,
where there is a clear one-to-one mapping, where they differ semantically, and
what abstraction layers could host both. All output lives in THIS plan folder
as research documents; the deliverable is understanding, options and a
recommendation — not an implementation.

The daemon today is Claude-Code-shaped end to end: hook events registered in
`.claude/settings.json` as `type: command` forwarders, Claude's hook-input
JSON schemas, its verdict/permission response contract, transcript paths,
status line, and session lifecycle. Codex CLI has its own configuration and
extension surface, and any dual-host story hinges on whether its hooks can
carry BLOCKING verdicts (our core value) or are notify-only, and on how its
event taxonomy maps to ours. Completed Plan 00169 contains prior Codex CLI
competitive analysis — a starting point, but it studied Codex for ideas, not
for hosting.

## Goals

- An accurate, cited inventory of Codex CLI's hooks/extension surface as it
  exists today (docs, source, changelogs — not assumptions), including its
  config format, event taxonomy, payload schemas, response semantics
  (blocking vs advisory), and lifecycle.
- A mapping table: every daemon-relevant Claude Code hook event vs its Codex
  counterpart — one-to-one, partial (semantic gaps named), or absent.
- An inventory of the daemon's Claude-Code couplings (events, schemas,
  settings registration, transcript/status/cron surfaces) ranked by how hard
  each is to abstract.
- Evaluated abstraction options (e.g. host-adapter layer at the front
  controller, host-specific forwarder generation, MCP as a common substrate,
  a verdict-degradation story for notify-only hosts) with trade-offs and a
  recommendation.
- Everything written into named research documents in this folder.

## Non-Goals

- No code changes anywhere — src/, tests/, config, installers all untouched.
- No commitment to implement: the output is research and a recommendation;
  any implementation would be its own planned work.
- No Codex CLI installation into this container unless reading docs/source
  proves insufficient (and then only sandboxed inspection, no daemon wiring).

## Tasks

### Phase 1: Parallel research sweep (Sonnet workflow)

- [ ] ⬜ **Task 1.1**: Codex CLI hooks/extension surface — primary sources
  (official docs, GitHub source/releases), written to
  `RESEARCH-codex-surface.md` with citations and verbatim schema excerpts.
- [ ] ⬜ **Task 1.2**: Codex CLI configuration + session lifecycle (config
  format, exec modes, approval/sandbox model, MCP support) —
  `RESEARCH-codex-lifecycle.md`.
- [ ] ⬜ **Task 1.3**: Daemon Claude-Code-coupling inventory from THIS repo's
  code (events, hook-input models, verdict contract, settings.json
  registration, forwarders, transcript/status-line/cron touchpoints) —
  `RESEARCH-daemon-couplings.md`.
- [ ] ⬜ **Task 1.4**: Prior art — Plan 00169's Codex analysis revisited, plus
  any ecosystem tools that already bridge multiple agent CLIs —
  `RESEARCH-prior-art.md`.

### Phase 2: Mapping and options

- [ ] ⬜ **Task 2.1**: Event/semantic mapping table (one-to-one / partial /
  absent, with the blocking-vs-advisory question answered per event) —
  `MAPPING-events.md`.
- [ ] ⬜ **Task 2.2**: Abstraction options paper with trade-offs and a
  recommendation — `OPTIONS-abstraction.md`.

### Phase 3: Synthesis and gate

- [ ] ⬜ **Task 3.1**: Executive synthesis at the top of a `FINDINGS.md`
  (what is possible today, what Codex would need to add, recommended path,
  open questions for the owner), cross-linking the supporting docs.
- [ ] ⬜ **Task 3.2**: Completeness pass — a critic agent checks for
  unanswered questions, uncited claims and stale-version risks; findings
  fixed or recorded as open questions. Plan flipped Complete and archived.

## Success Criteria

- [ ] Every factual claim about Codex CLI carries a citation to a primary
  source (URL + what it says); uncertainty is stated as uncertainty.
- [ ] The mapping table covers every hook event the daemon wires today.
- [ ] The options paper gives the owner enough to decide whether dual-host
  support is worth planning — including the honest "not worth it" case.
- [ ] Zero code changes on any branch; all output inside this plan folder.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
