READY

# Plan 00466: ninth review of the goal-flip branch (N3)

**Verdict: READY.** No BLOCKER and no MAJOR. There is 1 MINOR and 4 NITs. None of them needs another review round.

**Reviewer**: Opus 5.5. The review was adversarial and read-only. No tracked file was edited, nothing was committed, and no daemon was started. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `5c52a3a5`. The review-8 baseline is `421fcbee`.
**Probes**:

- The probes are under `/workspace/untracked/scratch/probe_gf9_cache/` and `/workspace/untracked/scratch/probe_gf9_red/`.
- Every probe ran with `PYTHONPATH=<tree>/src`, and the probe printed `claude_code_hooks_daemon.__file__` to confirm the override.
- The RED proofs ran in `git archive` scratch copies. No `git stash` was used.

## Findings by severity

| Severity | Count | IDs              |
| -------- | ----- | ---------------- |
| Blocker  | 0     |                  |
| Major    | 0     |                  |
| Minor    | 1     | RV9-m1           |
| Nit      | 4     | RV9-n1 to RV9-n4 |

## Status of review 8's findings

| Finding | Claimed          | Verified                                                                                                                                                                                                                                                                                                                                                                           |
| ------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV8-M1  | Fixed            | **Fixed and proven RED.** Over 500 hits: the first call raises the original `ValueError` with depth 4. Every later hit raises a new `CachedConfigLoadError` with a constant depth of 2. All 500 exception objects are distinct (`semantics_out.txt`). Against `421fcbee`, both new tests fail: `assert 49 == 1` and a same-object failure (`probe_gf9_red/red_out.txt`).           |
| RV8-M2  | Fixed            | **Fixed and proven RED.** A flaky `EMFILE` gives `['OSError 24', 'Config', 'Config']` with 2 underlying loads, so the second call recovers. Both new tests fail against `421fcbee`.                                                                                                                                                                                                |
| RV8-m1  | Fixed            | **Fixed and proven RED.** I mutated `matches()` in a HEAD copy back to gate-first. The new order test then fails with `assert [None, None, None] == []`, and the other 27 tests pass (`probe_gf9_red/mut_order_out.txt`). The old test has been renamed, and its docstring now says it pins only the result.                                                                       |
| RV8-m2  | Fixed            | **Fixed.** Details are in "Memoisation" below. A memo hit costs 82 µs per call. Review 8 measured 310 to 591 µs. `build_handler_config_mapping` lives in `handlers/registry.py`. `daemon.cli._build_handler_config_mapping` delegates to it. `registry.py` imports nothing from `daemon`. `GoalInjectionHandler.TAGS` is a `ClassVar`, and `__init__` builds its tag list from it. |
| RV8-n1  | No action        | As review 8 said, none was required.                                                                                                                                                                                                                                                                                                                                               |
| RV8-n2  | Fixed            | Fixed. `_load_config` no longer says "not registered". The gate docstring now names the window where it can disagree before a restart.                                                                                                                                                                                                                                             |
| RV8-n3  | Docs corrected   | The `HANDLER_REFERENCE.md` sentence is now accurate. The separate item about the `register_all` behaviour was not filed (RV9-m1).                                                                                                                                                                                                                                                  |
| RV8-n4  | Fixed            | Fixed. Details are in "Warning dedup" below.                                                                                                                                                                                                                                                                                                                                       |
| RV8-n5  | Renumbered to 39 | The new number collides again (RV9-n4).                                                                                                                                                                                                                                                                                                                                            |

## 1. The exception type change: call 1 compared with call 2, through all 6 callers

Probe: `probe_gf9_callers.py`, output in `callers_out.txt`. Each caller's real `_load_config` (or `_config_reader`) was called 3 times per shape, and the cache was reset between callers.

**Result: every caller behaves the same on call 1, call 2 and call 3, for all 6 shapes.**

- **Shapes tested:** YAML syntax error, pydantic validation error, unknown top-level key, invalid UTF-8, a top-level list, and 5000-deep nesting.
- **Why this holds:** all six `except` clauses include `ValueError`:
  - `cron_stop_enforcer.py:127` and `cron_subagent_stop_enforcer.py:94` catch `(ValidationError, OSError, ValueError)`;
  - `remote_docs_routing.py:112` catches `(OSError, ValueError)`;
  - `plan_status_snapshot.py:138`, `recovery_cron_advisor.py:534` and `failsafe_cron_session_advisor.py:114` also add `RuntimeError`.
- **Why the caller cannot tell:** no caller inspects the exception type beyond logging it at DEBUG. So the switch from the original type (call 1) to `CachedConfigLoadError` (call 2 onwards) cannot be observed.

## 2. What is cached, precisely

**YAML syntax errors ARE cached.**

- `yaml.YAMLError` is not a `ValueError`. But `Config.load` (`config/models.py:2233-2241`) converts it to `ValueError(...) from exc` before it reaches the cache.
- The same happens to invalid UTF-8: yaml raises a `ReaderError`, which is a `YAMLError`.
- `json.JSONDecodeError` and `UnicodeDecodeError` are `ValueError` subclasses already.
- Evidence: `remote_docs_routing` (whose `except` branch does not build `Config()`) costs 0.9 ms on call 1 and 0.1 to 0.2 ms on hits, for every broken shape.

**Review 7's 80 ms parse cost is gone, but about 50 ms per call remains** for the other five callers (the 45 to 57 ms figures in `callers_out.txt`).

- The remaining cost is the fresh `Config()` that each `except` branch builds. That is review 8's "related context" item.
- For `plan_status_snapshot`, a broken config makes the gate miss its memo on every call and cost 50.1 ms (`semantics_out.txt`). Each call gets a new `Config()`, so the identity check never matches.
- The branch did not introduce this, and it costs time only while the config is broken. But it was never filed (RV9-m1).

**Not cached: `RecursionError` from a pathologically nested file.** See RV9-n1.

## 3. Memoisation by Config identity

- **Same object while the file is unchanged:** confirmed. The verdict is `True`.
- **New object after an edit:** confirmed. The verdict flips to `False` straight away.
- **A stale verdict can survive only a signature collision.** I rewrote the config to the same size and restored its mtime with `utime`. The verdict stayed `True` after `enabled: false`. This is the cache key's existing `(st_mtime_ns, st_size)` property and applies equally to the cached `Config` itself. The memo adds no new staleness, so it is not a finding.
- **The memo cannot confuse two configs.** The stored tuple holds a strong reference to the old `Config`, so a later object can never reuse its `id`.
- **Thread safety:** the memo is a single tuple attribute, read into a local and replaced whole. Both operations are atomic under the GIL. With 16 threads × 200 calls, every verdict was `{True}` and nothing raised. A race between two threads only means both compute the same verdict.

## 4. The re-export

- `daemon.cli._build_handler_config_mapping` is now a thin delegate, so it matches the shared function by construction.
- The other callers pass: `tests/unit/daemon/test_cli_handler_config_mapping.py`, `tests/config/test_models.py`, `tests/integration/test_acceptance_contract.py`, `test_handler_scope_defaults.py` and `test_project_handler_priority_collisions.py`.
- `handlers/registry.py` imports nothing from `claude_code_hooks_daemon.daemon`. `plan_status_snapshot` no longer imports `daemon.cli`.
- `test_qa_package_dependency_direction.py` passes.

## 5. The warning dedup set (`plan_trigger.py:41-67`)

- **Bounded:** after 257 distinct paths the set holds 256 entries.
- **Thread-safe:** the check, the insert and the eviction all run under `_WARN_LOCK`. The log call is made outside the lock, which is correct. With 16 threads × 2000 calls over 600 paths, the set held 256 entries and nothing raised.
- **Semantics:**
  - The same path is warned once.
  - An evicted path is warned again (1 warning).
  - Eviction is FIFO rather than LRU: a hit does not refresh a path's position. That is acceptable for this purpose.
  - A persistent alias is therefore warned once per daemon lifetime, unless 256 other aliases push it out. This matches review 8's ask ("logged once").

## 6. Tests (worktree venv, no whole-suite run)

- **Requested scope: 1388 passed** (`probe_gf9_cache/scope_run.txt`). It covered:
  - all of `tests/unit/handlers/post_tool_use/`;
  - `pre_tool_use/test_plan_status_snapshot.py` and `test_remote_docs_routing.py`;
  - `stop/test_cron_stop_enforcer.py`, `subagent_stop/test_cron_subagent_stop_enforcer.py` and `session_start/test_failsafe_cron_session_advisor.py`;
  - `utils/test_plan_status_snapshot.py`, `test_plan_trigger.py` and `test_config_cache.py`;
  - the three `test_registry*.py` modules and `daemon/test_cli_handler_config_mapping.py`;
  - `integration/test_qa_package_dependency_direction.py` and `test_template_priorities_match_the_constants.py`;
  - `config/test_models.py`, and the three integration modules that use the mapping.
- **Handler-doc checks: 80 passed** (`docs_run.txt`). These were `test_handler_reference_check.py`, `test_upgrade_regenerates_handler_docs.py` and `test_docs_generator.py`, run because `HANDLER_REFERENCE.md` changed.

## Minor

### RV9-m1: two follow-ups that review 8 asked to be filed are not in the ledger

**Where:** `CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md`. Neither item appears there.

**Problem:**

1. **The per-event `Config()` cost on a broken config** (review 8, "Related context": "File it as a follow-up"). It is still measured at about 50 ms per call in five callers, including every Stop and SubagentStop while the config stays broken.
2. **`register_all` ignores `get_default_enabled()` for an absent block** (RV8-n3's Direction: "file a separate item"). The docs now describe this behaviour accurately. But the underlying question is unrecorded: should an opt-in handler run on an `init minimal` install?

`CLAUDE/Plan/CLAUDE.md` says niggles are recorded, never just reported.

**Reproduction:** `grep -n "Config()\|get_default_enabled\|generate_minimal" NIGGLES.md` finds neither item. The 50 ms figure is in `probe_gf9_cache/callers_out.txt` and `semantics_out.txt`.

**Direction:** append two NIGGLES entries. No code change is needed on this branch.

## Nit

- **RV9-n1: `config_cache.py:60-64` says no `RuntimeError` is reachable from a per-call load. `RecursionError` is.**
  - A config nested 5000 levels deep raises `RecursionError`, which is a `RuntimeError` subclass. It is uncached and costs about 1.6 s per call. It also escapes `cron_stop_enforcer`, `cron_subagent_stop_enforcer` and `remote_docs_routing`, whose `except` clauses do not include `RuntimeError` (`callers_out.txt`, shape `deep_nesting`).
  - This is contrived, and the escape predates the branch. Only the docstring sentence is new.
  - **Direction:** correct the sentence. Optionally, have `Config.load` convert `RecursionError` to `ValueError`: the failure is deterministic for the bytes, so it would then be cached, and those three callers would stop leaking it.
- **RV9-n2: `CachedConfigLoadError` cannot be copied or pickled.**
  - `copy.copy(exc)` raises `TypeError: __init__() missing 1 required positional argument: 'message'`. This happens because `args` holds a single formatted string while `__init__` takes two parameters (`semantics_out.txt`).
  - Nothing copies it today.
  - **Direction:** add a `__reduce__`, or give `message` a default.
- **RV9-n3: `test_a_chmod_only_fix_is_picked_up_without_an_mtime_change` (`tests/unit/utils/test_config_cache.py`) runs no chmod.**
  - It is the flaky-read test again, with `errno` 13 in place of 24.
  - Its signature-unchanged assert is trivially true, because nothing touched the file.
  - **Direction:** rename it to describe what it does, or perform a real `chmod 000`/`644` and skip the test when running as root.
- **RV9-n4: release note 39 collides with `worktree-p468-core`'s `39-a-write-into-an-installed-plugin-...md`.** Resolve it at integration, as before.

**Verdict: READY.**
