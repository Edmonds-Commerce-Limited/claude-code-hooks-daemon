# Plan 00307: subagent file based report handoff

**Status**: Complete
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

- [x] ✅ **Task 4.1** (PASS — see `REPRODUCTION.md` GREEN section; two
  tuning findings carried into Task 4.2): Re-run the Task 1.1 reproduction
  VERBATIM (GREEN):
  the same oversized-return dispatch must now be caught — the dispatch-time
  contract injected, and the oversized final message blocked at
  SubagentStop until the agent re-routes the report through a file and
  returns summary + path. Record the before/after in the findings doc.
- [x] ✅ **Task 4.2**: Dogfooded across three live probe runs (RED
  truncation confirmed; GREEN blocked+re-routed with two tuning findings;
  third run fully convention-compliant after `e2729470`) plus a full session
  of real multi-agent dogfood — implementation agents dispatched with plan
  declarations, returning short summaries + `subagent-reports/` files, zero
  false-positive blocks observed on legitimate returns. Owner has called
  time on this task: **passive multi-session soak is no longer a gate** —
  the evidence above (live reproduction + a full dogfood session with no
  false positives) is treated as sufficient, superseding the original
  "measured size distribution" framing in the Success Criteria (see note
  there).
- [x] ✅ **Task 4.3**: Both handlers ship **enabled by default**
  (`get_default_enabled` returns the base-class `True`, i.e. no override
  needed) — decided from the dogfood evidence above and this repo's
  precedent: opt-in (`False`) is reserved for handlers whose behaviour
  requires PROJECT-SPECIFIC configuration to be useful or safe (e.g.
  `skill_opportunity_detector` reads session transcripts,
  `flaggable_content_channel_guard` needs a declared flaggable boundary,
  `lsp_enforcement` needs an LSP configured); opt-out (`True`) is for
  universal, fail-open, project-agnostic safety behaviour (e.g.
  `secret_file_guard`). `dispatch_declaration` is advisory-only in its
  default (non-strict) mode and `subagent_report_size_blocker` fails open
  on any missing/malformed input, so both fit the opt-out precedent, not
  the opt-in one. The client config template (`init_config.py`) and this
  repo's own dogfood config already carried `enabled: true` for both since
  Phase 2/3 landed; the stale `.claude/hooks-daemon.yaml.example` (which
  still showed `enabled: false`) was corrected to match. CHANGELOG and a
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/pending.yaml` manifest entry
  record the defaults for release.

## Success Criteria

- [x] Evidence-based threshold — **reworded, honestly**: the original
  wording promised a "measured size distribution" from a passive
  measure-first phase; the owner-ruled reshape (see `PLAN.md` Delivery
  history and `JOURNAL/`) replaced that with a live reproduce-first design
  instead. What is actually on file: Task 1.1's live reproduction measured
  the harmful shape directly (~24k-token / ~96k-character inline return,
  harness-truncated in the middle), and the default 4,000-character
  threshold sits an order of magnitude below that measured shape — see
  `REPRODUCTION.md`. Ticked on that basis, not on a distribution study that
  was never run.
- [x] A subagent dispatched without the file-handoff contract gets it
  injected at dispatch time (observed live in this repo — RED/GREEN/third
  probe runs, `REPRODUCTION.md`).
- [x] A subagent attempting to return an oversized final message is blocked
  at SubagentStop and successfully re-routes its report through a file
  (observed live in this repo — GREEN and third-run passes,
  `REPRODUCTION.md`).
- [x] All failure paths fail open; full QA green; daemon restart verified.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00307-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- `5f674028` — Phase 2 (Task 2.1/2.2) + Phase 3 (Task 3.1/3.2): dispatch_declaration
  and subagent_report_size_blocker handlers, docs, wire-up, both enabled in
  this repo's dogfood config
