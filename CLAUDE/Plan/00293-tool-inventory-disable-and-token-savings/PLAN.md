# Plan 00293: tool inventory disable and token savings

**Status**: In Progress
**Created**: 2026-08-30
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner direction (2026-08-30, verbatim intent): find tools that we actively
don't want (like Artifact) and suggest/enforce disabling them; have another
tool (like skills selection) which actively scans transcripts and finds tools
that are never used and could be disabled to save tokens; provide a report of
tools to disable vs tokens saved and let projects/agents decide; dogfood on
this repo. The motivating insight: *"some things we are trying to fight with
the hooks system when we could in fact just fully disable them instead."*
Reference the owner supplied:
<https://www.reddit.com/r/ClaudeCode/s/MZmn1ZvaEn> (verify its claims against
primary sources during research — a Reddit thread is a lead, not evidence).

Every enabled tool costs its schema in EVERY context window of EVERY session,
whether or not it is ever called — and some tools this project actively
opposes are fought at runtime with PreToolUse blockers
(`artifact_publish_blocker` is the poster child: a whole handler, docs and
config surface to police a tool the project may be able to switch off at the
source). Disable-at-source is strictly stronger than block-at-use where it is
available: no schema tokens, no bypass surface, no handler to maintain. The
hooks system remains the right tool where semantics matter (allow SOME uses),
but a binary never-want is a configuration fact, not a policy decision to
re-make on every call.

## Goals

- Ground truth, from primary sources: exactly which mechanisms Claude Code
  offers to disable/hide tools per project (settings permissions deny rules,
  disallowed-tools config, tool-search deferral behaviour), what each does to
  the context (is the schema actually omitted?), and measured/documented
  per-tool schema token costs.
- A transcript-usage analyser: scans a project's session transcripts (the
  same JSONL surfaces existing daemon tooling reads) and produces per-tool
  call counts across sessions, distinguishing never-used from rarely-used.
- A report generator (`bin/hooks-daemon tool-report` or similar): tools
  ranked by estimated token cost vs observed usage, with a recommended
  disable list split into (a) policy never-wants (project-declared, e.g.
  Artifact) and (b) observed never-used candidates. Report only — the
  project/agents decide; nothing is disabled automatically.
- An advisory path for enforcement-by-choice: where a project records a
  never-want, the daemon suggests (or optionally verifies at session start)
  that the settings-level disable is in place — and flags blocker handlers
  made redundant by a source-level disable.
- Dogfooded on this repo: the report runs here, its recommendations are
  reviewed, and at least one accepted recommendation is applied (candidate:
  Artifact — evaluate whether `artifact_publish_blocker` can be demoted to a
  backstop or retired where the source-level disable is verified).

## Non-Goals

- No automatic disabling of anything — the deliverable is information and
  opt-in verification, never a silent settings edit.
- No removal of existing blocker handlers in this plan without the dogfood
  evidence showing the source-level disable actually holds (defence in depth
  is retired deliberately, not by assumption).
- No general context-window optimisation beyond tool schemas (CLAUDE.md
  compression is Plan 00116's territory).

## Tasks

### Phase 1: Research (primary sources, written to RESEARCH-tool-disable.md)

- [x] ✅ **Task 1.1**: Establish the disable mechanisms: Claude Code settings
  (`permissions.deny`, tool allow/deny lists, env/config switches), what each
  actually removes from context (schema vs mere refusal), interaction with
  deferred tools/ToolSearch, and per-tool schema token cost (measured where
  possible — token-count the schemas — cited where documented). Verify or
  refute the supplied Reddit thread's claims against these sources.
- [x] ✅ **Task 1.2**: Inventory this repo's fight-with-hooks candidates:
  every blocker handler whose target could instead be disabled at source
  (artifact_publish_blocker first), with the semantic-vs-binary analysis for
  each (does the project ever want ANY use of the tool?).

### Phase 1b: Owner-directed source-disable enforcement (2026-08-30)

Owner direction after Phase 1 review: extend `artifact_publish_blocker` with
an optional full-disable feature that updates Claude settings directly, and
dogfood it on this repo. This supersedes open question 1 of the research doc
(answer: disable outright) and narrows the Phase 3 advisory scope: for
Artifact the enforcement lives in the blocker itself, not a separate advisory.

- [x] ✅ **Task 1.3**: TDD an opt-in `source_disable` option on
  `artifact_publish_blocker` (ships off): ensure `.claude/settings.json`
  carries `"enableArtifact": false` — additive, idempotent, atomic, one-shot
  backup, fail-safe on broken client files; deny reason and handler guidance
  updated; HANDLER_REFERENCE documented.
- [x] ✅ **Task 1.4**: Dogfood on this repo: option enabled in
  `.claude/hooks-daemon.yaml`, daemon restarted, verified
  `.claude/settings.json` gained `"enableArtifact": false` (backup written).
  Blocker retained as in-session backstop. `/context` schema-removal spot
  check in a fresh interactive session remains for Task 4.1.

### Phase 2: Analyser + report

- [x] ✅ **Task 2.1**: TDD the transcript tool-usage analyser (per-tool call
  counts across a project's session JSONLs, bounded reads, never loading
  whole transcripts into memory; reuse existing transcript-reading utilities
  where the daemon has them).
- [x] ✅ **Task 2.2**: TDD the report generator: ranked table (tool, schema
  token estimate, calls observed, sessions observed, recommendation tier
  never-want / never-used / low-use / keep), machine-readable JSON +
  human-readable markdown output under `untracked/reports/`.
- [x] ✅ **Task 2.3**: CLI wiring (`bin/hooks-daemon tool-report`) + config
  block for project-declared never-wants (validated, `extra="forbid"`,
  ships empty).

### Phase 3: Advisory integration

- [ ] ⬜ **Task 3.1**: Session-start advisory (opt-in, ships disabled):
  when a declared never-want is NOT disabled at source, advise with the
  exact settings change; when a source-level disable makes a blocker
  handler redundant, name it and the config to demote/disable it.

### Phase 4: Dogfood and gate

- [ ] ⬜ **Task 4.1**: Run the report on this repo's own transcripts; commit
  the findings summary (not raw transcripts) to this plan folder; review
  recommendations with the owner; apply at least one accepted
  recommendation end-to-end (candidate: Artifact never-want declared,
  source disable verified, blocker handler disposition decided).
- [ ] ⬜ **Task 4.2**: Full QA green; UPGRADES manifests + HANDLER_REFERENCE
  docs for the new config/CLI; daemon restart verified.

## Success Criteria

- [ ] Research doc answers, with citations/measurements, whether a
  settings-level disable removes the schema from context — the fact the
  whole token-savings case rests on.
- [ ] Report runs on this repo and produces a defensible tools-vs-tokens
  table; the never-used tier matches reality (spot-checked against known
  usage).
- [ ] Nothing is ever disabled automatically; the advisory names exact
  changes and stays opt-in.
- [ ] Dogfood applied at least one accepted recommendation with the
  redundant-handler analysis recorded.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
