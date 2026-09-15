# Plan 00419: niggles ledger fourteen

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger thirteen
([00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md)) closed with all
seventeen entries terminal, so this is the open one.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

Full write-ups, with evidence and candidate remedies, are in
[NIGGLES.md](NIGGLES.md). One line each here so the ledger's shape is readable
without opening it:

- **N1** — `debug_hooks.sh` could not run in the repository that dogfoods it.
  Fixed; the fix then introduced a bash-4-only `mapfile`, also fixed.
- **N2** — archiving a plan breaks every link it makes to a sibling. Fork
  closed by constraint: a journal cannot accept repointing, so the resolver is
  the only remedy left. Remedy owner-gated.
- **N3** — the two plan-close gates are mutually exclusive on the legal close
  path. Three occurrences in one session. Remedy owner-gated.
- **N4** — `cron_stop_enforcer` wedged every Stop on the day it merged, because
  the delivered cron prompt is re-rendered and matching compared bytes. Fixed,
  RED first, verified against a captured payload.
- **N5** — the supervisor's goal check counts idle teammates as running work,
  so a session that correctly harvests its parallel work cannot satisfy its own
  stop condition. Remedy owner-gated.

## Tasks

- [x] ✅ **Task 1.1**: N1 — RED first, both defects tested separately, in
  `tests/unit/scripts/test_debug_hooks_socket_discovery.py`. Clean RED was 4
  failed / 3 passed: the client-install case PASSED from the start, which is the
  point of separating them — a single test would have conflated "wrong layout"
  with "dies on a missing directory" and a fix for either could have looked
  complete.

  The tests extract the script's own discovery block and run it in a real
  `bash`, because the defect lives in shell semantics (`set -e` + `pipefail` +
  command substitution) that no Python-level assertion can observe. One guard
  pins that the fix does not reach for `|| true`.

- [x] ✅ **Task 1.2**: N1 fixed. Both layouts are searched in order, each
  directory tested with `-d` before it is searched, and a `read` loop over a
  process substitution replaces `find | head -n1` — which also removes a latent
  SIGPIPE in the producer when the reader closes early. The first version of
  this fix used `mapfile`, which is bash 4+ and broke this project's own macOS
  `/bin/bash` 3.2.57 portability gate; caught by the full QA run on merged main,
  not by the targeted tests, because the portability check is a separate sweep
  over shell scripts. Fixing one defect inside a block is exactly when the next
  one gets introduced. The
  `CLAUDE_HOOKS_SOCKET_PATH` fallback is now reachable, and the not-found error
  names both searched locations instead of only the one that does not exist
  here.

  Proved on the real repository, not only in tests: discovery resolves
  `/workspace/untracked/daemon-*.sock`. Before the fix it produced nothing and
  exited silently. `bash -n` and `shellcheck -x` both clean.

- [x] ✅ **Task 1.3**: N2 — the eight links 00413's archival broke are
  repointed (`../` to `../../` in `PLAN.md` and `NIGGLES.md`), and each verified
  to resolve on disk rather than by eye.

- [ ] ⬜ **Task 1.4**: N2's remedy — build the resolver that knows a plan may
  have moved to `Completed/`. The fork this task was opened to decide is now
  settled by constraint rather than preference (see N2's new evidence): a
  journal link cannot be repointed without violating append-only, so
  "repoint at archival time" is not available. Still owner-gated, because it
  changes what `--sweep` blocks on across every project.

- [x] ✅ **Task 1.6**: N4 fixed, RED first, in
  `tests/unit/utils/test_cron_enforcement_whitespace.py`. Clean RED was 5
  failed / 3 passed — the three that passed are the guards asserting a
  genuinely different prompt, a dropped paragraph and a different schedule
  still do NOT match, which had to pass before AND after, or the fix would
  have traded a false positive for a check that never fires.

  Verified against the captured payload rather than only against fixtures:
  replaying the real `Stop` through `find_missing_crons` now reports nothing
  missing. Daemon restarted with the fix live.

- [ ] ⬜ **Task 1.5**: N3 — choose between the three candidate remedies and
  build it. Owner-gated: (1) and (2) both relax a gate that currently blocks,
  and relaxing a correct gate to fix a sequencing problem is the kind of change
  that should be asked for rather than assumed.

- [ ] ⬜ **Task 1.7**: N5 — decide between teaching the goal check that `idle`
  is not `running` (the fix) and documenting teammate reaping as the
  counterpart to `worktree-reap` (worth doing regardless). Owner-gated: the
  first changes when a stop is allowed, which is a safety control.

## Success Criteria

- [x] ✅ `scripts/debug_hooks.sh` resolves a socket in this repository, and a
  test fails if the self-install layout stops being found.

- [x] ✅ A missing socket directory produces the script's own readable error,
  not a silent `set -e` death, and the documented env-var escape hatch is
  reachable.

- [ ] ⬜ **Assessed when this ledger closes, not before**: every entry is
  terminal — fixed with a RED-first test, determined from the record, or
  graduated to its own numbered plan. Open while this is the current ledger,
  because a rolling ledger exists to keep collecting.

## Delivery & Milestones

- Opened because ledger thirteen closed, by the convention recorded in
  `CLAUDE/Plan/CLAUDE.md`: a niggle is appended to the open ledger, and if none
  is open a new one is scaffolded.
