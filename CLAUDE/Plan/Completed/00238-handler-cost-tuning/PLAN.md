# Plan 00238: Handler Cost Tuning

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

[Plan 00234](../00234-handler-value-audit/PLAN.md) Task 4.8 — "Follow-up H",
the last of its eight proposals and the one it ranked lowest-urgency. Every
handler here is WANTED and does its job; the finding is that several pay a cost
far above what their duty requires, and in two cases the cost is an accident of
one constant sitting on the wrong side of a threshold.

This is deliberately NOT a removal plan. Plan 00237 removed the handlers that
earned removal; these five earned a verdict of FIX or SUSPECT, which means the
behaviour stays and the cost changes. A tuning change that alters observable
behaviour has failed, and each task below names what must stay identical.

The headline is `git_branch`, and it is worth stating precisely because it is
counter-intuitive: its render-TTL cache is not weak, it is RESONANT. The TTL is
2.0s and the measured render interval is ~1.15s. Because `1.15 < 2.0 < 2.30`,
every render alternates hit, miss, hit, miss — an exact 50% miss rate, forever,
by construction rather than by chance. A cache that looks like it is working is
halving a cost it could nearly eliminate.

## Goals

- Cut the status line's measured subprocess and file-I/O rate without changing
  a single rendered character in the steady state
- Fix the two resonance defects (`git_branch` render TTL, `supervisor_indicator`
  negative-cache TTL) by choosing constants RELATIVE to the render interval
  rather than as absolute seconds that silently drift into resonance
- Give `git_context_injector` and `daemon_restart_verifier` the change-detection
  and rate-limiting their FIX verdicts call for, without weakening either duty
- Leave behind a way to NOTICE resonance, not just this instance of it

## Non-Goals

- Removing or disabling any handler in this plan — all five are wanted
- Re-litigating Plan 00234's verdicts; only a measurement that contradicts one
- Changing what the status line DISPLAYS (a tuning change that alters output is
  a bug, not a tuning)
- A general caching framework — YAGNI; `settings_reader.py` already
  demonstrates the mtime-gate pattern in this exact directory

## Context & Background

Measured evidence is in Plan 00234's
[RESEARCH-F-statusline.md](../00234-handler-value-audit/RESEARCH-F-statusline.md)
and [VERDICTS.md](../00234-handler-value-audit/VERDICTS.md). Live numbers, from
a 65-minute window: ~3,130 renders/hour, ~1.15s render interval.

| Handler                   | Verdict | Measured cost                                                                                                             |
| ------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------- |
| `git_branch`              | SUSPECT | ~50% TTL miss ⇒ **~6,200 git subprocess spawns/hour** — the largest single source in the whole chain                      |
| `supervisor_indicator`    | SUSPECT | full `/proc` walk on a negative-cache miss; 5s TTL vs 1.15s renders ⇒ a walk every ~4–5 renders for a project WITHOUT ccy |
| `account_display`         | SUSPECT | 1 uncached read + regex **every render, forever** — the only file-reading handler in the cohort with no cache of any kind |
| `git_context_injector`    | FIX     | ~460-token minimum payload on **every** prompt, zero change-detection                                                     |
| `daemon_restart_verifier` | FIX     | the same paragraph reaches context three ways on **every** commit, no rate limit                                          |

Two things the research found that this plan must respect:

1. **This repo does not feel `supervisor_indicator`'s cost.** ccy is armed
   here, so the positive cache holds and the `/proc` walk is not paid on the
   measured renders. The cost is real for projects that never run the
   supervisor — which is most of them. Measuring locally will show nothing; the
   fix must be verified against a forced negative-cache path.
2. **`account_display` is not alone.** The research names four handlers with
   the same uncached-read-every-render shape: `account_display`,
   `upgrade_notifier`, `startup_cleanup`, and (bounded by small N)
   `multithread_indicator` — collectively ~9,000–12,500 avoidable file
   operations/hour. Follow-up H named only the first. Fixing one and leaving
   three is the "95 instances by hand" failure DBF exists to prevent.

## Tasks

### Phase 1: Establish the baseline before changing anything

- [x] ✅ **Task 1.1**: Measured by polling the context-sidecar mtime (written
  once per render): 86 renders in 90s — min 0.939s, **median 1.039s**, max
  1.833s. Close to the research's ~1.15s but not equal, and the TTL derivation
  depends on it
- [x] ✅ **Task 1.2**: Baseline via a `git` shim on the DAEMON's PATH only,
  counting real spawns rather than modelling them: **115 renders, 192 spawns,
  57 misses = 49.6% — ~5,760 spawns/hour**. Note the instrument had to be
  rebuilt: Plan 00236's Follow-up A stopped recording status events, so the
  verdict log Plan 00234 measured with is no longer available (JOURNAL 04:20)

### Phase 2: The two resonance defects

- [x] ✅ **Task 2.1**: `git_branch` — TTL is now `round(5 × 1.043, 1) = 5.2s`,
  DERIVED in source from the measured interval with a test asserting the value
  equals the arithmetic, so it cannot drift back to a round guess. Re-measured
  with the identical method: **116 renders, 84 spawns, 26 misses = 22.4%,
  ~2,520 spawns/hour — 57% fewer** (JOURNAL 04:20)
- [x] ✅ **Task 2.1b**: Cut the calls per miss, not just the misses. Two of the
  four were avoidable at ZERO staleness cost: `_resolve_repo_toplevel` memoises
  per cwd (positive answers only, so a later `git init` is still seen), and
  `_run_status` runs the status call ONCE to serve both the icons and the
  branch name — `# branch.head` was already in that output, so
  `branch --show-current` was asking git a question it had just answered.
  `_parse_branch_head` maps `(detached)` to `""` so the no-branch path is
  reached identically. **Measured with Task 1.2's instrument: 112 renders, 44
  spawns — 22 `status`, 22 `stash list`, and nothing else.** Exactly 2 per
  miss, ~1,320 spawns/hour, so **192 → 44 = 77% below the original baseline**.
  One behaviour subtlety worth its own line: the branch name now comes out of
  the status output, so a status timeout would have blanked the whole segment.
  That is a display change, not a cost saving, so a fallback
  `branch --show-current` runs ONLY on that failure path and the degraded
  render is unchanged. **Correction to an earlier note here**: it was never 62
  tests pinned to ordered `side_effect` lists — that was the file's total test
  count. The real surface was 9 inline lists plus two helpers
- [x] ✅ **Task 2.2**: `supervisor_indicator` — the /proc walk is now throttled
  SEPARATELY from the negative cache (`_PROC_WALK_INTERVAL_SECONDS = 60`), and
  both clear points that must force a replacement scan clear it too. **The
  premise above was wrong and the guard from Task 2.3 is what settled it**: at
  the measured 1.043s interval a 5s TTL serves `ceil(5/1.043) = 5` renders per
  miss, above the resonance bar of 3 — so the TTL was never the defect. The
  cost is the WALK, measured at ~20µs per pid (17-pid container; ~10ms on a
  500-process desktop), repeated every ~5s forever ⇒ **~360,000 `/proc` reads
  an hour** on a project that will never run the supervisor. Splitting the two
  keeps the cheap precise detector (the status file, which a normally-started
  supervisor writes) at the 5s rate while the expensive fallback drops 12-fold;
  only a supervisor that never wrote a status file now waits up to a minute
- [x] ✅ **Task 2.3**: DBF — `tests/unit/handlers/status_line/test_render_ttl_resonance.py`
  fails when a render-path TTL sits in the resonance band. **The first version
  would have PASSED the 2.0s value it was written to catch**: it measured
  against the FASTEST interval, but a longer interval is the worse case for a
  fixed TTL. Caught only by running the anti-vacuity check (feed it the pre-fix
  value, confirm rejection) instead of shipping a green test. Rebased on the
  median, with the trap itself pinned as a test so a future "simplification"
  back to the minimum fails and explains why (JOURNAL 04:20)

### Phase 3: The uncached-read family

- [x] ✅ **Task 3.1**: `account_display` is gated. The pattern was EXTRACTED
  from `settings_reader.py` into `mtime_cache.py` rather than copied, and
  `settings_reader` became its first caller — four copies of a gate is four
  places to fix one bug. Its old tests mocked `Path.exists`/`read_text`, so
  they pinned a call shape and broke on a change that altered no output; they
  now drive a real file under a fake home and pin the OUTPUT instead
- [x] ✅ **Task 3.2**: All four siblings resolved. `upgrade_notifier` and
  `startup_cleanup` gated (the latter also stops a valid-JSON-but-not-an-object
  document raising `AttributeError` straight through a guard that only caught
  `OSError/JSONDecodeError/KeyError`). `multithread_indicator` — **the gate
  cannot apply**: it writes its own heartbeat into the registry immediately
  before reading it, so the directory mtime has always just moved and every
  render would miss; its read is bounded by live-session count, not render
  rate. DBF: `test_no_ungated_render_reads.py` now fails for ANY status-line
  module reading a file directly, so a fifth instance cannot appear silently.
  Its allowlist carries the three justified readers with reasons, and a
  companion test fails if an entry stops reading (a stale licence)
- [x] ✅ **Task 3.3**: Rendered output verified against the live daemon before
  and after the restart. The `👤` segment this plan changed is byte-identical;
  `🧹` and `📦` render nothing in both captures, with their positive paths
  pinned by unit test. Only `daemon_stats` differs, and only because the
  restart reset its own uptime counter

### Phase 4: The two FIX verdicts off the status line

- [x] ✅ **Task 4.1**: `git_context_injector` injects only on CHANGE.
  **"Changed" means: the rendered payload differs from the one THIS SESSION
  last received.** Two guards stop that definition becoming too strict, and
  both are pinned by test. It is keyed by `session_id`, because sessions share
  one daemon (Plan 00127) and a global "last payload" would let whichever
  session prompted first mute the others. And suppression expires after
  `_MAX_SUPPRESSION_SECONDS` (900s), because a compaction can evict the earlier
  injection — without a ceiling the agent would have no git context until the
  repository happened to change, which is exactly the silent-stop failure this
  task was warned about. Per-session state is capped at 32 entries,
  oldest-evicted
- [x] ✅ **Task 4.2**: `daemon_restart_verifier` — the three routes named, then
  the redundant one deleted rather than throttled. (1) `get_claude_md()` keeps
  the commands, rationale and 5-handler anecdote RESIDENT in CLAUDE.md for the
  whole session; (2) a one-line `context` nudge fires per commit; (3) a
  multi-paragraph `guidance` block restated (1) almost verbatim, per commit.
  The right rate limit for (3) is not "say the long version less often" but
  "say it once, where it already lives", so `handle()` now returns the single
  line and nothing else. An anti-vacuity test asserts the full instructions
  still exist in the resident guidance, since deleting the per-commit copy is
  only correct while the first copy is there to point at

### Phase 5: Verification

- [x] ✅ **Task 5.1**: Re-measured where each change actually lands, rather than
  re-running one instrument that cannot see three of the four. Git spawns:
  **192 → 84 per ~116 renders (57% down)**, by Task 1.2's method — and unchanged
  since, because nothing after Task 2.1 touches git (Task 2.1b, which would,
  is deliberately still open). File reads: pinned by test at ONE per change
  instead of one per render, across three handlers. The `/proc` walk: measured
  at ~20µs per pid and now run 12× less often. Per-prompt tokens: an unchanged
  ~460-token payload is no longer re-sent, and a duplicated per-commit
  paragraph is gone
- [x] ✅ **Task 5.2**: Full QA — 21/21 PASSED
- [x] ✅ **Task 5.3**: Daemon restarts RUNNING; the rendered line verified
  byte-identical for every segment this plan touched (Task 3.3)
- [x] ✅ **Task 5.4**: Committed and pushed — `416044a9` (Task 2.1 + 2.3),
  `85ea6fee` (Phase 3), `3144c420` (Tasks 2.2, 4.1, 4.2)

## Dependencies

- Depends on: [Plan 00234](../00234-handler-value-audit/PLAN.md) Task 4.8 (the
  verdicts and the measurements)
- Related: [Plan 00237](../Completed/00237-remove-the-dead-handlers/PLAN.md),
  the removal slice of the same audit

## Success Criteria

- [x] Measured subprocess-spawn and file-read rates fall, verified by the SAME
  method before and after (git spawns 57% down by Task 1.2's method; file reads
  and the /proc walk measured at their own site — see Task 5.1)
- [x] The rendered status line is byte-identical in the steady state
- [x] Every TTL changed is justified against the measured render interval, not
  chosen as a round number
- [x] A guard exists that would catch a future TTL drifting back into resonance
  — and it caught a wrong premise in this very plan (Task 2.2)
- [x] Full QA passes; daemon restarts RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The blow-by-blow activity log lives in JOURNAL/. -->

- Resonance fixed and guarded — `416044a9` (git spawns 192 → 84 per ~116
  renders; `test_render_ttl_resonance.py`)
- Uncached-read family closed — `85ea6fee` (`MtimeCachedFile` extracted, four
  handlers resolved, `test_no_ungated_render_reads.py` stops a fifth)
- Remaining tuning — `3144c420` (`/proc` walk throttled separately;
  `git_context_injector` change-detects; `daemon_restart_verifier` stops
  repeating its resident guidance)
- **Open**: Task 2.1b only (scoped; needs 62 call-sequence-pinned tests
  re-pointed at behaviour before the production change can land)
