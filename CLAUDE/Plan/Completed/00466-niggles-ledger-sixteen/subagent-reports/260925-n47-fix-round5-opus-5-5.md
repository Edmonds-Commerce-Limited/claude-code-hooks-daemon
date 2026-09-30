# N47 fix round 5 (claude-opus-5-5)

Worktree `agent-ad81ccb71a41cfa91-b9dca8ef`. Started at `26c9db750`. Review 4
was committed as-is at `d7ec91548`. The fixes are in `e8f890217`. Guard tests
from the mutation runs followed in `e19f6d0b2` and `52ccf41a8`, and the
truth-change and this report in the commit after that. Every finding was
fixed test-first. The new tests were run against the unchanged source first,
and 73 failed (`/workspace/untracked/scratch/n47r5_red.out`). The guard tests
that pass on unchanged code are proven RED by mutation (below).

Checks run on the touched files: ruff, black, mypy (strict, 16 files, clean)
and pyright (0 errors). Targeted tests: 1436 plus 119 passed, and the
truth-change manifest tests (125) passed. `llm_qa` passed on docs_qa,
plan_qa, handler_reference, british_english, skill_refs, doc_truth,
doc_snippets, magic_values and generated_doc_drift (9/9, a real run, not
`--read-only`). The daemon was restarted before the `src/` commit and reported
RUNNING. The gate is left to the reviewer.

## One line per finding

| #   | Status | What changed                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0   | FIXED  | The `modelSettings` JSON now lives only in `CLAUDE/development/CcySupervisor.md`, which is durable (a task file moves at release, so a link into `UNRELEASED/` would break). Post-upgrade task 02 names the three entries in prose and points to that section. `docs_qa`: 0 findings (fresh run, not `--read-only`)                                                                                                                                                                      |
| 1   | FIXED  | `tests/unit/supervise/test_no_effort_injection.py` asserts on PAYLOADS that no `/effort` is typed for: Fable at medium/high/xhigh/max; a whole attributed downgrade episode (restore and recovery); a manual pick; the operator `/model` switch; a compaction and its resume; a human-typed `/effort max` through `run_worker`'s raw-input tap. Each scenario also asserts it reached its path. NIGGLES.md no longer cites a probe                                                       |
| 2   | FIXED  | `_check_effort_level` is replaced by `_check_effort_source` ("Effort Source"). It WARNs on `CLAUDE_CODE_EFFORT_LEVEL` (except `auto`/`unset`) and on a top-level `effortLevel` in `.claude/settings.json` or `.claude/settings.local.json`, and on an unreadable one. It never recommends a level. `_run_checks(project_root)`; `cli check` prints `[WARN]`; both `check.md` copies updated. A v3.67.0 truth-change tells anyone who set the env var on `check`'s old advice to unset it |
| 3   | FIXED  | A record explains a drop only if the downgrade it records happened within `_DOWNGRADE_ATTRIBUTION_WINDOW_SECONDS` (300s) of the drop's observation. Retro attribution applies that judgement at the moment the drop was seen, so a record of a LATER downgrade cannot claim a manual pick. A late-published record of the drop itself is still attributed                                                                                                                                |
| 4   | FIXED  | Records carry `record_id`: the transcript `uuid`, else the line's byte offset (tail now read in bytes). A standalone record pairs with the block just before it (same models, within 180s) and keeps the block's id and time. The supervisor spends by id. A keyless legacy record is bounded by the window instead                                                                                                                                                                      |
| 5   | FIXED  | A test per guard, asserting on the `/model` payload or the state it owns. Mutation kill counts are below; the two "retro ignores session/family" guards were replaced by the latch invariant (see the table)                                                                                                                                                                                                                                                                             |
| 6   | FIXED  | `test_model_restore_cap_is_two_per_process` pins the literal: the 2nd restore fires, the 3rd does not (kills 2 -> 99 and 2 -> 1). `test_an_episode_closes_when_the_foreground_session_changes` kills the session-change close gap                                                                                                                                                                                                                                                        |
| 7   | FIXED  | `model_context.py` docstring and default comment (no "enforces high", no "never written to settings.json"); `StatusLine.md:107`; the supervisor's "effort-restore" comments; floor/ceiling wording in task 02, `CcySupervisor.md`, release note 34 and the tasks README. The unused `SidecarReading.effort` field (dead code, and what the comment described) is removed                                                                                                                 |
| 8   | FIXED  | A retro attribution logs `noop: downgrade fable -> opus attributed retroactively (...)`, and a restore on the same tick carries it in its own reason                                                                                                                                                                                                                                                                                                                                     |
| 9   | FIXED  | `OperatorSignals.md` and `HANDLER_REFERENCE.md` state current state. `HANDLER_REFERENCE` says `/effort` saves `low`–`xhigh`, with `max` session-only, and documents the record identity and window. `CcySupervisor.md` now names Opus 5.5 as staying at `medium`                                                                                                                                                                                                                         |

## Design notes a reviewer should check

- **The window applies to every attribution, not only the retro path.** A
  record the supervisor never opened an episode for (the downgrade happened
  while it was not watching) is never spent. Without a window, it would
  attribute a human's pick of the same fallback at any later time. That is
  the same hole as findings 3 and 4, reached without the latch.
- **Retro attribution moved** from `note_machine_downgrade` to a new
  `settle_pending_drop`, which runs after the tick's reading. The record and
  the human's next pick can land between the same two ticks. Before the
  move, the record was judged against the previous tick's family, which
  opened an episode that a later pick of Sonnet never closed. The test
  `test_leaving_the_fallback_on_the_tick_the_record_arrives_opens_nothing`
  and the mutant "N retro settled BEFORE the tick's reading" pin this.
- **Two guards were removed.** "Retro ignores current family" and "retro
  ignores session" checked state that the latch already guarantees: the
  latch exists only while the session is on the fallback. Each is replaced
  by a latch-clearing mutant that is killed.
- **Bounded residuals:**
  - A signal from a daemon that predates `record_id` AND has no timestamp has
    no key. It is bounded only by the window, measured from the moment it was
    first seen.
  - A spent key recorded as a legacy `record_ts` will not match the same
    record once an upgraded daemon republishes it with a uuid. That is
    bounded by the window too: at most 300s after the original downgrade.
- **Hot-reload state keys were renamed** to `*_record_id`. The legacy
  `*_record_ts` keys are still read on import, and that is tested.

## Mutation results at `52ccf41a8`

Harness: `/workspace/untracked/scratch/probe_n47r5_mutate.py`. It builds its
tree from `git archive` of the commit and never touches the worktree. Daemon
mutants run with `PYTHONPATH` set to the tree's `src/`, and the harness checks
that this shadows the venv's editable install. Output:
`probe_n47r5_mutate_final.out`. The baselines were green: supervise 846,
daemon 82, check 82.

**70 of 70 killed. 0 survived, 0 skipped.**

| Group                                        | Count | Result                                                                                                                                                                                                                                                                                                                                                            |
| -------------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Review 4's list (R3, R3b, C, E, H, X, L, Z)  | 28    | All killed. This includes the 9 M4 survivors (finding 5), the cap 2 -> 99 and the session-change close (finding 6), and the DROP ANCHOR and compensation reinstatements (finding 1). The Z mutants read `effort` from the sidecar file itself, because the unused `SidecarReading.effort` field was removed. Mutants whose code was renamed carry "[re-anchored]" |
| Attribution window, retro, identity, log (N) | 19    | All killed: the window removed, one-sided and widened; unknown time; retro judged at arrival; retro before the reading; first sighting reset; the record's own time ignored; export and import of both new times; legacy key import; loader key and UTC; both decision-log lines                                                                                  |
| Daemon record identity (D)                   | 13    | All killed: pairing removed, keeping the refusal's time, unbounded, ignoring models, ignoring shape; the offset counted in characters; the offset not assigned; uuid ignored; `record_id` not in the identity, not written, not read; zone-less time not UTC; recorder drops `record_id`                                                                          |
| Effort source check and cli (K)              | 10    | All killed: auto/unset counted as a pin; env, project and local not checked; unreadable or non-object passes; warn flag dropped; only the first pin reported; cli prints MISS; cli not given the project root                                                                                                                                                     |

The first full run (at `e19f6d0b2`) had 3 survivors. Each was fixed with a
test rather than dropped:

- "No event time means attributed": a legacy state that names a record but
  not its time must attribute nothing.
- "Legacy `*_record_ts` keys not read": the backfill masked it, so the test
  now uses a different published record.
- "Zone-less time not read as UTC": equivalent in a UTC container. Both
  parsers are now tested under `TZ=America/New_York`.

That run also had 2 skipped anchors, which black had reflowed. They were
re-pointed.

**Review 4's own script, re-run as written** (only its tree path changed; the
tree is a `git archive` of `52ccf41a8` in the reviewer's shape; output
`probe_n47r5_reviewer_verbatim.out`): baseline 846 passed. **17 killed, 0
survived, 10 skipped.**

- The 10 skips are anchors on renamed or removed code (`*_record_ts` ->
  `*_record_id`, retro moved to `settle_pending_drop`). Each has a
  re-anchored equivalent above, and all of those are killed.
- Its two Z mutants are "killed" by `AttributeError: 'SidecarReading' object has no attribute 'effort'`, which proves nothing. The harness's
  file-reading Z mutants are what show finding 1 is closed.
