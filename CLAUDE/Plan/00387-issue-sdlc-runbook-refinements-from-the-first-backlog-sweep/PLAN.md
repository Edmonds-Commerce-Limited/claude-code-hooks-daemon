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

- [x] ✅ **Task 1.5**: Audited every command, path and label the runbook names,
  because a runbook that cites a wrong command fails at the worst possible
  moment and nothing else in QA checks prose for that.
  `scripts/setup_worktree.sh`, `scripts/qa/llm_qa.py`, `CLAUDE/Plan/mkplan.bash`,
  `CLAUDE/Worktree.md` and `CLAUDE/UPGRADES/UNRELEASED/release-notes/` all
  resolve; `hooks-daemon worktree-reap` is a real subcommand (`--help` exits 0);
  and all three labels — `agent-triaged`, `agent-working`, `agent-needs-human` —
  exist on the repository.

- [x] ✅ **Task 1.6**: Specified the stale-`agent-working` recovery path
  concretely, because it is the one path in this runbook with NO field evidence
  — Plan 00384's journal recorded that it is written and has never fired. "Re-verify
  the state from git" was an invitation to guess, so it is now four ordered
  questions with the exact command for each and a defined action per answer:
  already landed → jump to Step 8; branch with unlanded commits → resume at QA;
  bare worktree → reap and restart Step 4; nothing → re-triage.
  Writing it found a defect in my own first draft. `git log --grep "#<N>"` was
  stated as the landed-or-not test; run against this repo's history for #34 it
  returns the real merge PLUS two commits that only mention the issue in passing,
  so a recovery tick could have read a mention as "already merged" and closed an
  unfixed issue. The test is now `git merge-base --is-ancestor`, verified to
  answer correctly in both directions, and deliberately the same test Step 8 uses
  — a recovery tick and a closing tick must not disagree about what merged means.

- [x] ✅ **Task 1.7**: Read the whole runbook end-to-end as a reader would,
  which is the only way to catch what piecemeal edits break. Two defects found,
  neither visible from any single edit:
  the section heading still said "Four checks before classifying" after two more
  were added — a skimming reader would have stopped at four, so it now says Six
  and carries an explicit instruction to renumber;
  and Steps 3 and 4 both tell you to dispatch a sub-agent without declaring
  where its output goes. `dispatch_declaration` advised on this loop's own scout
  dispatch today, which then needed a follow-up message to repair. Both steps now
  declare it — `untracked/agent-reports/` for the scout, since no plan folder
  exists yet, and `<plan-folder>/subagent-reports/` for the implementation agent,
  where one does. The reason is recorded too: an oversized inline report is
  silently elided by the return channel, so the omission can truncate evidence
  rather than merely look untidy.

## Success Criteria

- [x] Every addition names the issue that produced it — checks 5 and 6 cite #36
  and #38, the publishing caution cites #36, and the CI caution cites the
  in-session misread.
- [x] The loop's bounds are unchanged: one issue per tick, stops at merged.
- [x] Every command, path and label the runbook names resolves — audited in
  Task 1.5 rather than assumed, since no QA check reads prose for stale commands.
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
