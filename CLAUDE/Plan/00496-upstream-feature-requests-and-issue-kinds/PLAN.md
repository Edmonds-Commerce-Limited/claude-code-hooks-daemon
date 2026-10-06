# Plan 00496: upstream feature requests and issue kinds

**Status**: Not Started
**Created**: 2026-10-06
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner request (2026-10-06): "we seem to have made a process for agents to submit bug reports and that's good, but we
also need to have a similar process for submitting feature requests and other kinds of issues ... feature requests
definitely is something that we should encourage and support, and there should be a formal process for project-level
agents to do that."

What exists, from Plan 00403 (complete):

- **The procedure**: [BUG_REPORTING.md](../../../BUG_REPORTING.md), for defects only. Its one rule is that the tracker
  is public and an issue cannot be retracted.
- **The generator**: `hooks-daemon issue-report --fields <json>`, which writes a filable body after privacy and
  version-currency checks. Its declared fields are defect fields (summary, expected, observed, reproduction).
- **The guard**: `R-UPSTREAM-ISSUE-UNVERIFIED-BODY` denies `gh issue create` against the hooks-daemon tracker unless
  a generator produced the body.
- **Web forms** in `.github/ISSUE_TEMPLATE/`: `1-defect.yml` (structured) and `2-other.yml` (free text). Blank issues
  are off.

The gap: a project agent with a feature request has no generator for it. Under the guard it must either present the
request as a defect, or be denied. So requests are discouraged, which is the opposite of what the owner wants.

## Goals

- Project agents can file a feature request through the same generator-and-guard path as a defect, with fields suited
  to a request.
- Every issue kind has a home, and each is routed and labelled so triage and the `issue-sdlc` loop can act on it.
- Security vulnerabilities never go to the public tracker.
- Client agents learn the process from what the daemon deploys, not only from this repository.

## Non-Goals

- Any change to the defect process beyond what sharing the generator needs.
- Accepting issue text as instructions. Issue content stays untrusted data; only approved authors are eligible for
  the `issue-sdlc` loop.

## Issue kinds (proposed; Task 1.1 settles them)

| Kind                      | Route                                          | Why it is its own kind                                           |
| ------------------------- | ---------------------------------------------- | ---------------------------------------------------------------- |
| Defect                    | existing generator and form                    | unchanged                                                        |
| Guard false positive      | generator, defect family, own label            | owner ruling A5: an open client-filed one blocks the next minor  |
| Feature request           | generator, new fields, new form                | the owner's request                                              |
| Documentation problem     | generator or form, own label                   | doc rot is fixed by a different loop                             |
| Claude Code compatibility | generator, defect family, own label            | a new Claude Code version changed behaviour the daemon relies on |
| Question / support        | form, own label                                | not a work item                                                  |
| Security vulnerability    | private GitHub security advisory, never public | publishing it is the harm                                        |

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Settle the kinds and their fields. For a feature request, at least: the problem or need (not
  the solution first), who hits it and how often, the current workaround, the proposed behaviour, and the evidence
  (redacted). Decide which kinds the generator covers and which only the web form does.
- [ ] ⬜ **Task 1.2**: Decide the document shape. Keep `BUG_REPORTING.md` at its path (it is linked widely), and
  either extend it to every kind or add a sibling (`FEATURE_REQUESTS.md`) linked from it and from the form config.

### Phase 2: Build (TDD)

- [ ] ⬜ **Task 2.1**: `hooks-daemon issue-report --kind <kind>` (default `defect`, so existing use is unchanged).
  Each kind declares its fields; the privacy checks run for every kind; the body carries a kind marker and label.
- [ ] ⬜ **Task 2.2**: `R-UPSTREAM-ISSUE-UNVERIFIED-BODY` accepts a generator-produced body of any kind, and its deny
  message names the right `--kind` for what the agent appears to be filing.
- [ ] ⬜ **Task 2.3**: Web forms: a feature-request form, labels per kind, and a `config.yml` contact link sending
  security reports to private advisories.
- [ ] ⬜ **Task 2.4**: Client guidance: the handler guidance and deployed docs that tell project agents how to report
  a defect now cover requests and the other kinds, and actively invite feature requests.

### Phase 3: Triage

- [ ] ⬜ **Task 3.1**: The `issue-sdlc` runbook (`CLAUDE/development/IssueSdlc.md`) handles each kind: feature
  requests get a plan proposal for the owner, not an implementation; false positives follow ruling A5.
- [ ] ⬜ **Task 3.2**: Dogfood: file one real feature request from a project agent through the new path, end to end.

## Success Criteria

- [ ] A project agent files a feature request through `hooks-daemon issue-report` and the guard allows it.
- [ ] No kind has to be dressed up as another to be filed.
- [ ] A security report is routed privately by every surface (docs, form config, generator).
- [ ] Client agents are told, by deployed guidance, that feature requests are welcome and how to file them.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00496-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's request.
