# Plan 00466 — fourth review of the goal-flip branch (N3)

**Reviewer**: Opus 5.5. Read-only adversarial verification. I edited no tracked file, committed nothing, and did not start or restart a daemon. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `4d960ce9`. Base (`git merge-base main HEAD`): `1569d25f`.
**Earlier reviews**: `260924-n466-goalflip-review2-opus-5-5.md` and `260924-n466-goalflip-review3-opus-5-5.md`.

## Findings by severity

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 1     |
| Minor    | 7     |
| Nit      | 7     |

**Verdict: NOT READY.**

Every scenario from review 3 now gives the right answer, both with a PreToolUse snapshot and on the inference fallback. RV3-M1 is fixed and its tests are pinned. But two review-3 fixes interact to cause a new major regression (RV4-M1):

- RV3-m5 caps each plan at 50 owners and drops the oldest first.
- RV3-m3 makes every session that receives a combined signal an owner of **every** live plan.

Once 50 sessions have touched **any** live plan, the session that flipped a plan is evicted from that plan's owners. When that session then completes its own plan, its `/goal` is not refreshed. Main does refresh it.

The snapshot design works for single-writer sequences. It has three weaknesses:

- The store is not thread-safe, but the daemon dispatches on a thread pool (RV4-m1).
- A snapshot taken before a permission prompt, or before another session's write, can go stale (RV4-m2).
- The snapshot handler ships disabled, and no operator doc says to enable it (RV4-m4).

The exception refactor dropped all three exclusions honestly. However, its `is_file()` pre-check lets `EACCES` escape as a raw `PermissionError`, where main logged a warning and returned an empty list (RV4-m3).

## How I verified

Everything ran from the worktree's own venv (`untracked/venv-workspace_untracked_worktrees_worktr-0f21-py311-81c29529`). The package imported from the worktree's `src`. Main comparisons imported from `/workspace/src`. Every probe root sits under `/workspace/untracked/scratch/probe_gf4_*`. `ProjectContext.project_root` and `daemon_untracked_dir` were monkeypatched onto that root. Every hand-built payload carries `"synthetic_source": "review-goalflip-v4"`.

- **Targeted pytest: 693 passed.** The files were `test_goal_injection`, `test_goal_ledger`, `test_plan_status_snapshot` (utils and pre_tool_use), `test_plan_trigger`, `test_git_facts`, `test_recovery_cron_advisor`, `test_claude_md_injector`, `test_docs_generator`, `test_registry`, `test_markdown_fences` and `test_blocking_handler_evasion`. Output: `probe_gf4_pytest_targeted.txt`.

- **`scripts/qa/audit_error_hiding.py`: 0 violations.** Output: `probe_gf4_audit_error_hiding.txt`.

- **Probe harness `probe_gf4_lib.py`.** In **snap** mode, each Edit or Write goes through three steps:

  1. The real `PlanStatusSnapshotHandler` runs first, against the pre-write file, with a fresh `tool_use_id`.
  2. The change is applied to disk exactly as the tool would apply it. Edits get a uniqueness assertion.
  3. `goal_injection` handles the payload.

  In **fallback** mode the payload has no `tool_use_id`. This is also the path taken after a daemon restart between Pre and Post.

The scripts, all in `/workspace/untracked/scratch/`:

| Script                                             | Covers                                                                                                                                          | Output                                                               |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `probe_gf4_rv3.py`                                 | Every review-3 scenario (A1–A7, B1–B5, C1–C11, X1–X8), plus C2r (a genuine bulk flip) and C5n (a Write that creates a plan already In Progress) | `probe_gf4_rv3_branch_snap.txt`, `probe_gf4_rv3_branch_fallback.txt` |
| `probe_gf4_attack.py`                              | E (owner cap), F1/F2 (interleaving), G (store bounds, TTL, duplicate id), H (latency, never-raise)                                              | `probe_gf4_attack_branch.txt`                                        |
| `probe_gf4_evict2.py`, `probe_gf4_evict_main.py`   | RV4-M1: eviction across plans, branch against main                                                                                              | `probe_gf4_evict2_out.txt`, `probe_gf4_evict_main_out.txt`           |
| `probe_gf4_race.py`                                | RV4-m2: a Pre that ran before another session's flip                                                                                            | `probe_gf4_race_out.txt`                                             |
| `probe_gf4_threads.py`, `probe_gf4_threads2.py`    | RV4-m1: the store under concurrent threads                                                                                                      | `probe_gf4_threads_out.txt`, `probe_gf4_threads2_out.txt`            |
| `probe_gf4_eacces_setup.py`, `probe_gf4_eacces.py` | RV4-m3: real `EACCES`, run under `setpriv` without `CAP_DAC_OVERRIDE`/`CAP_DAC_READ_SEARCH`, branch against main                                | `probe_gf4_eacces_out.txt`                                           |
| `probe_gf4_mutate.py`                              | Step 5: 20 fix reverts in a scratch copy of HEAD (`probe_gf4_mut/`, extracted with `git archive`)                                               | `probe_gf4_mutate_out.txt`                                           |
| `probe_gfv3_n7.py`, re-run against the worktree    | RV3-n4: renders the CLAUDE.md block and HOOKS-DAEMON.md with the branch's code                                                                  | `probe_gf4_n7/`                                                      |

## Status of review 3's findings

| Finding | Status                                              | Evidence (branch, both modes unless stated)                                                                                                                                                                                                                              |
| ------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| RV3-M1  | **Fixed**                                           | **A4:** S2 gets `+clear` and S1 gets nothing. **A4b:** S2 gets `names 00298`; S1 and S3 get nothing. **X2, A7:** `<no signal>`. **X7:** the manual goal survives (`names 00301`). The mutants that drop the transition gate or take the first retired entry both go RED. |
| RV3-m1  | **Fixed**                                           | C1, C2 and C2b give no advisory and leave no `displaced_by`. The mutant goes RED on 3 tests, which now use real post-edit fixtures. C2r (a genuine status-plus-cell bulk flip) is detected in snap mode and missed on the fallback, a trade-off the ledger documents.    |
| RV3-m2  | **Behaviour fixed; the fix is not pinned** (RV4-m5) | C7, C7b, C8, C8b and X3 give no advisory, and C11 and C11c are detected. But the mutant that restores a literal post-state check stays **GREEN**.                                                                                                                        |
| RV3-m3  | **Fixed**, but it feeds RV4-M1                      | X1: S3 gets `names 00298`.                                                                                                                                                                                                                                               |
| RV3-m4  | **Fixed**                                           | B2 and C9 (same lifetime) give `<no signal>`. B5 gives `(256, 1)`. Both mutants go RED.                                                                                                                                                                                  |
| RV3-m5  | **Cost fixed. The cap causes RV4-M1**               | A5: the terminal write takes 0.011 s (review 3 measured 0.249 s), with 50 owners.                                                                                                                                                                                        |
| RV3-m6  | **Fixed**                                           | C5 and C5g give no advisory, and C5h stays silent. The mutant goes RED.                                                                                                                                                                                                  |
| RV3-m7  | **Partly fixed**                                    | The ledger text is corrected. New over-claims are in RV4-m7.                                                                                                                                                                                                             |
| RV3-m8  | **Fixed**                                           | X6: both paths return `ok`. X8: the Pre handler logs and records nothing. The `_plan_state` and `_read_plan` mutants go RED. The `_find_plan_md_text` mutant stays GREEN (RV4-m5).                                                                                       |
| RV3-n1  | Documented                                          | See RV4-n6 on the strict-mode wording.                                                                                                                                                                                                                                   |
| RV3-n2  | **Fixed**                                           | The `ever_recorded_sessions` mutant turns 8 tests RED.                                                                                                                                                                                                                   |
| RV3-n3  | **Partly fixed** (RV4-n1)                           | Only the module docstring was trimmed.                                                                                                                                                                                                                                   |
| RV3-n4  | **Not done, and the ledger says it was** (RV4-m6)   | See RV4-m6.                                                                                                                                                                                                                                                              |
| RV3-n5  | **Fixed in snap mode**                              | C3 and C3b are detected in snap mode and conservatively missed on the fallback. Both snapshot mutants go RED.                                                                                                                                                            |

**Step 4 (exclusions).** `git diff 1569d25f..HEAD -- scripts/qa/error_hiding_exclusions.json '*exclusions*'` shows one removal (`goal_injection._read_plan`) and nothing added. No `noqa`, `type: ignore` or `pragma` was added. Two `# nosec B603 B607` comments were added to tests (RV4-n4).

**Step 5 (tests go RED when a fix is reverted).** 18 of 20 reverts turned the suite RED. The two that stayed GREEN are the RV3-m2 post-state check and the `ValueError` catch in `_find_plan_md_text` (RV4-m5).

**Snapshot latency.** `matches()` takes 0.2 µs on a Bash call and 1.5 µs on a non-plan Edit. `matches()` plus `handle()` on a plan Edit takes 206 µs. There is no measurable cost on non-plan calls.

## Blocker

None.

## Major

### RV4-M1 — the owner cap evicts the flipping session from its own plan, so completing that plan does not refresh its `/goal` (a regression against main)

**Where:**

- `src/claude_code_hooks_daemon/utils/goal_ledger.py:66` (`_MAX_OWNERS_PER_ENTRY = 50`) and `:148-168` (`_add_bounded`/`_add_owner`). These evict index 0 FIFO. A session that is already present returns early, so an owner that keeps touching the plan is never moved to the end.
- `src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py:1357-1372` (`_extend_ownership`). It adds every session that receives a combined signal to **every** live plan's owners.
- `goal_injection.py:1168-1188` (`_maybe_refresh_on_retirement`). It refreshes only `owning_sessions(plan_number)`, never the session whose write completed the plan.

**Reproducers:**

- **`probe_gf4_evict2.py` (E2).** L flips 00296 and S flips 00298. 50 teammates tick 00298, and each is reasserted and absorbed into 00296's owners through `_extend_ownership`. L then completes its own 00296.
  - With 10 teammates, L gets `names 00298`, which is correct.
  - With 50 teammates, L is **no longer an owner of 00296**, and L's signal still reads `names 00296,00298`.
  - `probe_gf4_evict_main.py`: the same sequence on main gives `refreshed=True names00296=False`. On the branch it gives `refreshed=False names00296=True`.
- **`probe_gf4_attack.py` (E).** L flips the only live plan and N teammates touch it.
  - At N=49, L is retracted.
  - At N=50 and N=60, L gets no `+clear`, whether L or TM059 completes the plan. The 50 sessions that do get retracted are the most recent teammates, most of which are probably dead.
  - In A5 (`probe_gf4_rv3.py`), 151 goal-intent files remain after the terminal write. The 100 evicted teammates keep text that names the completed plan.

**Why it matters:**

- The stale `/goal` names a finished plan. This is Plan 00321's "challenges every stop for the rest of the session" failure, and here it hits the lead, the one session most likely to still be alive.
- 50 is not a large number here. This session alone lists more than 60 agents, and `_extend_ownership` counts any session that touched **any** live plan.
- This also undermines the B4 decision (`NIGGLES.md:766-776`). Its premise, "absorption only decides WHO IS REFRESHED", no longer holds once the cap exists: absorption also decides who is **evicted**.
- `test_plan_ownership_is_bounded` (`test_goal_injection.py:2171`) pins the cap, but not what happens to the owners it drops.

**Direction:**

1. Always include the completing write's own `session_id` in the refresh set.
2. Make eviction least-recently-touched rather than insertion-order: move an owner to the end on every touch. Never evict the entry's flipper (`session_id`). Alternatively, retract an owner's signal at the moment it is evicted.
3. Consider having the retirement refresh skip `_extend_ownership`'s absorbed owners. Or cap absorbed owners separately, so absorption cannot push out direct owners.
4. Add RED tests for E2, and for the completer being refreshed when it is past the cap.

## Minor

### RV4-m1 — the snapshot store is not thread-safe, but the daemon dispatches hook events on a thread pool

**Where:**

- `utils/plan_status_snapshot.py:14-20`. The docstring says "no filesystem round trip, no lock".
- `:54-86`. `record` and `consume` both run `_evict_expired`, which iterates `self._entries.items()`. `record` also does `del self._entries[next(iter(...))]`.
- `daemon/server.py:1435-1443`. Every event goes through `loop.run_in_executor(None, ...)`, which is the default `ThreadPoolExecutor`.

The codebase already takes `threading.Lock` for this pattern, for example in `utils/config_cache.py:35`.

**Reproducers:**

- **`probe_gf4_threads2.py`, at the shipped 300 s TTL.** Two threads each do `record` then `consume`, with 200 orphan entries preloaded. In 3 runs of about 230k calls each, between 439 and 487 calls raised `RuntimeError: dictionary changed size during iteration` or `dictionary keys changed during iteration`.
- **`probe_gf4_threads.py`, with a short TTL.** The second deleter also raises `KeyError`.

**Impact:**

- An exception from `record` escapes `PlanStatusSnapshotHandler.handle`. An exception from `consume` escapes `goal_injection.handle`.
- Today (N24: `strict_mode` is inert in the live daemon), the result is a lost or incorrect goal decision plus a "Handler exception" context line.
- Once N24 lands, `probe_gf4_attack.py` H shows the chain turning a handler exception into `deny` "SYSTEM ERROR ... blocking for safety". The Write that gets blocked is a legitimate PLAN.md Write, which breaks the "never raises, must not block a Write" requirement.
- Orphan entries are the normal case, not an edge case. Every edit whose result is neither In Progress nor terminal leaves one behind (`goal_injection.py:1011-1015` → `:1160-1162` returns before consuming). So the store usually sits near its cap, and each call iterates about 256 entries.

**Direction:** Guard `record`, `consume` and `_evict_expired` with one `threading.Lock`, and use `pop(key, None)` in the eviction loops. Add a threaded test.

### RV4-m2 — a snapshot is not "ground truth" once the file changes between Pre and the write, and the Pre→Post gap includes the permission prompt

**Where:**

- `goal_injection.py:904-907`. A found snapshot is trusted unconditionally.
- `:933-935`. It claims "the race this guards against cannot have occurred".
- `utils/plan_status_snapshot.py:30-35`. The TTL comment says the gap is "bounded by the tool's own execution time".

PreToolUse runs before the permission check (`/workspace/remote-docs/code.claude.com/docs/en/hooks.md:1597,1918`), so the gap includes however long a person takes to answer the prompt.

**Reproducer: `probe_gf4_race.py` (F3).**

1. S0 flips Q.
2. S1's Pre for a plain task tick on P runs while P reads Not Started.
3. S2 really flips P, then S3 flips R.
4. S1's tick lands and its Post runs.

In **snap** mode, S1 gets `⚠️ GOAL DISPLACED`. R is persisted as `displaced_by=00300`, P's own displacement is erased, and `_fired[(S1,00300)]` is set. That is N3's full symptom set. In **fallback** mode, the same interleaving gives no advisory and no change to displacement.

F2 (`probe_gf4_attack.py`) shows the retirement version: a note whose Pre ran before the Complete flip clears the owner a second time. This is rare in bypass mode, but a permission prompt or two concurrent teammates widens the window to minutes. It is not a regression against main, because main fires on any In Progress edit. It is a hole in the "no collision possible" claim.

**Direction:**

- For Edit, have the Pre handler also record a digest of the pre-write text. In Post, check that reversing the edit reproduces it. If it does not, the file changed underneath, so fall back to the inference (which gets F3 right).
- Alternatively, use the snapshot only when the reconstruction is ambiguous.
- Fix the TTL comment either way.

### RV4-m3 — the new `is_file()` pre-checks let `EACCES` escape as a raw `PermissionError`; main logged a warning

**Where:**

- `utils/goal_ledger.py:315`: `if not self._path.is_file(): return None` sits outside the `try`.
- `handlers/pre_tool_use/plan_status_snapshot.py:122`: the same shape.

Commit `4d960ce9` added both, so that the missing-file branch "never touches an except handler". But `Path.is_file()` swallows only `ENOENT`, `ENOTDIR`, `EBADF` and `ELOOP`. Every other `stat` error, including `EACCES` and `ENAMETOOLONG`, is raised outside the domain-exception contract.

**Reproducer: `probe_gf4_eacces.py`.** The ledger's parent directory is mode `000`. The probe runs as root under `setpriv` with the DAC capabilities dropped. The branch results:

- `entries()`, `session_has_entries()`, `is_plan_live()` and `live_plan_numbers()` all raise **`PermissionError`**.
- The Pre handler's `handle()` on a plan folder that denies search also raises `PermissionError`.

On main, `entries()` and `live_plan_numbers()` return `[]` with the warning "unreadable ledger".

**What this contradicts:**

- The ledger module's own contract (`goal_ledger.py:13-14`: "a missing, corrupt, or unwritable ledger never raises out of the public API").
- `auto_continue_stop._goal_ledger_challenge` (`handlers/stop/auto_continue_stop.py:795-813`), which promises fail-open for an unreadable ledger.
- `HANDLER_REFERENCE.md:3662`.

The reverse error also happens: `is_file()` silently reads a directory or a symlink loop as "missing". The Pre handler then records `None`, meaning "no prior status", which its own docstring (`:82-88`) says must not happen for an unknown state.

`probe_gf4_attack.py` H shows `ENAMETOOLONG` raising from Pre, and denied under `strict=True`. The Write itself would fail there too, so that case alone is a nit.

**Direction:** Move the existence check inside the `try`. `return None` in the try body is not the audited shape. Any `OSError` then becomes `LedgerUnreadable`/`PlanUnreadable`. Add an `EACCES` test that monkeypatches `Path.stat`.

### RV4-m4 — `plan_status_snapshot` ships disabled and nothing tells operators to enable it, so clients get the fallback on every write

**Where:**

- `handlers/pre_tool_use/plan_status_snapshot.py:64-66` (`get_default_enabled() -> False`). Only this repo's `.claude/hooks-daemon.yaml:660-662` enables it.
- `docs/guides/HANDLER_REFERENCE.md` has no entry for the handler.
- Release note 13 (`:17-23`) calls the snapshot "`goal_injection`'s primary source of truth". Line 81 says "No other action is needed — everything above is automatic."

**Effect:**

- A client that enabled `goal_injection`, the only step documented, takes the inference path on every PLAN.md write. It logs `no pre-write status snapshot … falling back` at INFO each time (`goal_injection.py:908-912`).
- It keeps every conservative miss: C3, C3b and C2r give `<no signal>` in `probe_gf4_rv3_branch_fallback.txt`.
- The Pre handler docstring (`:17-20`) and `_resolve_transition` (`goal_injection.py:897-900`) list "a daemon restart … or a payload with no `tool_use_id`" as the only no-snapshot cases.

**Direction:**

- Either register or enable the sensor whenever `goal_injection` is enabled, or add a config-validation warning when `goal_injection` is on without it.
- Add a HANDLER_REFERENCE entry.
- Correct release note 13 and the two docstrings.

### RV4-m5 — the RV3-m2 fix and one RV3-m8 branch are not pinned by any test

**Where:**

- `test_goal_injection.py:1293` (C7b) and `:1314` (C8) write the **pre-edit** file and then dispatch the Edit. The `new_string` is never on disk, so `_is_transition_via_reconstruction` returns at `:776` ("new_string not found") before the post-state check matters. This is the same fixture defect review 3 raised as RV3-m1.
- The `_find_plan_md_text` `ValueError` catch (`goal_ledger.py:211`) is unreachable in the tests. `_plan_state` has already marked the undecodable plan unreadable, so it is never live.

**Reproducer: `probe_gf4_mutate.py`.**

- Replacing `PlanDoc.parse(plan_text).status` in `handle()` with a `'**Status**: In Progress' in plan_text` literal leaves the suite **GREEN** (204 passed).
- Reverting `_find_plan_md_text` to `except OSError` also leaves it **GREEN**.

**Direction:** Apply the edit to the fixture before dispatching, as the C7b and C8 probes in `probe_gf4_rv3.py` do. For `_find_plan_md_text`, test it directly, or corrupt the plan between reconciliation and the refs read.

### RV4-m6 — RV3-n4 was not done, and the ledger says it was

**Where:** `NIGGLES.md:708-711` says the block was "Regenerated by a daemon restart before this pass's commit". But `git log -- CLAUDE.md .claude/HOOKS-DAEMON.md` shows the last regeneration is `d23b56f0`, which is main's commit and predates this pass. Neither file mentions `plan_status_snapshot`, although this repo's config enables it.

**Reproducer:** `probe_gfv3_n7.py <worktree>/src <worktree> …/probe_gf4_n7 1` renders the branch's block.

- The branch's code starts the promoted tier with `lsp_enforcement`. The committed CLAUDE.md starts with `sed_blocker`.
- The rendered block has a `plan_status_snapshot` line (`CLAUDE.md:635-637` in the render), and the rendered HOOKS-DAEMON.md has a row at `:41`.
- The committed files have neither. The first daemon restart after the merge will auto-commit the difference.

**Direction:** Restart the worktree daemon, commit the regeneration, and correct the ledger sentence.

### RV4-m7 — documentation over-claims against actual behaviour

- **Release note 13, `:41-58`.**
  - It says a terminal plan "drops it from every CURRENT owning session's combined `/goal` text". That is false for evicted owners, including the completer (RV4-M1).
  - It presents the cap only as a cost bound.
  - "can no longer be misread either way" (`:21-23`) is false on the fallback (RV4-m4) and under interleaving (RV4-m2).
- **`docs/guides/HANDLER_REFERENCE.md:3033`** still says "The trigger is STATE-based … not transition-based: the first edit to an already-In-Progress plan in a NEW session re-fires". That is the exact behaviour N3 removes. `:3662`'s fail-open claim is false under RV4-m3.
- **`goal_injection.py:836-851`** (the `_is_real_transition` docstring) describes an `old_string` "FIRST witness … used DIRECTLY" fast path. The code (`:870-873`) no longer has one; `NIGGLES.md:633-636` says it was removed.
- **`goal_injection.py:1456-1461`** (`get_claude_md`) says "every session ever handed a plan's goal keeps its own claim". That is false past the cap.
- **`utils/plan_status_snapshot.py:30-31`**: the TTL rationale is covered under RV4-m2.
- **`PLAN.md:41`** shows N3 as ✅ Remedied. `NIGGLES.md:683` says the entry is "held at 🔄 until this pass lands". Given this report, hold it at 🔄.

## Nit

- **RV4-n1 — RV3-n3 is only partly done.** The module docstring was trimmed, but the method docstrings still narrate review rounds. A grep for review labels finds 42 hits in `goal_injection.py` and 26 in `goal_ledger.py`. Examples:

  - "measured at 0.25s for 150 owners, against 0.003s on main" (`goal_injection.py:1139-1143`);
  - "the pre-fix shape" (`goal_ledger.py:116`, `:557`, `:647`);
  - "The previous implementation read…" (`goal_ledger.py:610`).

  `NIGGLES.md:703-707` claims the trim is complete.

- **RV4-n2 — the "single shared implementation" is not shared by `goal_injection`.** `utils/plan_trigger.py:10-13` says both handlers call into it. But `GoalInjectionHandler.matches()` (`goal_injection.py:965-975`) and the top of `handle()` (`:989-995`) re-implement `matched_plan_write_or_edit`. `_COMPLETED_SEGMENT` is also duplicated (`:234`). Call `matched_plan_write_or_edit` from both.

- **RV4-n3 — `record_emission` on `LedgerUnreadable` rewrites the ledger from empty** (`goal_ledger.py:483-486`, then `:528`). Main does the same. The new warning, "proceeds from an empty ledger", does not say that the unreadable file is about to be replaced. For a transient `OSError`, as opposed to corrupt JSON, this destroys every live entry and `ever_recorded_sessions`. Either say so in the log, or skip the save when the cause is an `OSError`.

- **RV4-n4 — two new `# nosec B603 B607` in tests** (`test_goal_injection.py` and `test_recovery_cron_advisor.py`, both in `_git`). They copy `test_git_facts.py:30`'s helper and its suppression. Reuse the one helper instead of adding two more suppressions.

- **RV4-n5 — test classes subclass `TestNewSessionReassertion` to reuse fixtures.** `TestOwnershipSurvivesASecondSession`, `TestResumedSameSessionReassertion` and `TestReview3Fixes` each re-run the parent's tests: 108 `def test_` give 117 collected. A fixture mixin avoids the duplicates.

- **RV4-n6 — docstrings assert that this repo's `strict_mode` DENIES.** Examples: `goal_injection.py:1096-1101` and `goal_ledger.py:307-309`. That contradicts N24 (`NIGGLES.md:152-169`: `strict_mode` is inert in the live daemon). Word it conditionally.

- **RV4-n7 — pathological paths raise from the Pre handler.** A symlink-loop `PLAN.md` raises `RuntimeError` from `is_inside_project`'s `resolve()` (`plan_trigger.py:61-78`; the shape is pre-existing, copied from `goal_injection`). A folder name longer than `NAME_MAX` raises `OSError` (RV4-m3). The Write would fail in both cases, so the only harm is a misleading "SYSTEM ERROR" under strict mode. Catch `RuntimeError` in the second `try`.

## Things I attacked that held

- **Missing `tool_use_id`.** It falls back and logs. The whole review-3 suite passes on the fallback, apart from the documented conservative misses (C3, C3b, C2r).
- **Duplicate `tool_use_id`.** A later Pre overwrites the earlier one. Ids are unique by construction, so this is not a real risk.
- **Pre without Post** (a denied, failed or deferred call). The store is capped at 256 (5000 Pre-only calls leave 256), and the TTL evicts (size 1 after expiry). Snapshots are keyed by call, so a stale one cannot reach a different call.
- **Daemon restart between Pre and Post.** This is the same as fallback mode, and correct.
- **A Write that creates a plan already In Progress** (C5n). Both modes give `names 00304`.
- **MultiEdit and NotebookEdit.** Neither handler matches them, so behaviour is unchanged from main.
- **A plan moved or archived mid-flight.** The Edit fails, so there is no PostToolUse and the snapshot is orphaned and bounded. `/Completed/` paths are excluded from both matchers.
- **Fenced, per-phase and date-qualified Status lines.** C7, C7b, C8, C8b, X3, C11 and C11c are correct in both modes.
- **`replace_all`.** C2, C2b and C2r are correct in snap mode.
- **Memory.** The store is capped at 256 with a TTL, both latch maps at 256, owners at 50 per plan (see RV4-M1) and `ever_recorded` at 200.
- **Exception refactor, apart from RV4-m3.**
  - Each `except PlanUnreadable`/`LedgerUnreadable` logs a WARNING and takes its documented branch.
  - Neither of N29's shapes appears: a local assigned in the handler and returned later, or a catch-log-continue with no substantive branch. `record_emission`'s `else:` continuation is a real fail-open path, not an evasion.
  - `audit_error_hiding.py` is clean with zero exclusions for these functions.

## Recommended order of work

1. RV4-M1: include the completer in the refresh, and make owner eviction LRU with the flipper never evicted. Add RED tests for E2.
2. RV4-m1: a lock around the store. RV4-m3: move the existence checks inside the `try`.
3. RV4-m4: tie the sensor's enablement to `goal_injection`, or document it.
4. RV4-m2: cross-check the snapshot against the Edit's own reconstruction, and fix the TTL comment.
5. RV4-m5: fix the fixtures. RV4-m6: regenerate CLAUDE.md and HOOKS-DAEMON.md. RV4-m7 and the nits: correct the docs, the release note and the ledger, and hold N3 at 🔄.

**Verdict: NOT READY.**
