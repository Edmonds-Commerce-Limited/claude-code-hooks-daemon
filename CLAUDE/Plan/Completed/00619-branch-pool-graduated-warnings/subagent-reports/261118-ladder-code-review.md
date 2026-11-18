# Code Review: Plan 00619 branch pool warning ladder

Branch `agent-aa5b3e19f48a28f06-f164c7f6` (commits a58cd5b58..03f328c1f), reviewed read-only against `main...HEAD`. 31 files, +1285/-15.

**Verdict: FAIL.** 12 defects: 1 critical, 5 important, 6 suggestions.

The ladder maths is correct and well tested. The problem is the stated invariant, "the new handlers never block and no guard decision changes". It does not hold once branch data cannot be read. Under this repository's `daemon.strict_mode: true`, the two new handlers deny every tool call and every prompt. In the stop guard, the ladder adds a path where a stop that should be held is allowed.

Probe scripts that reproduce the findings are in `/workspace/untracked/scratch/00619-review/`:

- `probe_ladder_crash.py`
- `probe_stop_ladder_only.py`
- `probe_stop_origin.py`
- `probe_chain_strict.py`, whose output is in `chain_strict_out.txt`
- `probe_cost.py`

Run each with `/workspace/.venv/bin/python -I <probe>`.

## Answers to the six review questions

1. **Ladder maths.** Correct.
   - `_threshold_count` is the integer ceiling (`branch_ladder.py:69-71`).
   - The block is at `count >= base` (`:80`), which matches the creation guard's deny at `len(groups) >= cap + creation_grace` (`branch_creation.py:986`) and at `>= cap` for parked and merged (`:961`, `:966`).
   - The open pool's base is `effective_wip_cap() + creation_grace` (`branch_ladder.py:94-95`).
   - Cap 0 cannot occur: every cap has `ge=1` (`models.py`, `BranchWipConfig.cap` and `BranchPoolConfig.cap`), so the base is always at least 1 and the percentage division cannot divide by zero.
2. **No guard decision changes.** Not met under failure. See C1 and I1. With git healthy, no deny/allow logic changed: `branch_creation.py` only renames `_CLEANABLE` and `_rank`, and the stop hold condition is untouched.
3. **Stop guard stays on the project root.** Met. `decide_stop` takes `self._project_root()` (`branch_stop_guard_base.py:112`). The new test `test_judges_the_project_root_whatever_directory_the_payload_names` is meaningful because the other clone's branch carries a touch record. It does run through `_project_root_override`, so the production `ProjectContext` path is not exercised.
4. **Tests.**
   - Strong points: the level table covers tiny bases where thresholds collapse (1, 2, 3, 5); the throttle tests are behavioural; the red commit is honest (only typing and formatting changed between a58cd5b58 and HEAD).
   - Gaps: failure paths, warn mode, the parked and merged wording, the cache TTL, `count_remote=True` and owner filtering (S2 to S4).
5. **Config and docs.**
   - Consistent: the yaml, the example, `init_config`, HOOKS-DAEMON.md, HANDLER_REFERENCE.md and the release note all agree.
   - The manifest version 3.76.0 is the right next minor after tag v3.75.0 (`pyproject` says 3.75.0), and no other UNRELEASED manifest collides with it.
   - One minor manifest gap, S6.
6. **Dead code, duplication, fail-open.** Covered in C1, I1, I5, S1 and S2.

## Critical

### C1. A failure to read the park records makes both "never block" handlers deny every tool call and every prompt in strict mode (Confidence: 95%)

**Location:**

- `src/claude_code_hooks_daemon/core/branch_ladder.py:143-153`, the except clause in `pool_pressures`.
- `handlers/pre_tool_use/branch_pool_pressure_advisor.py:66-77`.
- `handlers/user_prompt_submit/branch_pool_pressure_prompt.py:62-73`.

**Problem:**

- `pool_pressures` catches only `(RuntimeError, OSError)`.
- `work_pools` → `_pool_groups` → `_with_standing_parks` → `read_park_records` raises `BranchParkError` (`core/branch_park.py:128`). That class subclasses `Exception` (`branch_park.py:63`) and is neither of the caught types.
- `BranchParkError` is raised whenever `git config --get-regexp` returns anything other than 0 or 1. That includes the timeout `run_git` reports as returncode 124 under host load.
- The exception escapes `matches()`. `HandlerChain` then converts any handler raise under strict mode into a terminal deny: "SYSTEM ERROR: Handler ... crashed - blocking for safety" (`core/chain.py:1199-1219`).
- This repository runs `daemon.strict_mode: true` (`.claude/hooks-daemon.yaml:8`, under `daemon:`), and the wiring is live (`daemon/controller.py:1298`, `core/router.py:215`).
- The pools do not have to be full. The ladder reads the pools on every call, so an empty repository is enough. The PreToolUse advisor matches every tool, so for the length of a git hiccup every Read, Edit and Bash call is denied. The prompt handler holds every prompt.
- The cache keeps no record of a failure, so every call retries the git read.

**Evidence:** `probe_chain_strict.py`, output in `chain_strict_out.txt`:

```
BranchPoolPressureAdvisorHandler strict -> deny | SYSTEM ERROR: Handler branch-pool-pressure-advisor crashed - blocking for safety
BranchPoolPressurePromptHandler strict -> deny | SYSTEM ERROR: Handler branch-pool-pressure-prompt crashed - blocking for safety
```

`probe_ladder_crash.py` reproduces the same with the real `run_git` returning 124 for `git config`: `failing matches() RAISED: BranchParkError git config --get-regexp failed: timed out`.

**Why the tests miss it:** the only failure test, in both the ladder tests and the handler tests (`test_a_git_failure_is_silent`, `test_silent_outside_a_repository`), uses a missing directory. That fails in `_read_refs` and takes the caught `RuntimeError` path. No test makes a later read in `work_pools` fail, and no test runs the handlers through `HandlerChain` with `strict_mode=True`.

**Fix:**

1. In `pool_pressures`, also catch `BranchParkError`. Because the ladder is advisory by contract, the better fix is to make `ladder_notice` itself fail open on any `Exception`, using `log_and_continue`.
2. Add a test that monkeypatches `branch_creation.read_park_records` to raise. It should assert `matches()` is False, and assert that `HandlerChain.execute(..., strict_mode=True)` returns ALLOW for both handlers.

## Important

### I1. The ladder can turn a held stop into an allowed one and lose the block counter (Confidence: 85%)

**Location:**

- `src/claude_code_hooks_daemon/core/branch_stop_gate.py:285-290`.
- The catch-all in `handlers/utils/branch_stop_guard_base.py:120-127`.

**Problem:**

- `ladder_notice` runs after `reason` is computed and after `state[key] = blocks + 1`, but before `write_state`, and it sits inside the region the handler wraps with `except Exception: return allow`.
- If the ladder's own read fails, the stop guard allows a stop it had decided to deny, and the block-counter increment is never persisted.
- The failure in question is a `BranchParkError` from its second `read_park_records`, after `build_inventory`'s read succeeded (a transient timeout).
- This is a new allow path in a guard, which the plan's invariant forbids. To scope it honestly: `probe_stop_origin.py` shows that a persistent park-record failure already escapes `build_inventory` (at `branch_inventory.py:892`) on main. So the new exposure is the transient case only.
- The same pattern in `handlers/session_start/branch_sweep.py:189` means one ladder exception drops the whole branch summary, including the `CONTAINED NOWHERE` and pool-report lines computed before it.

**Evidence:** `probe_stop_ladder_only.py` patches only the ladder's read path. The traceback ends at `branch_stop_gate.py:288 -> branch_ladder.py:277 -> :144 -> branch_creation.py:900 -> :874 -> :402`.

**Why the tests miss it:** `TestLadderAtStop` covers healthy repositories only.

**Fix:** in both `decide_stop` and `branch_sweep`, compute the ladder lines in their own `try` that fails open with `log_and_continue`, and place the call after `write_state`. Add a test where the ladder read raises while a stop is held, asserting the decision is still DENY and the counter was written.

### I2. In `mode: warn` the ladder claims creation is refused when it is not (Confidence: 85%)

**Location:**

- `branch_ladder.py:157`: the ladder skips only pools in `off` mode.
- `:174`: the BLOCK headline reads "AT THE LIMIT (a new branch is refused)".
- `:207-208`: every line reads "of the point where creating a branch is refused".

**Problem:** `creation_report` refuses only when the pool's mode is `block` (`branch_creation.py:985`, `:1005`, `:1015`). With `wip.mode: warn`, `parked.mode: warn` or `merged.mode: warn`, the ladder still reaches BLOCK and states a refusal that never happens. Because BLOCK is never rate-limited, that false line is repeated on every tool call and every prompt.

**Why the tests miss it:** the only mode test covers `off`. No test sets `warn`.

**Fix:** for a pool in `warn` mode, word the top level as "at the cap (creation warns, not refused)", or end the ladder at VERY_STRONG. Add a test with `mode: warn` asserting the text does not contain "refused".

### I3. The strong-level advice is wrong for the merged and parked pools (Confidence: 80%)

**Location:** `branch_ladder.py:216-221`.

**Problem:**

- The text is the same for every pool: "A branch leaves the pool by being merged or ... the no-value verdict route ...; park it only as a short, bounded pause, with a reason."
- Branches in the merged pool are already merged. They leave by being deleted (`branch-sweep --clean`) or are kept with `branch-keep`.
- Parking does not take a branch out of the parked pool. It is how branches get into it.
- So for two of the three pools the strong and very-strong guidance contradicts the command printed on the line above it (`_command`, `:193-199`).

**Why the tests miss it:** `TestWording` builds only open-pool repositories. Neither `_command` nor `pressure_lines` is ever exercised for `Pool.PARKED` or `Pool.MERGED`.

**Fix:** use per-pool exit text: open = merge or no-value verdict, or park; parked = clear the park and merge; merged = sweep or keep. Add wording tests for parked and merged repositories, which the existing park and merge fixtures can build.

### I4. The every-call advisor runs several git processes synchronously on the PreToolUse hot path (Confidence: 75%)

**Location:**

- `branch_ladder.py:230-253` (a 10 s TTL cache).
- `branch_pool_pressure_advisor.py:66` (priority 20).

**Problem:**

- On a cache miss the reading runs `for-each-ref`, default-branch resolution, `git config --get-regexp`, `for-each-ref --merged`, `park_marked_refs`, and `is_park_residue` for each parked ref and target. On this repository that takes 378-495 ms (`probe_cost.py`).
- Each git call is allowed up to `GIT_CONTEXT` 5 s, or `GIT_BRANCH_METADATA_MAX` 10 s.
- The chain deadline is 20 s (`Timeout.CHAIN_DEADLINE_DEFAULT`). A slow ladder at priority 20 spends the budget before the later SAFETY+BLOCKING guards, which are then denied as "not judged in time" (`models.py:1906-1915`). Under load that is another new deny path.
- Failures are not cached (C1), so a failing host pays the full cost on every call.
- The branch-sweep code itself says the PreToolUse path "cannot afford the inventory" (`branch_sweep.py:168-169`).

**Fix:**

1. Cache the failure result as well as successes.
2. Prefer refreshing the reading off the hot path, for example with a snapshot written at SessionStart and refreshed by a PostToolUse after a branch-mutating command, the way the labels snapshot is.
3. Or bound the reading by a time budget and fall silent when it is exceeded.

### I5. Duplicated handler bodies and test scaffolding (Confidence: 80%)

**Location:**

- `branch_pool_pressure_advisor.py:40-81` and `branch_pool_pressure_prompt.py:35-77` are line-for-line the same: `__init__` fields, `_project_root`, `matches` and `handle`.
- `_project_root` is a third copy of `branch_creation_guard.py:147-154`.
- The `_git` and repo builders are copied into `test_branch_ladder.py`, `test_branch_pool_pressure_advisor.py` and `test_branch_pool_pressure_prompt.py`.

**Problem:** the C1 fix, and any change to the throttle or cache wiring, must be made twice and could drift.

**Fix:** move the shared behaviour into a mixin in `handlers/utils/`, for example `BranchLadderSurface`, holding `_branches`, `_project_root`, `_due`, `matches` and `handle`. Move the test repository builder into a shared fixture under `tests/unit`.

## Suggestions (non-blocking; each to be filed as a plan task)

- **S1. Dead parameters and a dead branch.**
  - `PressureCache.get(clock=...)` (`branch_ladder.py:243`) and `ladder_notice(now=...)` (`:269`) are never passed by any caller or test.
  - `decide_stop` receives `now` but does not forward it (`branch_stop_gate.py:288`), so the ages in the stop report use the wall clock and ignore the injected clock.
  - `if pressure.work:` (`:210`) is always true: WARN or higher means `count >= ceil(base*warn/100) >= 1`.
  - Fix: forward `now` from `decide_stop`, test the TTL through `clock` or delete the parameter, and drop the dead `if`.
- **S2. The cache's behaviour is untested.** Every handler test uses `PressureCache(ttl=0.0)`, so the hit path and up to 10 s of staleness after a branch is deleted or created are never exercised. The key is `id(config)` (`:246`), which can be reused after a config reload. Fix: add a TTL test driven by `clock`, and key on the repository plus a config hash, or simply `repo`.
- **S3. The default remote and owner path is untested at the ladder level.** All ladder and handler tests set `count_remote=False`. Foreign remote-only branches excluded by `_owned_refs` (per-owner counting) and local plus remote copies counted once are never shown to give the right ladder count. Fix: add one test with a remote holding the caller's branches and another author's branches, asserting the count.
- **S4. The unfinished-first test uses a label shape the snapshot does not write.**
  - `test_strong_names_an_unfinished_branch_before_a_merged_one` uses labels with no `local_tip`.
  - A real snapshot label records the tip. A tipped "merged" label moves the branch into the MERGED pool (`_tip_label`, `branch_creation.py:545-555`, `:571`).
  - So in production the filter at `branch_ladder.py:187` almost never excludes anything from the open pool.
  - Fix: build the fixture labels with tips, assert what the filter really does, and drop the filter if it does nothing.
- **S5. A pool can be refused by staleness while the ladder is quiet.** Parked and merged creation is also refused for a stale member regardless of count (`branch_creation.py:960-967`), while the ladder speaks only by count. With an unkept merged branch (stale from day 0), creation is refused while the ladder is silent or says "1 of 10".
  - Design consequence for the owner, not a code defect: rounding up means a base of 9 or less never reaches VERY_STRONG. This repository's `parked.cap: 1` goes straight from silent to AT THE LIMIT, which then repeats on every call and prompt while one branch is parked.
  - Fix: either name the stale-member block in the ladder lines or state the limit in HANDLER_REFERENCE. Record the small-cap behaviour for the owner.
- **S6. The manifest has no entries of its own for `branches.parked.ladder` and `branches.merged.ladder`.** They are mentioned only inside the `branches.wip.ladder` description (`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.76.0.yaml`), so the key diff in `check-config-migrations` will not name them. Fix: add one `added` entry for each, and check against `CLAUDE/UPGRADES/config-changes/SCHEMA.md` whether `recommended: true` is right for handlers that are already on by default.

## Positive observations

- The level table is thorough, including bases where the thresholds collapse onto the block point. The integer-ceiling arithmetic avoids float error, and the ordering validator rejects unordered thresholds.
- The red commit is honest. Expectations were unchanged between a58cd5b58 and HEAD, apart from typing and formatting.
- The renames (`CLEANABLE_GROUPS`, `work_rank`) are complete. No stale `_CLEANABLE` or `_rank` references remain, and the creation guard's deny logic is untouched.
- The stop-guard pin test is meaningful: the foreign clone's branch carries a touch record for the same session.
- No `--allow-unproven`, archive-ref or override wording appears anywhere.
