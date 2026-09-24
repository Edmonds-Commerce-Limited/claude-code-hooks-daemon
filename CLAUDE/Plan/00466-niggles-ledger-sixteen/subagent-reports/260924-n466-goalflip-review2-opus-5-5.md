# Plan 00466 — second review of the goal-flip fix-up (N3, N7)

**Reviewer**: Opus 5.5, read-only verification. No tracked file was edited in either checkout.
**Branch**: `worktree-n466-goal-flip` at HEAD `56d5b9a3`. The fix commit is `7eb246dc`, on top of `d705f2c0`.
**First review**: `260924-n466-review-opus-5-5.md` (M2, M3, m4, m5, m6, n3, n4, n6, n7).

## Summary

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 1     |
| Minor    | 5     |
| Nit      | 3     |

**Verdict.** The narrow cases the first review named are fixed:

- M2 when the completing session still owns the ledger entry;
- M3 for a new session id;
- m4, m5, m6, n3, n6 and n7;
- all four regression cases;
- N7 determinism.

However, the two new mechanisms work against each other:

- M3's re-assert **transfers** a plan's single ledger owner to whichever fresh session touches it.
- M2's retraction now asks "does THIS session own the live entry?"

So once a second session touches the plan (a teammate ticking a task, for example), the session that flipped it can no longer retract it when it completes. The ledger stays live and no `.goal-clear` is written. Main retracts correctly in the same scenario (RV-M1).

The m4 reversal also re-opens a narrow path to N3's own false-flip symptoms (RV-m1). N3 should not be marked ✅ Remedied yet. N7 is sound.

## What I verified

**Targeted pytest** on the branch passed: **408 passed**. The files were:

- `test_goal_injection.py`, `test_goal_ledger.py`, `test_git_facts.py`, `test_recovery_cron_advisor.py`
- `test_claude_md_injector.py`, `test_docs_generator.py`, `test_registry.py`

**Handler-level probes.** Each ran in a throwaway project root with `ProjectContext` pointed at it, so no real ledger or sidecar was touched. All are under `/workspace/untracked/scratch/`:

| Script                                               | What it covers                                                                                                                                                    | Output                                                     |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `probe_gf_handler.py` (helpers in `probe_gf_lib.py`) | Every M2, M3, m4 and m5 case and every regression case                                                                                                            | `probe_gf_handler_out.txt`                                 |
| `probe_gf_compare.py`                                | The new-defect scenarios against both the branch source and main's `/workspace/src`                                                                               | `probe_gf_compare_branch.txt`, `probe_gf_compare_main.txt` |
| `probe_gf_clear.py`                                  | Single-plan retraction after another session touched the plan, both sources                                                                                       | `probe_gf_clear_out.txt`                                   |
| `probe_gf_ledger.py`                                 | `has_live_entry`, `session_has_entries` and `reassert_session` under a missing file, 5 corrupt variants and 60 concurrent threads                                 | `probe_gf_ledger_out.txt`                                  |
| `probe_gf_determinism.py`                            | The CLAUDE.md block rendered over the real registered handler set (139 instances, this project's config and `promoted_handlers`), shuffled 12 times plus reversed | `probe_gf_determinism_out.txt`                             |

**Real hook payloads.** `probe_gf_hook.py` drove the worktree's `.claude/hooks/post-tool-use`, which started a worktree daemon running branch code:

- Every payload carried `"synthetic_source": "review"`.
- The plan files used numbers 00901–00904, which no real plan uses. They sat under the worktree's gitignored `untracked/scratch/probe_gf_hook/`, because `_is_inside_project` needs them inside that project root.
- Phase 1 ran, then `bin/hooks-daemon restart` gave a new PID (1633563 → 1638273), then phase 2 ran.
- Output: `probe_gf_hook_phase1.txt` and `probe_gf_hook_phase2.txt`.
- **Cleanup:**
  - Afterwards I deleted the probe-created `untracked/goal-ledger.json` (and its `.lock`), `untracked/context-sidecar/` and the probe plan tree. None of them existed before the probe.
  - I stopped the daemon I had started.
  - `git status --porcelain` in the worktree was clean before and after. The real restart regenerated CLAUDE.md byte-identically.

## Status of the first review's findings

| Finding  | Status                                                                                                                  | Evidence                                                                                                                                                                                                                                                            |
| -------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M2       | **Fixed** for the case the first review described. **Broken** again once ownership moves (RV-M1) and in a race (RV-m2). | **Handler:** M2a flipped 00296 and 00298, took a new handler instance, ticked 00296, then completed it. The signal named `00298`. **Real daemon restart:** 00902 was completed after the restart and dropped out of the signal (`names 00901,00903,00904`).         |
| M3       | **Fixed** for a new session id: no displacement and no advisory. **Not covered** for a same-id resume (RV-m3).          | M3a: S2 touched 00296 and got a signal naming `00296,00298` with `no-advisory`. The ledger's `displaced_by` fields were unchanged before and after. Only the owner of 00296 changed, from S1 to S2. The hook run matched: `gfrev-NEW` got a signal and no advisory. |
| m4       | **Fixed** for the case the first review named. The reversal introduces RV-m1.                                           | m4a: `old="Not Started"`, `new="In Progress"` on a Not Started plan produced a signal. The hook run gave the same result for 00904.                                                                                                                                 |
| m5       | **Fixed**                                                                                                               | m5a: a Write appending to a nested-repo plan already committed as In Progress gave `<no signal>`. m5b: a Write flipping a nested-repo plan committed as Not Started produced a signal.                                                                              |
| m6       | **Fixed** in code (`registry.py:473`, `:517` are `sorted(...)`). The narrative is only partly corrected (RV-n1).        | Code read.                                                                                                                                                                                                                                                          |
| n3       | **Fixed**                                                                                                               | `git_facts.py` imports only `constants.timeout` and `utils.git_repo`, and `git_repo` imports no core module.                                                                                                                                                        |
| n4       | Not changed (acknowledged). The inconsistency is now inside one class (RV-n2).                                          | —                                                                                                                                                                                                                                                                   |
| n6       | **Fixed**                                                                                                               | The promoted order follows `promoted_handlers`: lsp_enforcement, pipe_blocker, sed_blocker … auto_continue_stop. The worktree CLAUDE.md matches.                                                                                                                    |
| n7       | **Fixed**                                                                                                               | The release-note title now reads "already-In-Progress/Complete".                                                                                                                                                                                                    |
| N7 check | **Holds**                                                                                                               | 14 renders over 139 real handlers gave 1 distinct SHA-256 (`6152f92d4aef71aa`). No handler name appears twice across chains, so the name sort is a total order.                                                                                                     |

**Regression cases.** All pass at handler level and through the real hook:

| Case                                         | Expected                                                                                   | Handler                                                            | Hook                                              |
| -------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------- |
| Edit adds a table row to an In Progress plan | No signal change, no advisory. The session has its own entries, or the plan is unledgered. | R1 and R1c: no new signal, `no-advisory`, ledger unchanged.        | R1: `no-displacement-advisory`, signal unchanged. |
| Not Started → In Progress flip               | Emits                                                                                      | R2: signal plus advisory for the displaced plan.                   | Same.                                             |
| Write of a new In Progress plan              | Emits                                                                                      | R3: signal.                                                        | Same.                                             |
| Complete → In Progress reopen                | Emits                                                                                      | R4 (Edit) and R4b (Write against a HEAD reading Complete): signal. | R4: signal plus advisory.                         |

A fresh session adding a table row to an **already-ledgered** In Progress plan does write its own signal. That is the M3 re-assert, working by design. It writes no ledger record and gives no displacement advisory.

## Blocker

None.

## Major

### RV-M1 — The M3 re-assert moves the plan's only owner, and the M2 retraction keys on that owner, so the session that flipped a plan can no longer retract it

- **Where:**

  - `utils/goal_ledger.py:436`: `reassert_session` overwrites `existing.session_id`.
  - `utils/goal_ledger.py:398-401`: `has_live_entry` requires `e.session_id == session_id`.
  - `goal_injection.py:813`: `_maybe_refresh_on_retirement` returns early unless `_session_ledgered_plan(session_id, plan_number)`.

- **Cause:** Before the fix, retraction keyed on the in-memory `_fired[(session, plan)]` latch. Every session that emitted a plan held its own latch, so ownership changes in the ledger did not matter. Now:

  - Retraction keys on a single-valued ledger owner.
  - The re-assert path hands that owner to any session with no ledger entries that makes a non-flip touch. That includes a teammate ticking a task in the lead's plan, which is routine here.
  - The original session's completing write then fails `has_live_entry`. So it neither re-renders nor clears, and the ledger entry is not reconciled either.

- **Failure scenarios** (in each, main retracts and the branch does not):

  1. **Single plan** (`probe_gf_clear.py`):

     - LEAD flips 00296.
     - TEAMMATE ticks a task in it, and the ledger owner becomes TEAMMATE.
     - LEAD sets it Complete.

     | Source | LEAD's `.goal-intent` | LEAD's `.goal-clear` | Ledger entry for 00296 |
     | ------ | --------------------- | -------------------- | ---------------------- |
     | Branch | Still names 00296     | Not written          | Still `live`           |
     | Main   | Removed               | Written              | `retired`              |

     `goal_injection.py:497-503` records why this matters. Claude Code's `/goal` slot is last-writer-wins, so without the clear trigger "a retired goal otherwise challenges every stop for the rest of the session" (Plan 00321). The session affected is the lead's, which is the one under the ccy supervisor.

  2. **Two plans** (`probe_gf_compare.py` M2b):

     - S1 flips 00296 and 00298.
     - TEAMMATE ticks 00296.
     - S1 completes 00296.
     - S1's signal: the branch still names `00296,00298`; main names `00298`.

  3. **A resumed session's second plan** (`probe_gf_compare.py` M3b′):

     - S1 flips 00296 and 00298.
     - A new session S2 touches 00296. The re-assert fires, and S2 now owns 00296.
     - S2 ticks 00298. `session_has_entries` is now True, so no re-assert: S1 still owns 00298.
     - S2 completes 00298.
     - S2's signal: the branch still names `00296,00298`; main names `00296`.

  4. **Real hook, across a real daemon restart** (`probe_gf_hook_phase2.txt`):

     - `gfrev-NEW` re-owned 00901 in phase 1.
     - In phase 2 `gfrev-S1` completed 00901.
     - `gfrev-S1`'s signal still named 00901, and `.goal-clear pending: False`.

- **Side effect:** The teammate also gets a `.goal-intent` naming the lead's plan (`TEAMMATE intent file names 00296`). It is harmless only while no supervisor watches that session id.

- **What the tests pin:** No test covers retraction after an ownership change. `TestHasLiveEntry.test_false_for_a_different_session` pins the exact behaviour that causes this defect.

- **Fix direction:** Retraction must not depend on a single owner. Either:

  - record every session that was handed a plan's goal (a `sessions` set on the entry that the re-assert *adds* to rather than overwrites) and, on a terminal write, refresh or clear each of those sessions' signals; or
  - keep `has_live_entry` but make `reassert_session` additive rather than a transfer.

  Add RED tests for scenarios 1 and 3.

  A related gap is pre-existing on main: when a *different* session completes the plan, the flipping session's goal is never retracted. The sessions-set approach closes that gap too.

## Minor

### RV-m1 — The m4 reversal undoes the first occurrence of `new_string`, not the edit site, so it can fake a flip, or miss one

- **Where:** `goal_injection.py:644-646` (`post_edit_text.replace(new_string, old_string, 1)`, and the `replace_all` variant).
- **Cause:** The Edit tool replaced the unique occurrence of `old_string`. Nothing makes the first occurrence of `new_string` in the post-edit text that same site. When `new_string` also occurs earlier, the reversal rewrites the wrong span. The Status line sits near the top of the file, so the typical collision is `new_string` being a substring of the Status line ("In Progress", "Progress").
- **Failure scenarios:**
  - **m4b (false flip).** The plan is already In Progress and has a table cell reading `Not Started`. An `Edit(old="Not Started", new="In Progress")` is reversed on the Status line, so the pre-edit status reads Not Started and the edit counts as a FLIP. The result is a signal, a displacement advisory, and a persistent `displaced_by=00300` on another live plan. These are N3's full symptoms.
  - **m4c.** The same happens with `replace_all=True`.
  - **Before the fix commit** this path returned `False`. The earlier code had `if not before.status_line_present: return False`. So the m4 fix introduced this path.
  - **m4d (missed flip).** The title is "Track In Progress plans" and the status is Not Started. A value-only flip is reversed in the title, so it reads as not a flip: the branch shows `<no signal>` and main emits. This one is contrived.
- **Severity:** Minor, because the trigger needs `new_string` to occur before the edit site. This project's task rows use emoji markers and its ledger tables use "🔄 In progress", so it is rare here. Client projects that write "In Progress" in task tables will hit it.
- **Fix direction:** Consider every occurrence of `new_string` as a candidate edit site. Keep only candidates whose reversal leaves `old_string` unique, since the Edit tool enforced that. Call it a flip only if every surviving candidate agrees that the pre-edit status was not In Progress. Otherwise take the conservative `False`. Add RED tests for m4b and m4d.

### RV-m2 — M2's `has_live_entry` ignores an entry retired a moment earlier, so a reconciliation that runs first silently suppresses the retraction

- **Where:** `goal_ledger.py:399` (`e.retired_at is None`) together with `goal_injection.py:813`.

- **Cause:** By the time PostToolUse runs, the terminal status is already on disk. Any `live_plan_numbers` or `record_emission` call from another session in that window reconciles and retires the entry, and `has_live_entry` then returns False. The callers are:

  - `auto_continue_stop` (Stop);
  - `failsafe_cron_blockage_suppressor` (UserPromptSubmit);
  - another session's goal_injection write.

  Main's `_fired` latch did not have this window.

- **Failure scenario:** `probe_gf_compare.py` M2c interleaves one `live_plan_numbers()` between the write and `handle()`. S1's signal: the branch still names `00296,00298`; main names `00298`. The window is short, but with dozens of concurrent teammates on one daemon it is reachable.

- **Fix direction:** The refresh is idempotent, so accept an entry for this session and plan whether it is live or was retired with `RETIRED_TERMINAL_STATUS`. RV-M1's sessions-set fix subsumes this.

### RV-m3 — A same-id resume is excluded, although the docs promise that "a resumed session still gets its /goal back"

- **Where:** `goal_injection.py:875` (the `session_has_entries` gate); the module docstring at `:32-44`; release note 13's second bullet.

- **Cause:** Claude Code's `--resume`/`--continue` reuse the session id unless `--fork-session` is given, so a resumed session already has ledger entries and never re-asserts. The supervisor unlinks `.goal-intent` on consumption (`00269/SIGNAL-CONTRACT.md` "Consumption"), so nothing is left for it to find.

- **Failure scenario:** `probe_gf_compare.py` M3c:

  1. S1 flips.
  2. The signal is consumed.
  3. The daemon restarts.
  4. S1 touches the plan.

  The branch writes `<no signal>`. Main re-fires, because its latch is empty after the restart.

  Whether Claude Code keeps the `/goal` slot across a resume is not established here. If it does not, the resumed session has no goal.

- **Fix direction:** Either:

  - scope the gate to "has this session emitted *this* plan since the daemon started", an in-memory set that does not stop the ledger answering M2; or
  - narrow the docs to "a new session id", and keep `inject-goal` as the documented path after a resume.

### RV-m4 — The release note, the docstrings and the ledger overclaim

- **Where:** release note `13-goal-injection-…`; `NIGGLES.md` N3 (✅ Remedied).
- **What is wrong:**
  - "An edit or rewrite that leaves an already-In-Progress or already-Complete status unchanged emits nothing from either handler." This is false twice:
    - RV-m1: a false flip with a displacement advisory;
    - the M3 re-assert: a fresh session's first touch deliberately writes a signal.
  - "A plan completing after a daemon restart still drops out of the combined `/goal` text." This holds only while the completing session still owns the entry (RV-M1, RV-m2).
  - "A resumed session still gets its `/goal` back." See RV-m3.
- **Fix direction:** Correct these statements, and set N3 back to in progress until RV-M1 is fixed.

### RV-m5 — A non-UTF-8 ledger raises out of the new methods; the cause is pre-existing, but these methods expose it far more often

- **Where:** `goal_ledger.py:228-234`. `entries()` catches `OSError` and `json.JSONDecodeError`, but a `UnicodeDecodeError` from `read_text` is neither.
- **Failure scenario:** `probe_gf_ledger.py`, "corrupt[binary]", gives `RAISED UnicodeDecodeError`. Four other corrupt shapes (truncated JSON, a list root, a non-list `entries`, a bad field type) and a missing file all fail open correctly. 60 concurrent threads mixing `record_emission`, `reassert_session` and the readers finished with no errors, all 20 plans present, and no leftover `.tmp`.
- **Why it matters now:** On the branch every non-flip touch of an In Progress plan runs `session_has_entries`, and every terminal write runs `has_live_entry`. Both are reached without a guard. With `strict_mode: true` (this repo), a byte-corrupt ledger turns every such PLAN.md edit into a PostToolUse system error. The module contract says a corrupt ledger "never raises out of the public API".
- **Fix direction:** Catch `ValueError` (or `UnicodeDecodeError`) alongside `JSONDecodeError` in `entries()`.

## Nit

- **RV-n1 — the m6 narrative is still wrong in four places.** Each still blames `pkgutil.walk_packages()`, which sorts. The real cause was `register_all`'s globs, which `NIGGLES.md:68` now states correctly. The four places are:

  - `core/claude_md_injector.py:683` ("now itself sorted at the source too");
  - `daemon/docs_generator.py:205`;
  - `tests/unit/daemon/test_docs_generator.py:253`;
  - `tests/unit/core/test_claude_md_injector.py:1692`.

- **RV-n2 — n4 is now inconsistent inside one class.** In `goal_injection`:

  - `_session_ledgered_plan` and `_maybe_reassert_for_new_session` let `RuntimeError` from `daemon_untracked_dir()` propagate;
  - `_write_combined_signal` and `_ledger_record` catch it and fall back.

  The `7eb246dc` message calls the split "intentional per the first review's explicit design", but the first review's n4 flagged the split as the problem.

- **RV-n3 — test gaps.**

  - No test covers the four RV-M1 scenarios, or RV-m1 (`new_string` occurring before the edit site).
  - `test_register_all_handler_order_is_independent_of_glob_order` reads the chain's private `_handlers`. It only works because the lazy sort in `.handlers` has not run yet, so any earlier access to `.handlers` would make it pass whatever the glob order.
