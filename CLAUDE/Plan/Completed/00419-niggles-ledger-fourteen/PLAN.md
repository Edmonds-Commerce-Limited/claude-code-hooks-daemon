# Plan 00419: niggles ledger fourteen

**Status**: Complete
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

Fifteen entries. Full write-ups, with evidence and candidate remedies, are in
[NIGGLES.md](NIGGLES.md); deeper narrative is in
[JOURNAL/00419-Journal-26-09-16.md](JOURNAL/00419-Journal-26-09-16.md). One
line each here so the
ledger's shape is readable without opening it, with the verdict each entry was
given when this ledger closed:

| #   | Verdict                                                                    | Status                                                                                                                                                                             |
| --- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1  | `debug_hooks.sh` could not run in the repository that dogfoods it          | ✅ Fixed — RED first, both defects separately; the fix's own `mapfile` too                                                                                                         |
| N2  | archiving a plan silently breaks every link it makes to a sibling          | ✅ Fixed — RED first, archive-aware link resolver (Task 1.4)                                                                                                                       |
| N3  | the two plan-close gates are mutually exclusive on the legal close path    | ✅ Fixed — RED first, stage move plus a new COMMIT registration (Task 1.5)                                                                                                         |
| N4  | `cron_stop_enforcer` wedged every Stop on the day it merged                | ✅ Fixed — RED first, verified against a captured payload (Task 1.6)                                                                                                               |
| N5  | the goal check counts idle teammates as running work                       | ✅ Determined — the defect is UPSTREAM in Claude Code's own `/goal` evaluator; the local counterpart was built RED-first (Task 1.7)                                                |
| N6  | declaring `layout.source_dirs` disables the TDD file-level exclusions      | ✅ Fixed — RED first, `is_excluded_source_file` (Task 1.8)                                                                                                                         |
| N7  | Black is the formatter of record and nothing stopped `ruff format`         | ✅ Fixed — project handler `ruff_format_blocker`, 20 tests                                                                                                                         |
| N8  | the `Priority` constants are not the numbers a fresh install ships         | ⬜ NOT terminal — remedy owner-gated and unbuilt; graduated to [00422 N1](../00422-niggles-ledger-fifteen/NIGGLES.md)                                                              |
| N9  | worktree creation was dead here, because seeding cannot say "if it exists" | ✅ Fixed — RED first, `SeedEntry.optional`                                                                                                                                         |
| N10 | a handler exception is reported as a configuration question                | ✅ Fixed — RED first, `print_worktree` reports the real reason                                                                                                                     |
| N11 | the linter runs on gitignored scratch output                               | ⬜ NOT terminal — remedy chosen and un-gated, but unbuilt; graduated to [00422 N2](../00422-niggles-ledger-fifteen/NIGGLES.md)                                                     |
| N12 | a committed future-dated entry makes the journal permanently uncorrectable | ⬜ NOT terminal — remedies recorded, none chosen; its advisory is still live against this plan's own day-file; graduated to [00422 N3](../00422-niggles-ledger-fifteen/NIGGLES.md) |
| N13 | a cron cannot be both cancelled for a session and declared in config       | ⬜ NOT terminal — remedy owner-gated and unbuilt; graduated to [00422 N4](../00422-niggles-ledger-fifteen/NIGGLES.md), which names the class it shares with N3 and N12             |
| N14 | the security-downgrade scan descended into linked worktrees                | ✅ Fixed — RED first, commit `2778206f`                                                                                                                                            |
| N15 | an owner gate whose premise had expired ten days before it was filed       | ✅ Determined from the record — the premise was false, F-PRIV-4 is unblocked and the guard is unchanged                                                                            |

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

- [x] ✅ **Task 1.4**: N2's remedy built as UNCONDITIONAL behaviour, per
  [the ruling](fable-niggle-remedies-decision.md); the default-off flag this
  task floated is rejected. `plan_links.py` resolves a link by plan NUMBER
  across the active root and every configured archive dir, only after the
  literal path fails. `pointer-resolves` consumes it and is source-sensitive:
  silent from an archived plan or a `JOURNAL/` day-file, silent from a live
  `PLAN.md` (plan QA owns that one), ADVISE elsewhere — never BLOCK. New
  plan-QA check `plan-link-resolves`, SWEEP-only at ADVISE. `docs_qa` now
  learns the plan dir and archive names from `plan_workflow` config instead of
  hardcoding `CLAUDE/Plan/Completed`; no new config key.

  Clean RED was 6 failed / 222 passed plus 4 collection errors for the
  not-yet-existing modules; GREEN is 5,258 passed across every touched area.

  Verified on the REAL tree, not only fixtures: the shipped resolver replays
  all 8 of N2's recorded dead links out of the archival commit `8b580808` —
  8 resolve, 0 still dead, each with its literal path confirmed absent. A
  whole-repo pass finds 19 relocated links (18 from archived sources, silent
  by doctrine; 1 from a live doc) and leaves 16 genuinely dead links dead.
  Both sweeps still report the real tree clean, so no false positive was
  introduced.

- [x] ✅ **Task 1.6**: N4 fixed, RED first, in
  `tests/unit/utils/test_cron_enforcement_whitespace.py`. Clean RED was 5
  failed / 3 passed — the three that passed are the guards asserting a
  genuinely different prompt, a dropped paragraph and a different schedule
  still do NOT match, which had to pass before AND after, or the fix would
  have traded a false positive for a check that never fires.

  Verified against the captured payload rather than only against fixtures:
  replaying the real `Stop` through `find_missing_crons` now reports nothing
  missing. Daemon restarted with the fix live.

- [x] ✅ **Task 1.5**: N3 — none of the three candidates. The ruling
  (`fable-niggle-remedies-decision.md`) took a fourth option: move the
  `header-body-coherence` COMPLETION finding from BLOCK to ADVISE at EDIT, and
  add a COMMIT registration at BLOCK. The `Not Started`-with-boxes-ticked
  branch is untouched and still blocks at EDIT.

  Not owner-gated after all, because the premise was wrong: this is not a
  relaxation. The all-ticked-under-`In Progress` state is the MANDATORY
  intermediate on the legal close path — the `Edit` tool replaces one
  contiguous span, and the header and the Success Criteria are never one span
  — so both orderings were denied and the only legal move left was a
  whole-file `Write`. A gate no legal sequence of moves can satisfy is a
  defect.

  Net effect is a TIGHTENING: the check had NO commit registration, so a plan
  committed in the violating state reached history unchallenged and waited for
  the next session's sweep. The commit gate is scoped by Plan 00343's rule, so
  a commit is blamed for incoherence it introduces, never for incoherence it
  inherited — pinned by its own test.

  RED first, 9 new tests. The registry catalogue guard caught the third
  registration on its own (`COMMIT` 17→18), which is the guard working.

- [x] ✅ **Task 1.8**: N6 fixed, RED first, in
  `tests/unit/handlers/test_tdd_enforcement.py`. Clean RED was 1 failed / 4
  passed — and the four that passed are the guards that had to hold before AND
  after: a real module under a declared `source_dirs` is still gated, and an
  `__init__.py` under zero-config is still exempt. Without both, the fix could
  have traded a false positive for a gate that never fires.

  `TddStrategy` gains `is_excluded_source_file` — a file-level veto,
  independent of location — consulted ahead of both location rules. Python's
  `is_production_source` now delegates to it rather than re-testing
  `__init__.py`, so the two cannot drift apart; the other ten languages have no
  such file and return False.

  Proven before it was written up, and before it was fixed: the real handler
  was driven directly with only the layout changed between two calls, which is
  what separated "the gate is too strict" from "declaring a layout disables an
  exclusion".

- [x] ✅ **Task 1.7**: N5 — **remedy (1) is UPSTREAM and is not available
  here.** The goal check is Claude Code's OWN `/goal` evaluator, a
  session-scoped prompt-based Stop hook that "skips the evaluation for that
  turn" while a subagent or background shell is running; nothing in this
  repository can teach it that `idle` is not `running`. The owner-gate premise
  ("changes when a stop is allowed") therefore dissolves — **the sole remaining
  owner question is whether to file it with Anthropic**, and nothing was filed.

  Two things WERE built, neither of which touches stop control. Teammate
  reaping is now documented as the counterpart to `worktree-reap`, canonically
  in `CLAUDE/AgentTeam.md` ("Reaping Teammates (`TaskStop`)"), with pointers
  from the Cleanup Phase, the Team Lead Checklist and `CLAUDE/Worktree.md`.

  And the payload shape was ESTABLISHED before a line of handler was written
  (the N4 lesson, applied): the `/goal` evaluator is itself a Stop hook, and its
  `goal_status` records in the session transcript quote the same payload on both
  sides of the reap — seven entries with `status: "running"`, which it itself
  classified as "'teammate' type tasks … not OS processes", then
  `background_tasks: []` once each was `TaskStop`ped. So an idle teammate DOES
  occupy the list. `teammate_reap_advisor` (Stop, priority 9, `terminal=False`)
  reports the count and names `TaskStop`; it is an advisory with no deny path in
  its source at all, silent when the list is absent or empty, and rate-limited
  like `background_process_tracker`. Clean RED was 1 collection error — the 13
  tests could not run because the module did not exist — then 13 passed.

## Success Criteria

- [x] ✅ `scripts/debug_hooks.sh` resolves a socket in this repository, and a
  test fails if the self-install layout stops being found.

- [x] ✅ A missing socket directory produces the script's own readable error,
  not a silent `set -e` death, and the documented env-var escape hatch is
  reachable.

- [x] ✅ **Assessed at close, not before**: every entry judged one by one
  against the terminal states this plan's Goals define — fixed with a RED-first
  test, determined from the record, or graduated to its own numbered plan. The
  verdict per entry is the table above, and **the assessment does not come out
  clean**. Eleven of fifteen are terminal: nine fixed RED-first, and two
  determined from the record (N5, whose defect is upstream in Claude Code's own
  `/goal` evaluator and cannot be fixed here; N15, whose premise was already
  false when the gate was filed). **Four are not, and they are named rather
  than counted** — N8 and N13 are owner-gated with the remedy recorded and
  unbuilt, N11 and N12 have an un-gated remedy nobody built. Counting those
  four as terminal would be the one failure this ledger could not recover from,
  because nothing downstream re-reads a closed plan. They are graduated instead,
  by the house precedent 00413 set: all four are re-filed in full as N1-N4 of
  [00422](../00422-niggles-ledger-fifteen/PLAN.md), which also owns naming the
  class N3/N12/N13 share.

- [x] ✅ **QA and CI**: the full suite ran, its two genuine failures are fixed
  and committed as `2778206f` (a `mypy` re-binding in `daemon/cli.py`, and
  N14's worktree scan), and the daemon was restarted with the fix live. **One
  finding is still open and is not suppressed**: `plan_qa` reports
  `journal-entry-ordering` at ADVISE against this plan's own day-file
  `JOURNAL/00419-Journal-26-09-16.md`. That finding IS N12 — the entries were
  appended with a heredoc, bypassed the future-dated guard at write time, and
  reached history, where the append-only rule makes them uncorrectable. This
  ledger therefore closes carrying a live advisory finding against itself that
  it has itself documented as unfixable, which is the accurate state rather
  than a clean one.

- [x] ✅ **Holding area is current**: every release-bound consequence is in
  `CLAUDE/UPGRADES/UNRELEASED/` — `teammate_reap_advisor` and
  `seed.entries[].optional` in `config-changes/v3.65.0.yaml`; the
  `header-body-coherence` stage move and the new `plan-link-resolves` check in
  `truth-changes/v3.65.0.yaml`; N4's prompt-matching rule inside 00416's
  callout `release-notes/05-declared-crons-are-enforced-at-stop.md`; and this
  plan's own callout
  `release-notes/10-worktrees-layouts-and-diagnostics.md` for the five
  client-visible fixes that had none (N1, N6, N9, N10, N14).

## Delivery & Milestones

- Opened because ledger thirteen closed, by the convention recorded in
  `CLAUDE/Plan/CLAUDE.md`: a niggle is appended to the open ledger, and if none
  is open a new one is scaffolded.

- N14 and the two genuine QA failures this close was gated on landed in
  `2778206f`; the rest of the work is in this session's merges to `main`.

- Closing hands four entries on rather than absorbing them: N8, N11, N12 and
  N13 are unresolved, and are re-filed in full as N1-N4 of
  [00422](../00422-niggles-ledger-fifteen/PLAN.md), each citing the entry here
  that it came from. A rolling ledger ends when it is closed, not when it is
  empty.
