# Plan 00242 — Measurements (Task 1.2) and response bounds (Task 3.4)

## Question

Does running EVERY matching handler on the blocked path (collect-all mode)
cost enough that a deny should still short-circuit inside that mode? The
plan's worry: several handlers shell out to git, and today a terminal deny
at priority 10 skips all of them, so running everything could make the
BLOCKED path the slowest path.

## Method

The daemon's real controller, built from this repository's own
`.claude/hooks-daemon.yaml` (every enabled built-in and project handler — 59
PreToolUse handlers registered), dispatching representative PreToolUse
payloads through `DaemonController.process_event()` — the same path the
socket server uses — 200 iterations per cell, wall time per dispatch.
Verdict log disabled; `ClaudeMdInjector.inject` patched out of `initialise()`
so the tracked CLAUDE.md is not rewritten. The script lives in
`untracked/scratch/measure_00242.py` (uncommitted; reproduce by rebuilding
it from the description below) and flips
`controller._chain_config = ChainConfig(collect_all_violations=...)` between
the two modes.

Payloads:

| Label    | Tool  | Input                                                                                           | Expected                                                                            |
| -------- | ----- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| allow    | Bash  | `git status`                                                                                    | no deny (baseline)                                                                  |
| deny x1  | Bash  | `git reset --hard HEAD~1`                                                                       | `destructive_git` denies at priority 10                                             |
| deny x2  | Bash  | `git reset --hard HEAD~1 && pytest tests/ \| tail -5`                                           | `destructive_git` + `pipe_blocker`                                                  |
| deny x3+ | Write | a `src/.../utils/*.py` with `shell=True`, an except-and-swallow, a suppression comment, no test | `error_hiding_blocker`, `security_antipattern`, `qa_suppression`, `tdd_enforcement` |

Hardware: the dogfooding container (Linux 7.1.8, Python 3.11.2, `uv sync --frozen --all-extras` venv).

## Results

| Payload  | Mode          | p50 ms | p95 ms | max ms | matched | executed | denies | reason chars | terminated_by           |
| -------- | ------------- | -----: | -----: | -----: | ------: | -------: | -----: | -----------: | ----------------------- |
| allow    | short-circuit |   0.48 |   0.91 |  49.72 |       1 |        1 |      0 |            0 | —                       |
| allow    | collect-all   |   0.48 |   0.53 |   0.59 |       1 |        1 |      0 |            0 | —                       |
| deny x1  | short-circuit |   0.18 |   0.22 |   0.28 |       1 |        1 |      1 |          265 | prevent-destructive-git |
| deny x1  | collect-all   |   0.60 |   0.65 |   0.83 |       2 |        2 |      1 |          265 | —                       |
| deny x2  | short-circuit |   0.19 |   0.21 |   0.27 |       1 |        1 |      1 |          265 | prevent-destructive-git |
| deny x2  | collect-all   |   1.15 |   1.24 |   1.69 |       3 |        3 |      2 |          576 | —                       |
| deny x3+ | short-circuit |   0.34 |   0.40 |  13.91 |       1 |        1 |      1 |          588 | error-hiding-blocker    |
| deny x3+ | collect-all   |   2.03 |   2.49 |   4.09 |       4 |        4 |      4 |         3048 | —                       |

(The 49.72 ms and 13.91 ms maxima are first-iteration warm-ups — lazy imports
and the first git fork — not steady state; the p95 column is the operative
one.)

## Reading

- The blocked path in collect-all mode costs **~2 ms p50 / 2.5 ms p95** on
  the worst measured case (four denies from four content scanners over the
  same Write), against **0.34 ms** short-circuited. That is a 6x relative
  increase and a ~2 ms absolute one.
- `CLAUDE/Performance/README.md`'s Rule 0 puts the per-event budget at ~100
  ms p95 and the daemon-side baseline at ~1.8 ms of a ~45 ms end-to-end
  PreToolUse event (the rest is forwarder process spawns). Collect-all's
  worst case stays inside the daemon-side baseline and is ~5% of the
  end-to-end event.
- The git-forking handlers the plan worried about (`daemon_restart_verifier`,
  `git_upstream_checker`-style probes) did not show up: `matches()` filters
  them off these payloads, and the only Bash-wide advisory that ran
  (`bash_safe_mode`, priority 30) costs ~0.4 ms.
- The allowed path is unchanged (0.48 ms in both modes), as expected: the
  flag only changes what happens after a deny.

## Decision (Task 1.2: "decide from data")

**A deny does NOT need to short-circuit in collect-all mode.** The measured
cost of running every matching handler after a deny is under the noise floor
of the forwarder spawns that dominate the event. Collect-all runs the whole
chain; the only short-circuit it keeps is the PermissionRequest
`allow_is_final` opt-in, which is semantic, not a cost saving.

The default mode keeps the terminal-deny short-circuit anyway — not for
cost, but because the merged response is a behaviour change existing
projects should opt into (the plan's own risk table: "ship behind a config
flag first, default off, then flip").

## Response bounds (Task 3.4)

Three full deny reasons concatenated would be unreadable (sed_blocker's
alone runs to ~5 KB). `core/chain.py` bounds the merged reason:

| Bound                                | Value | Rationale                                                                                         |
| ------------------------------------ | ----: | ------------------------------------------------------------------------------------------------- |
| `COLLECT_ALL_MAX_EXTRA_DENIES`       |     4 | Beyond the lead, four full excerpts; further deniers are still NAMED so nothing is silent         |
| `COLLECT_ALL_DENY_EXCERPT_CHARS`     |  1500 | Long enough for a verbose first-fire rule message; marks the cut with the dropped character count |
| `COLLECT_ALL_MAX_ADVISORY_ROWS`      |     8 | One table row per advisory handler; the rest are counted and named                                |
| `COLLECT_ALL_ADVISORY_EXCERPT_CHARS` |   160 | First non-empty line of the advisory, cell-safe; full text still travels as `additionalContext`   |

Worst case beyond the lead deny: 4 x 1500 + 8 x 160 + framing, a little
under 8 KB — the same order as a single verbose deny today. The lead deny is
never cut: it is the highest-priority violation and owns the `To disable:`
footer.

The measured 3048-character reason for the four-deny Write is the merged
report: the lead (588 chars) plus three excerpts plus the footer.
