NOT READY

# Plan 00466: eighth review of the goal-flip branch (N3)

**Verdict: NOT READY.** 2 MAJOR, 2 MINOR, 5 NIT. No BLOCKER.

**Reviewer**: Opus 5.5. The review was adversarial and read-only. No tracked file was edited, nothing was committed, and no daemon was started. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `421fcbee`. The review-7 baseline is `88991a06`.
**Probes**:
- The probes are under `/workspace/untracked/scratch/probe_gf8_cache/`, `probe_gf8_red/`, `probe_gf8_m1/` and `probe_gf8_symlink/`.
- Every hand-built hook payload carries `"synthetic_source": "review-goalflip-v8"`.
- The RED proofs ran in `git archive` scratch copies, loaded with `PYTHONPATH=<copy>/src`. I confirmed the override with `claude_code_hooks_daemon.__file__`. No `git stash` was used.

## Findings by severity

| Severity | Count | IDs              |
| -------- | ----- | ---------------- |
| Blocker  | 0     |                  |
| Major    | 2     | RV8-M1, RV8-M2   |
| Minor    | 2     | RV8-m1, RV8-m2   |
| Nit      | 5     | RV8-n1 to RV8-n5 |

## Status of review 7's findings

| Finding | Claimed | Verified |
| ------- | ------- | -------- |
| RV7-B1 | Fixed | **Fixed.** The four asserts now compare against `Priority.*`. Note that these asserts are now tautological (RV8-n1). |
| RV7-M1 | Fixed | **The order swap is fixed, but no test covers it** (RV8-m1). The failure cache that came with it introduces two new defects (RV8-M1, RV8-M2). |
| RV7-m1 | Fixed | **Fixed in behaviour.** `probe_gf8_m1/registry_out.txt` has 11 config shapes: this repo's config, this repo plus `disable_tags`, plus `enable_tags` as a list, and plus `enable_tags` as a scalar, `init full`, `init full` plus enabled, `init full` plus enabled with each tag filter, `init minimal`, `init minimal` plus `disable_tags`, and an empty file. The gate matches `register_all` in all 11. The gate's cost is examined in RV8-m2. Two docstrings are stale (RV8-n2). |
| RV7-m2 | Fixed | **Fixed and proven RED.** With the constants reverted to `GOAL_INJECTION=31` and `MARKDOWN_TABLE_FORMATTER=26`, all four `TestFormatterOrderingChain` tests fail: the guard, FE, FT4 and FC3b (`probe_gf8_red/mutord_chain.txt`). The mutant run's caplog records the "is stale" WARNING for `tu-fe`, `tu-ft4` and `tu-fc3b`, which proves the new stale assertion is reachable. Against `88991a06` itself the chain tests pass, as expected, because that commit already carries the fixed order. |
| RV7-m3 | Fixed | **Fixed and proven RED.** The new test fails against `88991a06` with the capture `'00301-l'` (`probe_gf8_red/red_vs_88991a06.txt`). Review 7's own probe, rerun at HEAD, now retires 00300 with `+clear` (`probe_gf8_symlink/gf7_rerun_head.txt`). The edge cases are in the next section. |
| RV7-m4 | Fixed | **Fixed.** There are six `changed` entries, with a `migration_note` on the pair that matters. The released v3.66.0 values (31/26/27/28/29/30) match every "was" value in the entries. Both "unconditionally" sentences have been rewritten. |
| RV7-n1 | Fixed | Fixed. The formatter block now sits below goal_injection's commented options. |
| RV7-n2 | Fixed | Fixed. The note is renumbered to 33 and trimmed to three sentences. The new ordinal collision is RV8-n5. |
| RV7-n3 | Fixed | Fixed. The bullet has been added at `goal_injection.py:933-938`. |

RED against `88991a06`, with the HEAD tests overlaid: 6 failed and 46 passed. The failures are:
- the symlink test;
- the cache-by-failure test;
- the absent-block test;
- the real-invalid-YAML load-failure test;
- the `no-goal-injection-block` and `disable-tags-covering-it` rows of the table-driven test.

## Major

### RV8-M1: re-raising the cached exception object grows its traceback on every call, which leaks memory for the daemon's lifetime and corrupts the traceback across threads

**Where:** `src/claude_code_hooks_daemon/utils/config_cache.py:99-109`. The problem is `raise result` on a cached `Exception` instance.

**Problem:**
- Raising an exception instance that already has a `__traceback__` prepends the new frames to that traceback. It does not replace it.
- The cache hands out the same instance on every hit. Every call while the config stays broken therefore adds that call's frames to one shared chain, and nothing ever frees them.
- The retained traceback keeps each caller's frame alive, together with all of that frame's locals.
- Six handlers share this code path. `cron_stop_enforcer.matches` hits it on every Stop, `cron_subagent_stop_enforcer` on every SubagentStop, `recovery_cron_advisor` on plan lifecycle writes, and `plan_status_snapshot` on plan writes.
- Dispatch is threaded (`run_in_executor`), and the raise happens inside `_LOCK`, but propagation happens outside it. So concurrent threads splice their frames into the same chain. Any `exc_info` rendering then shows thousands of frames from unrelated calls and threads.

**Reproduction:**
- `probe_gf8_cache/probe_gf8_tb_growth.py` (output in `tb_growth_out.txt`): each caller frame holds a 10 KB local. After 2, 101, 1001 and 2001 calls there are 6, 204, 2004 and 4004 traceback frames. The live local objects number 2, 101, 1001 and 2001, and traced memory reaches 22.4 MB. It is the same exception object every time.
- `probe_gf8_cache/probe_gf8_tb_real.py` (output in `tb_real_out.txt`) goes through the real `PlanStatusSnapshotHandler._load_config` and `RecoveryCronAdvisorHandler._load_config`. After 1000 rounds the cached exception carries 4002 frames.

**Direction:**
- Never re-raise the stored instance. Cache a failure marker, for example the exception type and `str(exc)`.
- On a hit, raise a fresh exception. One option is a new `CachedConfigLoadError(ValueError)`, which every caller's existing `except` already catches.
- If the original type must be kept, raise a copy that has `with_traceback(None)` applied, rather than mutating the shared object.
- Add a test: call `load_config_cached` N times on a broken file, and assert that the traceback depth of the raised exception does not grow with N. Also assert that two hits never return the same exception object.

### RV8-M2: a transient `OSError` is now cached until the file's content changes, so a VALID config reads as broken for the rest of the daemon's life

**Where:**
- `config_cache.py:48-53`: `OSError` is in `_CACHEABLE_LOAD_FAILURES`.
- `config_cache.py:105-109`: the failure is stored under the unchanged `(st_mtime_ns, st_size)` signature.

**Problem:**
- The cache key identifies the file's CONTENT. A failure like `EMFILE`, `EIO`, `EACCES` or `ENOMEM` is a property of the READ, not of the content.
- Before this commit, the next event retried and recovered. Now the failure persists until someone edits the config or restarts the daemon.
- A permission repair such as `chmod` changes neither the file's mtime nor its size. I checked this: `chmod changes signature: False`.
- The affected callers then quietly run on defaults:
  - `cron_stop_enforcer` and `cron_subagent_stop_enforcer` stop enforcing declared crons;
  - `failsafe_cron_session_advisor` and `recovery_cron_advisor` lose declared config;
  - `plan_status_snapshot`'s gate flips to the defaults answer.
- All of this is logged at DEBUG only.

**Reproduction:** `probe_gf8_cache/probe_gf8_transient.py` (output in `transient_out.txt`). The config is valid. `load_or_default` fails once with `EMFILE`. Calls 0 to 4 all raise `OSError [Errno 24]`, and `load_or_default` is invoked once in total.

**Direction:**
- Cache only the failures that are a deterministic function of the bytes: `ValidationError` and the YAML-parse `ValueError`. Never cache `OSError`.
- Decide whether `RuntimeError` belongs in the set. Nothing in `load_or_default` documents raising it.
- Add a test: a flaky `load_or_default` that raises `OSError` once and then succeeds must yield a valid `Config` on the second call.

**Related context, not a separate finding:** the failure cache saves the parse, about 56 ms for this repo's config with an error near the end (`bigbroken_out.txt`). It does not save the other half of the per-event cost. Every caller's `except` branch builds `Config()` fresh, which takes about 34 ms per call on this host because of `validate_handler_dependencies` (`config_ctor_out.txt`, and the profile in `tb_prof_out.txt`). So "a broken config costs one parse per edit" is true, but each event still pays about 30 ms or more. Caching the degraded default next to the failure, or a module-level `_DEFAULT_CONFIG`, would close that. File it as a follow-up.

## Minor

### RV8-m1: the RV7-M1 order swap has no test, and the test that claims to cover it has the opposite name

**Where:** `tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py:344`, `test_gate_runs_before_the_trigger_match_so_a_non_plan_write_is_still_false`.

**Problem:**
- The name states the pre-fix order.
- The test also passes with either order, because a non-plan write is False either way.
- Review 7's Direction #2 was to replace it with a test that proves the order. That was not done.

**Reproduction:** in a HEAD copy, restore the old order in `matches()`: gate first, then trigger. `tests/unit/handlers/pre_tool_use/` and `test_goal_injection.py` then give 463 passed and 0 failed (`probe_gf8_red/mutm1_out.txt`).

**Direction:**
1. Rename the test.
2. Add a test that monkeypatches `_goal_injection_enabled`, or `_load_config`, to raise or to count its calls.
3. Assert that it is never called for a Bash payload, a Read payload, or a non-plan Write.

### RV8-m2: the RV7-m1 gate now costs about half of what it exists to save

**Where:** `plan_status_snapshot.py:159-171`.

**Problem:**
- On every plan write, the gate does three things:
  - builds `_build_handler_config_mapping` over EVERY event's handler blocks, which means `model_dump` for each one;
  - constructs a throwaway `GoalInjectionHandler`, just to read its tags;
  - imports a private helper from `daemon.cli`. It is the only handler in the tree that does this, so the layering runs backwards.
- Where goal_injection is off, the gate saves the snapshot's work at about twice the gate's own cost. Where goal_injection is on, it adds about 50% on top.

**Reproduction:**
- `probe_gf8_m1/probe_gf8_handlecost.py` (output in `handlecost_out.txt`): with this repo's config and a real-size PLAN.md, the gate costs 446 to 591 µs and `handle()` costs 1030 µs.
- `probe_gf8_m1/gatecost_out.txt`: the gate costs 310 µs and a cached `_load_config` costs 38 µs.

**Direction:**
- Memoise the verdict against the identity of the `Config` object. `load_config_cached` returns the same object while the file is unchanged, so a stored pair `(config_obj, verdict)` is enough.
- Take the tags from a class-level constant rather than building an instance.
- Move `_build_handler_config_mapping`, or just the single-event part of it, into `handlers/registry` or `config`, so that a handler does not import `daemon.cli`.

## Nit

- **RV8-n1: the RV7-B1 asserts are tautological.**
  - `handler.priority == Priority.X`, where `__init__` passes `Priority.X`, can never fail.
  - With the four constants mutated to 94, 95, 96 and 97, the four test modules give 239 passed (`probe_gf8_red/mutb1_four.txt`). Only `test_template_priorities_match_the_constants` catches the change (`mutb1_guards.txt`), and only when the template is not updated with it.
  - This is the form review 7 asked for, and the repo uses both forms (51 literal and 51 constant asserts). The ordering that matters is guarded by `test_goal_injection_precedes_markdown_table_formatter`, and that guard is proven RED.
  - **Direction:** none required. If the other four handlers' relative order should be pinned, add one pairwise ordering assert instead.
- **RV8-n2: stale gate docstrings.**
  - `plan_status_snapshot.py:118-124` (`_load_config`) still says the fallback defaults are the state "under which `goal_injection` (opt-in) is not registered". That is false: `register_all` registers it.
  - `:132-133` says the gate "can never disagree with what the daemon actually runs". It still disagrees after a config edit that has not been followed by a restart, because the registry is fixed at startup and the gate reads the current file. Review 7's option 2, registry-injected state, was not taken.
  - **Direction:** correct both sentences.
- **RV8-n3: goal_injection's docs say "Ships disabled (opt-in)", but a minimal or empty config registers it.**
  - This predates the branch. See the `init minimal` and `empty file` rows in `probe_gf8_m1/registry_out.txt`: `generate_minimal()` writes `post_tool_use: {}`, and `register_all` never consults `get_default_enabled()`.
  - Since RV7-m1, the gate follows the daemon, so those installs now also run the sensor. That is consistent behaviour, but `docs/guides/HANDLER_REFERENCE.md:3057` overstates the default.
  - **Direction:** file a separate item. Either make `register_all` honour `get_default_enabled()` for an absent block, or have `generate_minimal()` emit explicit `enabled: false` for opt-in handlers.
- **RV8-n4: `plan_trigger.py:117` logs a WARNING on every match of a PLAN.md that resolves outside the pattern.**
  - Examples are a PLAN.md symlinked to a non-plan file, or a folder alias into `Completed/`.
  - The warning fires twice per tool call, once at Pre and once at Post. Review 7 asked for it to be logged once.
  - **Direction:** deduplicate per path, for example with a bounded seen-set, or drop to INFO after the first.
- **RV8-n5: the release-note ordinal 33 collides with N46 and N47.** Resolve it at integration, as the brief says.

## Symlink edge cases (RV7-m3 fix)

Probe: `probe_gf8_symlink/probe_gf8_symlink.py`, output in `symlink_edges_out.txt`.

| Case | Result |
| ---- | ------ |
| Link to a folder OUTSIDE the project | Refused (`None`). |
| Chain `00311-a -> 00310-b -> 00300-c` | Resolves to `00300-c`. |
| Loop `00320-loop <-> 00321-loop` | Refused (`None`). It does not crash and does not fail open: `resolve()` raises `RuntimeError`, which `is_inside_project` catches. |
| Alias into `Completed/` | Refused, with a WARNING (RV8-n4). |
| `Completed/` path used directly | Refused. |
| PLAN.md symlinked to a non-plan file | Refused, with a WARNING. |
| Dangling link to a nonexistent folder | Captured under the target's name. This is contrived and harmless. |
| Plan dir reached through a root-level alias (`PlanAlias/`), or a path with `..` | `None`. The raw-text regex runs first, so the resolved-path re-capture is never reached. This predates the branch and is not a regression. |

Review 7's S1d case, where S3 edits a plan through the link while 00300 is live: the edit now takes the documented new-session reassert path under 00300. That is the same result as an edit through the real path.

## Test scope (worktree venv, no whole-suite run)

- **Requested scope:** `tests/unit/handlers/post_tool_use/` (whole directory), `tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py`, `tests/unit/utils/test_plan_status_snapshot.py`, `test_plan_trigger.py`, `test_config_cache.py`, `tests/integration/test_template_priorities_match_the_constants.py`, `test_config_changes_manifest_examples.py` and `test_pending_release_notes_holding_area.py`. Result: **953 passed** (`probe_gf8_red/scope_run.txt`).
- **The other `load_config_cached` callers:** the test modules for `cron_stop_enforcer`, `cron_subagent_stop_enforcer`, `failsafe_cron_session_advisor` and `remote_docs_routing`. Result: **80 passed** (`probe_gf8_red/callers_run.txt`). No caller depends on seeing a fresh exception: each one catches, logs at DEBUG and returns defaults. `cron_stop_enforcer`, `cron_subagent_stop_enforcer` and `remote_docs_routing` do not catch `RuntimeError`, which is now cacheable. That is another reason for RV8-M2's Direction to narrow the set.
- **Cache bounds:** `_CACHE` has one entry per distinct resolved config path, so it is bounded. The leak in RV8-M1 lives inside the one cached value, not in the number of entries.

## Recommended order of work

1. RV8-M1 and RV8-M2 together: narrow the cacheable set, and raise a fresh exception on every hit. Add the two tests.
2. RV8-m1: add the order test and rename the old one.
3. RV8-m2: memoise the gate verdict.
4. The nits.

**Verdict: NOT READY.**
