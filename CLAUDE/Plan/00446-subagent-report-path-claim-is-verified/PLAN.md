# Plan 00446: subagent report path claim is verified

**Status**: Not Started
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Ledger 00422 N15: a dedupe scout's final message ended `Report written to:`
followed by a path that was well-formed, matched the convention exactly, and
named a file that was never created. The verdict arrived inline and was
recoverable by hand, so it cost nothing that time. What it costs otherwise is a
PLAN.md citing evidence at a path that resolves to nothing.

No caller-stated value can catch this. Plan 00434's remedy for N13 — the
caller states the plan count so the agent's own enumeration can be checked
against something outside it — works, and is not in question. But N15 is the
report's own EXISTENCE claim being false, and the coordinator has nothing to
compare it against except the filesystem.

`subagent_report_size_blocker` (Plan 00307) establishes the shape. Its
reasoning transfers exactly: a coordinator cannot detect the failure by
inspecting what it received, because what it received looks right. So the
check belongs on the SUBAGENT side, at the moment it stops — the one point
where the claim and the filesystem are both in reach.

## Goals

- A subagent that claims in its final message to have WRITTEN a file is
  blocked from stopping when that file does not exist, and told to write it or
  drop the claim.
- The check is narrow enough to be trusted: a message that merely MENTIONS a
  path — one it read, one it is recommending — is never blocked.

## Non-Goals

- No verification that the content is any good, or that it matches what the
  dispatch asked for. This checks existence, which is the claim that was false.
- No change to `dispatch_declaration`. Reading the declared destination at
  SubagentStop is a larger question (the declaration is not carried on this
  surface), and N15's defect is detectable without it — the agent named the
  path itself.
- No change to `subagent_report_size_blocker`. Sibling handler, separate
  config key, separate failure.

## Tasks

### Phase 1: the claim detector

- [ ] ⬜ **Task 1.1**: RED first — a claim-extraction helper with a corpus of
  real message shapes, including a CONTROL set that must NOT match: a path an
  agent says it read, a path it recommends the coordinator create, a path
  inside a fenced code block, a bare path with no verb. False positives are
  the whole risk here: this handler blocks a stop, so a message that mentions
  a filename it did not write must sail through.
- [ ] ⬜ **Task 1.2**: Resolve the claim against the project root and stat it.
  Only paths INSIDE the project are judged — a claim about a path elsewhere is
  not this repository's business and cannot be checked reliably.

### Phase 2: the handler

- [ ] ⬜ **Task 2.1**: `SubagentReportPathVerifierHandler` on SubagentStop,
  modelled on `subagent_report_size_blocker`: terminal, `stop_hook_active`
  loop guard, fails OPEN on a missing or unreadable `last_assistant_message`.
  New `HandlerID` and `Priority` entries.
- [ ] ⬜ **Task 2.2**: Deny reason that names the exact path that is missing
  and gives two ways out — write the file, or reply without claiming a path —
  because an agent that genuinely reported inline is not at fault and must not
  be pushed into inventing a file to satisfy the guard.
- [ ] ⬜ **Task 2.3**: `get_claude_md()` and `get_acceptance_tests()`, both of
  which the `handler_reference` QA gate requires.

### Phase 3: gate

- [ ] ⬜ **Task 3.1**: `llm_qa format`, README index row and statistics, then
  `llm_qa.py all` green with the daemon restarted after the last `src/` edit.
- [ ] ⬜ **Task 3.2**: Record the outcome on Plan 00422's N15 entry; archive.

## Success Criteria

- [ ] The control corpus of Task 1.1 was observed passing through unblocked —
  a guard that blocks everything would satisfy the positive tests alone.
- [ ] A SubagentStop carrying N15's actual message shape, with no such file on
  disk, is denied and names the path.
- [ ] The same message, with the file present, is allowed.
- [ ] `llm_qa.py all` green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00446-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
