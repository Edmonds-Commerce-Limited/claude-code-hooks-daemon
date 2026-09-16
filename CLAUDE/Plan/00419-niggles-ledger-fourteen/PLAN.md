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
- **N6** — declaring `layout.source_dirs` silently switched off every TDD
  language strategy's file-level exclusions, so a project that describes itself
  carefully lost Python's `__init__.py` exemption. Fixed, RED first.
- **N7** — Black is the formatter of record, Ruff the linter, and nothing stops
  an agent running `ruff format`: an eight-file fix commit went in carrying 163.
  Documented in `CLAUDE/QA.md` and broken anyway, by the author, hours after
  reading it. Remedy owner-gated.
- **N8** — the `Priority` constants are not the numbers a fresh install ships;
  the whole `status_line` template diverges and one segment it references is
  absent from it. Relative order holds, so nothing misbehaves and nothing can
  detect it. Remedy owner-gated.

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

  **The gating premise has a possible dissolution worth deciding on
  explicitly**, by analogy with N7. That niggle was also recorded as
  owner-gated "because it changes the gate surface in every installing
  project", and that stopped being true once the remedy was scoped to a
  PROJECT-level handler — the reasoning was sound, it just described a
  different artefact from the one actually needed.

  The same move is not available here, since a project handler cannot
  override the library's plan-QA link resolution. The equivalent is a
  DEFAULT-OFF config flag: no installing project's `--sweep` behaviour
  changes until it opts in, so the premise that gates this task no longer
  holds. That is a suggestion for the owner to accept or reject, not a
  decision taken — it trades one real cost (a config surface that must be
  documented and can drift out of step with the default) for another.

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

- [ ] ⬜ **Assessed when this ledger closes, not before**: every entry is
  terminal — fixed with a RED-first test, determined from the record, or
  graduated to its own numbered plan. Open while this is the current ledger,
  because a rolling ledger exists to keep collecting.

## Delivery & Milestones

- Opened because ledger thirteen closed, by the convention recorded in
  `CLAUDE/Plan/CLAUDE.md`: a niggle is appended to the open ledger, and if none
  is open a new one is scaffolded.
