# Plan 00387: issue sdlc runbook refinements from the first backlog sweep

**Status**: In Progress
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

The owner asked for the issue-SDLC loop to be checked carefully and fine-tuned.
Plan 00384 built it and dogfooded it on one issue end-to-end. This plan records
what the FIRST full sweep of the backlog taught, and folds it back into
`CLAUDE/development/IssueSdlc.md`.

The sweep ran the loop over every untriaged issue — #27, #28, #36, #38 — and
closed three as already-fixed plus filing one plan. Three of four were already
fixed, which says something useful on its own: on a backlog that has aged, the
dominant outcome is not "implement" but "prove it is already done and say so
with evidence". The runbook's triage checks carried that load, and the four
additions below are the gaps that sweep exposed.

Every refinement traces to a specific issue. None is a tidy-up.

## Goals

- Each lesson from the sweep is in the runbook, attributed to the issue that
  produced it, so a later reader can tell refinement from taste.

## Non-Goals

- Re-litigating the triage outcomes. The classifications stand.
- Broadening the loop's remit. It still handles exactly one issue per tick and
  still stops at "merged to the default branch".

## Tasks

### Phase 1: Fold the sweep's findings into the runbook

- [x] ✅ **Task 1.1**: Triage check 5 — a plan may have been filed FROM the
  issue and never linked back. #36 was filed at `16:25:38` and fixed at
  `16:43:34` the same day by a plan that recorded its origin as "the field
  report" with no number. Eighteen minutes to fix, three days of silence. The
  check tells you to search the git log around the issue's timestamp, and to
  retro-fit `**GitHub Issue**: #N` so the next sweep does not re-derive it.
- [x] ✅ **Task 1.2**: Triage check 6 — verify the reporter's stated BLOCKER,
  not only their suggested fix. #38 concluded no tracked version marker existed,
  having grepped for the wrong spelling; the marker and a parser for it both
  already shipped. A wrong blocker is more expensive than a wrong fix because it
  inflates the apparent size of the work.
- [x] ✅ **Task 1.3**: A publishing caution in the triage-comment step. Quoting
  a concrete vendor path out of #36's body was denied by `sensitive_content` —
  the guard checks what the loop PUBLISHES even though it never saw what the
  reporter filed, and this repository is public. Describe the shape instead.
- [x] ✅ **Task 1.4**: Step 8 now says to read the RUN's conclusion rather than
  the watcher's exit code. A `timeout … gh run watch` that expires exits 124, and
  in a chain the chain reports the last command's status — which read an
  `in_progress` run as green during this very sweep. Same failure shape as the
  `QA_EXIT` trap already documented in Step 5, so it is stated as such.

## Success Criteria

- [x] Every addition names the issue that produced it — checks 5 and 6 cite #36
  and #38, the publishing caution cites #36, and the CI caution cites the
  in-session misread.
- [x] The loop's bounds are unchanged: one issue per tick, stops at merged.
- [x] No release-bound consequence — `CLAUDE/development/IssueSdlc.md` is a
  repo-internal contributor document and ships to no client.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Requested by the owner as part of "check it carefully and fine tune the cron
  process".
- Successor in spirit to Plan 00384, which built the loop; this plan is what
  running it against a real backlog taught.
- Sweep outcomes: #27, #28, #36 closed as already-fixed with evidence re-verified
  against `main`; #38 filed as Plan 00386 and labelled `agent-needs-human`.
