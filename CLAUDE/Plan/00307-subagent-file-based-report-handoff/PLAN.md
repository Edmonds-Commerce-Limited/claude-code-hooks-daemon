# Plan 00307: subagent file based report handoff

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Field report (owner, from another project's session): dispatched subagents
"failed when they returned a truncated message back to the main agent" —
their final report exceeded the harness's tool-result size cap (suspected
~16k-token default), so the coordinator received a garbled, cut-off blob.
Even below the cap, a huge inline report is pure context tax on the
coordinator: it pays tokens for detail it usually only needs a pointer to.

The norm this plan establishes and then enforces: **subagents (and agent-team
members) communicate large data by FILE, never by direct message.** Long-form
output goes to a report file; the returned message is a short completion
summary plus the file path ("done, full report at untracked/agent-reports/…").
Truncation is the visible symptom; the enforced norm fixes the underlying
cost as well.

Adjacent, not overlapping: Plan 00032 (blocked upstream) is about WHEN to
delegate to preserve coordinator context; this plan is about HOW results
travel back. Plan 00264 (GitHub comment size cap) is the same "oversized blob
into a bounded channel" defect class aimed at a different channel — reuse its
threshold/steering design thinking where it fits.

## Goals

- Prove the problem with a live reproduction (owner-ruled, replacing an
  earlier measure-first phase): dispatch a subagent instructed to return an
  oversized final message and record what the coordinator actually receives.
- Prevention at dispatch: the Agent-tool prompt carries the file-handoff
  contract so agents know the rule before they start.
- Enforcement at return: a subagent whose final message exceeds the threshold
  is blocked from stopping until it writes the report to a file and replies
  with a summary + path.
- Dogfood both handlers in this repo before defaulting them on for clients.

## Non-Goals

- Raising or working around the harness's tool-result size cap (upstream
  behaviour; the file-handoff norm is preferable even with a bigger cap).
- Post-hoc shrinking of an already-returned result (PostToolUse cannot
  rewrite a tool result payload).
- Plan 00032's delegation-enforcement scope (blocked upstream; cross-linked).

## Tasks

### Phase 1: Reproduce and verify the surfaces

- [x] ✅ **Task 1.1** (findings: `REPRODUCTION.md`): Live reproduction
  (RED): dispatch a subagent
  explicitly instructed to return an oversized final message (well past the
  suspected ~16k-token cap; e.g. generate long structured filler and return
  it ALL inline, writing nothing to disk). Record in a findings doc in this
  plan folder: what the coordinator received (truncated? garbled? errored?),
  the observed size limit, and the exact dispatch prompt so the run is
  repeatable verbatim as the Phase 4 acceptance check. This same evidence
  pins the enforcement threshold.
- [x] ✅ **Task 1.2** (report:
  `subagent-reports/260901-explore-hook-surfaces-fable.md`): Verify the
  hook surfaces against the vendored
  contract (contracts/claude-code-hooks/, now at v2.1.252): confirm what
  SubagentStop receives (transcript path? final message?), whether the
  daemon's existing transcript-reading machinery (stop-quality handlers) can
  read a SUBAGENT transcript, and whether agent-team `SendMessage` traffic
  is visible to any PreToolUse surface. Record findings in the same doc.

### Phase 2: Prevention at dispatch (PreToolUse on Agent)

- [x] ✅ **Task 2.1**: TDD a PreToolUse handler on the `Agent` tool
  enforcing a dispatch declaration (owner-ruled): every dispatch prompt
  must EITHER name the plan folder the agent is working in — which then IS
  the canonical location for its reports and other artefacts — OR
  explicitly declare it is not plan work AND name where any files it
  creates must go. A prompt declaring neither gets the contract injected
  (advisory additionalContext by default; optional strict mode denies until
  a declaration is present). The same declaration carries the file-handoff
  rule: long-form output goes to a file in the declared location, the final
  message is summary + path. Fallback location for genuinely plan-less
  work: configurable, default `untracked/agent-reports/`. Enable in this
  repo (dogfood).
- [x] ✅ **Task 2.2** (owner-ruled): standardise WHERE and WHAT NAME.
  Reports live in a standard `subagent-reports/` subfolder of the declared
  plan folder (created on demand; plan-less work uses the fallback
  directory), with a standard filename `{yymmdd}-{agent-name}-{model}.md`
  (e.g. `260901-explore-surface-check-haiku.md`). The Task 2.1 handler's
  injected guidance states the exact expected path for THIS dispatch;
  document the convention in the plan-workflow docs (PlanWorkflow.md /
  DirectoryRoles.md) and teach plan QA to treat `subagent-reports/` as a
  recognised plan-folder member.

### Phase 3: Enforcement at return (SubagentStop)

- [x] ✅ **Task 3.1**: TDD a SubagentStop handler that measures the
  subagent's final message and, above the configured threshold, blocks the
  stop with remediation: "write the full report to a file under the report
  directory; reply with a short summary + path". Fail-open on any
  transcript-read failure. Threshold from Task 1.1's findings.
- [x] ✅ **Task 3.2**: Wire-up completeness: HandlerID/Priority, `__init__`
  export, config template + example, drift-guard set, docs (CLAUDE.md
  handler guidance regeneration), explain-handler text. Note SubagentStop
  wiring status in `constants/events.py` — if the event is currently
  unwired, wiring it is part of this task.

### Phase 4: Prove the fix, dogfood, then default

- [ ] ⬜ **Task 4.1**: Re-run the Task 1.1 reproduction VERBATIM (GREEN):
  the same oversized-return dispatch must now be caught — the dispatch-time
  contract injected, and the oversized final message blocked at
  SubagentStop until the agent re-routes the report through a file and
  returns summary + path. Record the before/after in the findings doc.
- [ ] ⬜ **Task 4.2**: Dogfood both handlers in this repo across real
  multi-agent work; journal observed fires, false positives, and agent
  compliance. Tune thresholds/wording from the journal evidence.
- [ ] ⬜ **Task 4.3**: Decide per-handler client defaults
  (`get_default_enabled`) from the dogfood evidence; update docs and
  CHANGELOG for release.

## Success Criteria

- [ ] Evidence-based threshold: measured size distribution and truncation
  frequency recorded in this plan folder, cited by the chosen defaults.
- [ ] A subagent dispatched without the file-handoff contract gets it
  injected at dispatch time (observed live in this repo).
- [ ] A subagent attempting to return an oversized final message is blocked
  at SubagentStop and successfully re-routes its report through a file
  (observed live in this repo).
- [ ] All failure paths fail open; full QA green; daemon restart verified.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00307-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- `5f674028` — Phase 2 (Task 2.1/2.2) + Phase 3 (Task 3.1/3.2): dispatch_declaration
  and subagent_report_size_blocker handlers, docs, wire-up, both enabled in
  this repo's dogfood config
