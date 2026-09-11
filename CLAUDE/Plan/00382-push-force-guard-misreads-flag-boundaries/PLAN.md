# Plan 00382: push force guard misreads flag boundaries

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**GitHub Issue**: #37

## Overview

A user reported that `destructive_git` denies an ordinary push when the branch
name contains `-f-`, e.g.
`git push origin feature/lane-f-adoption`. The report is exact, including the
cause: the `-f` alternative in `_GIT_PUSH_FORCE_PATTERN` carries a trailing
`\b` but no leading boundary, so the `f` in `lane-f-adoption` is followed by a
`-` and that counts as a word boundary. The `+`-refspec alternative beside it
already guards its leading position with `(?<!\S)`; the flag alternative never
did.

**Reproducing it turned up a second, opposite defect the report does not
mention, and it is the more serious one.** Grouped short flags evade the guard
completely: `git push -uf origin main`, `-fu` and `-nf` are all real force
pushes that are ALLOWED today, because the literal substring `-f` never appears
in `-uf` or `-nf`, and in `-fu` the `f` is followed by a word character so the
trailing `\b` fails. `git push -nq <remote>` was accepted by git's own option
parser — failing on the remote, not on an unknown switch — which confirms git
groups short options on `push`.

So the guard is wrong in both directions, and the fix suggested in the issue
(`(?<!\S)` in front of the whole flag group) closes the false positives while
leaving all three false negatives open. Measured against 14 cases: current 6
wrong, suggested 3 wrong, proposed 0.

The shape that works separates the two flag syntaxes, because they have
different rules. A LONG option is forceful only when it is exactly `--force`
or `--force-with-lease`. A SHORT cluster is any single-dash token containing
`f`, whatever else rides along with it.

## Goals

- An ordinary push of a branch whose name contains `-f-` is allowed.
- A grouped short flag carrying `f` is denied.
- Every force spelling that is denied today stays denied.

## Non-Goals

- Widening the guard to other subcommands. This pattern is scoped to the
  `git push` segment and stays so.
- Treating `--force-if-includes` as non-forceful. It matches today and keeps
  matching; it appears only alongside a real force flag, so the verdict is
  unchanged either way.

## Tasks

### Phase 1: Reproduce before fixing

- [x] ✅ **Task 1.1**: A failing test for each reported false positive —
  `feature/lane-f-adoption`, `fix-f-test`, and the `--set-upstream` form.
- [x] ✅ **Task 1.2**: A failing test for each grouped-short-flag false
  negative — `-uf`, `-fu`, `-nf`. These are the ones the report misses, and a
  guard that misses a destructive command is worse than one that over-matches.

### Phase 2: One pattern, both directions

- [x] ✅ **Task 2.1**: Split the flag alternatives by syntax: `(?<!\S)--force`
  `(?:-with-lease)?\b` for long options, and
  `(?<!\S)-(?!-)[A-Za-z0-9]*f[A-Za-z0-9]*\b` for a short cluster.
- [x] ✅ **Task 2.2**: Pin the near-misses the new shape must NOT match:
  `--follow-tags` and `--no-force-with-lease`. Both were ALREADY allowed — I
  assumed the latter was denied and checked instead of asserting it; the
  literal `--force` never occurs in `--no-force-with-lease`. The tests record
  correct existing behaviour so the new leading guard cannot regress it.

### Phase 3: Say so

- [x] ✅ **Task 3.1**: The handler's `get_claude_md()` describes the three
  spellings that qualify. Add grouped short flags, since an agent reading it
  would otherwise believe `-uf` is not covered.
- [ ] ⬜ **Task 3.2**: Release note, and close #37 with a summary that names
  the second defect the reporter did not know about.

## Success Criteria

- [ ] `git push origin feature/lane-f-adoption` is allowed.
- [ ] `git push -uf origin main` is denied.
- [ ] Every spelling denied before this plan is still denied.
- [ ] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/<file>.md`.
- [ ] Full QA passes and CI is green.
- [ ] Issue #37 is closed with an implementation summary.

## Delivery & Milestones

- Reported as GitHub issue #37 against daemon 3.63.0, with an accurate
  diagnosis and a suggested fix that this plan extends rather than adopts.
