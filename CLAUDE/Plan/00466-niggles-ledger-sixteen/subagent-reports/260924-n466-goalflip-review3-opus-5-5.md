# Plan 00466 — third review of the goal-flip branch (N3, N7)

**Reviewer**: Opus 5.5, read-only adversarial verification. No tracked file was edited in either checkout, nothing was committed, and no daemon was started or restarted.
**Branch**: `worktree-n466-goal-flip` at HEAD `c40d4ce6`. The review-2 fixes are in `05557ece`, and `c40d4ce6` undoes RV-n2's round-1 helper.
**Earlier reviews**: `260924-n466-review-opus-5-5.md` and `260924-n466-goalflip-review2-opus-5-5.md`.

## Findings by severity

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 1     |
| Minor    | 7     |
| Nit      | 5     |

**Verdict: not ready to merge.**

Every scenario review 2 reported now passes, including all four RV-M1 scenarios, and N7 is sound. But the RV-M1 fix brings in a new major defect (RV3-M1). `owning_sessions` returns the owners of the first ledger entry for a plan number, and that includes entries retired long ago. Two things follow:

- When a plan is reopened by a different session and completed again, the wrong session is retracted.
- Any later edit to a Complete plan that is not yet archived sends signals to every past owner. It can hand a session a `/goal` for a plan it never touched, or type `/goal clear` over that session's manual `inject-goal` goal.

Main does neither of these, so they are regressions. RV-m1 is also only half fixed: the `replace_all` false flip (review 2's m4c) still gives a signal, a "GOAL DISPLACED" advisory and a persisted `displaced_by`. The tests that are meant to pin it use post-edit files the Edit tool could never produce.

## How I verified

**Targeted pytest on the branch passed: 430 tests.** The command ran in the worktree's own venv, and the package imported from the worktree's `src`. The files were `test_goal_injection.py`, `test_goal_ledger.py`, `test_git_facts.py`, `test_recovery_cron_advisor.py`, `test_claude_md_injector.py`, `test_docs_generator.py` and `test_registry.py`. Output: `untracked/scratch/probe_gfv3_pytest_out.txt`.

**Handler-level probes.** Every scenario ran twice, once against the branch source and once against main's `/workspace/src`:

- Each scenario ran in a throwaway root, with `ProjectContext.project_root` and `daemon_untracked_dir` monkeypatched onto that root. No real ledger or sidecar was touched.
- The Edit payloads were applied to disk exactly as the Edit tool applies them, with a uniqueness assertion unless `replace_all` was set.
- Every payload carries `"synthetic_source": "review-goalflip-v3"`.
- "Consumed" means the probe unlinked `.goal-intent` and `.goal-clear`, the same way the supervisor does on read.

All scripts are in `/workspace/untracked/scratch/`:

| Script                                                   | Covers                                                                                                                                                | Output                                                                       |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `probe_gfv3_lib.py`                                      | Shared helpers                                                                                                                                        | —                                                                            |
| `probe_gfv3_handler.py`                                  | A: ownership (A1–A7). B: reassert latch (B1–B5). C: flip detection (C1–C11)                                                                           | `probe_gfv3_handler_branch.txt`, `probe_gfv3_handler_main.txt`               |
| `probe_gfv3_extra.py`                                    | X1 (sessions told about a plan they do not own), X2, X3, RV-m2 (X4), RV-m5 (X5), X6, and D (c40d4ce6 through a real `HandlerChain`)                   | `probe_gfv3_extra_branch.txt`, `probe_gfv3_extra_main.txt`                   |
| `probe_gfv3_x6debug.py`                                  | A non-UTF-8 PLAN.md in a live sibling plan, with tracebacks. This supersedes X6 in the extra probe, whose payloads were applied to disk eagerly       | `probe_gfv3_x6debug_{branch,main}.txt`                                       |
| `probe_gfv3_x7.py`                                       | An `inject-goal` goal wiped by a note on an old Complete plan                                                                                         | `probe_gfv3_x7_out.txt`                                                      |
| `probe_gfv3_n7.py`                                       | N7: `Path.glob` and `pkgutil.walk_packages` both shuffled by a seed, the handler list shuffled, then the CLAUDE.md block and HOOKS-DAEMON.md rendered | `probe_gfv3_n7_branch.txt`, `probe_gfv3_n7_main.txt`                         |
| review 2's `probe_gf_compare.py` and `probe_gf_clear.py` | Re-run unchanged against branch HEAD                                                                                                                  | `probe_gfv3_rerun_review2_compare.txt`, `probe_gfv3_rerun_review2_clear.txt` |

**Not done: real-hook payloads through the worktree daemon.** That daemon is stopped. Starting it would regenerate the worktree's tracked CLAUDE.md, whose block is not what the branch's own code renders (nit RV3-n4), and the daemon auto-commits that regeneration. That breaks the "edit nothing tracked, commit nothing" rule. Review 2 already showed that handler-level results match the real hook path, and nothing in `c40d4ce6` changes the dispatch path.

## Status of review 2's findings

| Finding | Status                                                                         | Evidence (branch)                                                                                                                                                                                                                                                                                                                                        |
| ------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV-M1   | **Fixed** for every scenario reported. It introduced RV3-M1.                   | **A1:** LEAD and TEAMMATE both get `.goal-clear`. **A2:** S2 flips, S3 (busy) touches, S1 reasserts, then each of S1, S2, S3 or a stranger U completes. Every owner is refreshed (`names 00298`), and S3 and U get nothing. **Review 2's M2b and M3b′** now give `names 00298` and `names 00296`. **`probe_gf_clear`:** LEAD's `.goal-clear` is written. |
| RV-m1   | **Fixed without `replace_all`. Not fixed with `replace_all`** (RV3-m1).        | C1 (m4b): no advisory. C4 (`new_string` occurs 3 times): no advisory, where main advises. C2 and C2b (m4c): ADVISORY, and `00302 displaced_by=00300` is persisted.                                                                                                                                                                                       |
| RV-m2   | **Fixed**, but the grace window has no time limit, which feeds RV3-M1.         | X4: an interleaved `live_plan_numbers()` gives `names 00298`.                                                                                                                                                                                                                                                                                            |
| RV-m3   | **Fixed.** One side effect: RV3-m4.                                            | B1 (same session id, restart, signal consumed): `names 00296`. B3 (two restarts): a signal each time.                                                                                                                                                                                                                                                    |
| RV-m4   | **Partly fixed.** New over-claims: RV3-m7.                                     | Release note 13, and the `NIGGLES.md` N3 text and ✅ status.                                                                                                                                                                                                                                                                                             |
| RV-m5   | **Fixed for the ledger file.** The same class remains for PLAN.md (RV3-m8).    | X5: a binary ledger no longer raises, where main raises `UnicodeDecodeError`.                                                                                                                                                                                                                                                                            |
| RV-n1   | **Fixed.** The narrative is now correct, but see RV3-n3.                       | The `pkgutil` mentions now say it is *not* the cause.                                                                                                                                                                                                                                                                                                    |
| RV-n2   | **Resolved by `c40d4ce6`** (propagate, not swallow). The ledger text is stale. | D probes below; RV3-m7.                                                                                                                                                                                                                                                                                                                                  |
| RV-n3   | **Partly fixed.**                                                              | The registry test now asserts `_sorted is False` (`test_registry.py:566,579`). The RV-m1 tests pass through unreachable fixtures (RV3-m1).                                                                                                                                                                                                               |
| N7      | **Holds**                                                                      | 6 adversarial seeds gave one block digest (`438cc720a92fe339`) and one HOOKS-DAEMON.md digest (`0230fb2d58a4e36a`). Main gave 3 distinct digests for 3 seeds.                                                                                                                                                                                            |

**Requirement 6: ordinary ledger edits.**

- **Advisories:** a table-row edit of an In Progress plan never produced an advisory (C9, C9u).
- **Signals:** it does produce one:
  - by design, for a fresh session (the M3 re-assert, as on main);
  - after every daemon restart (as on main);
  - newly, for the flipping session itself within the same daemon lifetime (RV3-m4).

## Blocker

None.

## Major

### RV3-M1 — `owning_sessions` answers from the plan's oldest ledger entry, including long-retired ones: a reopened plan retracts the wrong session, and any edit to a Complete plan re-signals every past owner

**Where:**

- `utils/goal_ledger.py:446-466`: `owning_sessions` returns the `sessions` of the **first** entry for the plan number that is live **or** `retired_reason == RETIRED_TERMINAL_STATUS`, with no time bound.
- `handlers/post_tool_use/goal_injection.py:812-813` and `:957-964`: `_maybe_refresh_on_retirement` runs on **any** write that leaves a plan in a terminal status, not only on the transition to terminal.

**Cause:**

- `record_emission` appends a new entry when a retired plan is reopened. The first lifecycle's retired entry stays earlier in the list, and `_prune` keeps it until the ledger passes 100 entries. So after a reopen, `owning_sessions` returns the **first** lifecycle's owners.
- The terminal grace window added for RV-m2 is unbounded. Any later terminal-state write therefore still finds the retired entry. The retirement path is still triggered by the plan's state, not by a transition, which is the shape N3 exists to remove.

**Failure scenarios** (each is a regression against main):

| Probe   | Steps                                                                                                                                                                                                | Branch                                                                                                                                                                                                                  | Main                                    |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| **A4**  | S1 flips and completes 00296. S2 reopens it (Complete → In Progress, which is regression case R4) and consumes its goal. S2 completes it.                                                            | S2 gets **no** `.goal-clear`, so its `/goal` still names a finished plan (the Plan 00321 "challenges every stop for the rest of the session" failure). S1, which has nothing to do with the reopen, gets `.goal-clear`. | S2 gets `.goal-clear`; S1 gets nothing. |
| **A4b** | As A4, plus 00298 is live and owned only by S3.                                                                                                                                                      | S2 is not refreshed. S1 is handed a new `.goal-intent` naming **00298**, a plan it never touched.                                                                                                                       | S2 gets `names 00298`; S1 gets nothing. |
| **X2**  | S1 flips and completes 00296, and consumes its goal. S3 flips 00298. Later, in a fresh daemon, an unrelated session X adds a completion note to 00296, which is still Complete and not yet archived. | S1 gets `names 00298`: a goal for someone else's plan, from an edit that changed no status.                                                                                                                             | `<no signal>`                           |
| **X7**  | S1 flips and completes 00296. S1 runs `inject-goal` for 00301 (not ledgered), and the supervisor consumes it. X adds a note to Complete 00296.                                                       | S1 gets `.goal-clear`, and the supervisor would type `/goal clear` over S1's manual goal.                                                                                                                               | `<no signal>`                           |
| **A7**  | Same as X2 with no other live plan.                                                                                                                                                                  | S1 gets a fresh `.goal-clear` on every such edit.                                                                                                                                                                       | Nothing                                 |

**Why it matters here:**

- The Plan Completion Checklist puts several edits on a plan after its Complete flip and before the `git mv` into `Completed/`. Each of those edits reaches every session that ever touched the plan.
- Under RV-M1, teammates who ticked a task are owners too.
- Review 2's R4 (reopen) is a named regression case, but no test covers a reopen by a different session followed by completion.

**Fix direction:**

1. Make the retirement refresh transition-based, the same way the flip is. Only a write that moves the plan **into** a terminal status should refresh. Use the Edit's own `old_string`/`new_string`, or HEAD for a Write, with the same machinery as `_is_real_flip_to_in_progress`. This removes X2, X7 and A7 outright. It also makes the RV-m2 grace window safe to keep, because the window then applies only to the entry this write just retired.
2. In `owning_sessions`, prefer the live entry. Otherwise take only the **most recently** retired terminal entry, with the largest `retired_at`. Never take the first one in the list.
3. Add RED tests for A4, A4b and X2.

## Minor

### RV3-m1 — RV-m1 is not fixed for `replace_all`, and its tests use post-edit files the Edit tool cannot produce

**Where:** `goal_injection.py:701-705`; tests at `test_goal_injection.py:1156-1203`.

**Cause:** The `replace_all` branch returns "not a flip" only when `old_string` is still present in the post-edit text. A real `replace_all` always removes every occurrence of `old_string`, so that guard never fires on real input. The branch then reverses **every** occurrence of `new_string`, including ones that were `new_string` before the edit, such as the Status line itself.

**Failure scenario:** C2 and C2b: the plan is already In Progress and has one or two table cells reading `Not Started`. The Edit is `replace_all("Not Started" → "In Progress")`. The branch returns ADVISORY, persists `00302 displaced_by=00300`, and writes a signal. These are N3's full symptoms. Review 2 named this case as m4c.

**Why the tests pass:** Both RV-m1 tests write a post-edit file that still contains `old_string` ("Not Started" in the cell) **and** a Status line reading In Progress.

- For the non-`replace_all` test, that file could only come from an Edit whose `old_string` was not unique.
- For the `replace_all` test, it could not come from any Edit at all.

The tests pass through the "no viable candidate" and "old_string present" early exits, not through the collision logic. So the "Pinned by two RED tests" claim in `NIGGLES.md:490` pins nothing real. The genuine m4b case (C1) passes, but only because the candidates disagree, and no test covers it.

**Fix direction:**

- Under `replace_all`, treat any occurrence of `new_string` that overlaps the post-edit Status line as ambiguous. Compare two verdicts: reverse every occurrence, and reverse every occurrence except that one. If they disagree, the answer is "not a flip".
- Rewrite both tests so the fixture is the file as it really stands after the Edit: apply the edit to a pre-edit fixture.

### RV3-m2 — the "is it In Progress now?" check and the "was it In Progress before?" check use different parsers, so N3's symptoms survive for plans with a second Status line

**Where:**

- `goal_injection.py:219-221` and `:812`: the post-state check is the raw `_STATUS_IN_PROGRESS_RE`, which matches **any** line anywhere, including inside fences, and only the exact literal.
- The pre-state check is `PlanDoc.parse`: the first Status line outside fences, and tolerant of dates and icons.
- The Edit fast path at `:765-767` parses `old_string` as a standalone fragment, with no fence or position context.

**Failure scenarios.** C7b, C8, C8b and X3 all give ADVISORY plus a persisted `displaced_by`. Main behaves the same, so none of this is a regression, but each contradicts the "real transition only" contract:

- **C7b.** A Not Started plan with a fenced example `**Status**: In Progress`. A plain task tick is treated as a flip, because the regex says the plan is In Progress now and PlanDoc says it was Not Started before.
- **C8b.** The same, with a per-phase `**Status**: In Progress` line.
- **C8.** An In Progress plan whose phase-2 `**Status**: Not Started` is edited to In Progress. The fragment's Status line reads Not Started, so it is treated as a flip.
- **X3.** The same, with a bare `old_string` on a fenced example.
- **C11** (a missed flip on both branch and main). A flip to `**Status**: In Progress (2026-09-24)` is never seen, because the regex requires the exact literal.

**Prevalence:** In this repository, 3 of about 400 completed plans have more than one Status line, and the templates have one. So it is rare here. Client templates with per-phase status lines hit it on every edit.

**Fix direction:**

- Decide the post-state with `PlanDoc.parse(plan_text).status is PlanStatus.IN_PROGRESS`, and delete `_STATUS_IN_PROGRESS_RE`.
- In the fast path, accept `old_string`'s Status line only when it is the document's real Status line. Reconstruct the pre-edit text and compare `PlanDoc` before and after, rather than trusting the fragment.

### RV3-m3 — a session whose combined `/goal` names a plan, but which does not own it, is never refreshed when that plan completes

**Where:**

- `_write_combined_signal` (`goal_injection.py:1077-1104`) renders **every** live ledgered plan into whatever session it writes for.
- Ownership only grows through a flip or re-assert of **that** plan.

**Failure scenario:** X1. S1 flips 00296. S3 flips 00298, and S3's signal is `names 00296,00298`. S1 completes 00296. S3 is not refreshed, so its `/goal` still names 00296. Main behaves the same.

**Why it is a finding:** The module docstring (`:62-67`) and release note 13 claim the refresh reaches "EVERY session the ledger ever handed that plan's goal to", and "every owning session's combined `/goal` text, however it reaches that state". X1 shows that claim is false. The impact is low, because the multi-plan wording "until each is complete" can still be satisfied.

**Fix direction:** When `_write_combined_signal` writes a session's signal, add that session to the `sessions` of every live plan it names. Otherwise, narrow the claims.

### RV3-m4 — the RV-m3 re-assert latch is not set by the flip path, and the latch map is unbounded

**Where:** `goal_injection.py:597` and `:1028-1051` (`_reasserted`), and `:847` (the flip path latches `_fired` only).

**Failure scenarios:**

- **B2 and C9.** The session that just flipped a plan adds a table row in the same daemon lifetime. The branch writes a fresh `.goal-intent`, where main writes nothing. This contradicts the brief's requirement that a table-row edit produce no signal, and release note 13's "emits nothing" for a non-flip edit. The supervisor's `last_goal_text` guard should absorb the duplicate. It is still a redundant write, and it takes the ledger lock once per session and plan.
- **B5.** After 400 distinct sessions, `len(_reasserted) == 400`. `_fired` is capped at 256 with FIFO eviction for exactly this reason (`:237-239`).

**Fix direction:** Set `_reasserted[latch_key]` in `handle()` after a confirmed flip write. Route both maps through one bounded `_record_latch` helper.

### RV3-m5 — plan ownership grows without bound, and a terminal write re-signals every owner, dead sessions included

**Where:** `GoalLedgerEntry.sessions` (`goal_ledger.py:103`), `reassert_session` (`:504-516`), and `_maybe_refresh_on_retirement` (`goal_injection.py:960-964`).

**Failure scenario:** A5. 150 teammate sessions each touch one live plan, giving 151 owners. Nothing prunes `sessions`: the 100-entry cap bounds entries, not owners.

- The completing write then takes **0.249 s**, against 0.003 s on main. The cost grows as owners × live plans: each owner does a `live_plan_refs` pass, which reads every live PLAN.md under the lock, and then writes one file.
- It also writes a `.goal-intent` for each of the 150 sessions, naming the lead's four other live plans. Most of those sessions are long gone. Any that is still watched is handed plans it never touched.

The rolling ledger plans here (00466 and its siblings) are touched by dozens of teammates. Ledger N25 already records a slow handler running out the client budget.

**Fix direction:**

- Render once, not once per owner, because the combined text does not depend on the session.
- Cap `sessions`, dropping the oldest after N, or record `last_touched_at` and skip owners idle longer than some window.

### RV3-m6 — the Write path still fires on an already-In-Progress plan that is not committed as In Progress

**Where:** `goal_injection.py:769-772`.

**Failure scenarios** (main behaves the same). In each, S1 flips 00304, S2 flips 00305 (which marks 00304 displaced), and teammate S3 Writes 00304:

- **C5**, where HEAD does not have the file;
- **C5g**, where HEAD reads Not Started because the flip is not committed yet.

Both give ADVISORY "00305 superseded by 00304" and a persisted `00305 displaced_by=00304`.

**Why it is a finding:** Release note 13 says a Write that rewrites an already-In-Progress plan emits nothing. HEAD is not the state before the write, and the window between a flip and its commit is where teammates work. C5h, where HEAD already reads In Progress, is correct.

**Fix direction:**

- Take a snapshot of the PLAN.md status in PreToolUse, keyed by `tool_use_id` (already parsed in `core/input_schemas.py`), and compare it in PostToolUse. That also settles RV3-m1, RV3-m2 and RV3-n5 at their root.
- A cheaper partial fix: a Write to a plan that already has a live ledger entry is never a flip.

### RV3-m7 — the documentation now over-claims in new ways, and N3 is marked Remedied

**Where and what:**

- **`NIGGLES.md:497-503`, the RV-n2 bullet.** It describes the round-1 helper that "catch[es] RuntimeError and logging". `c40d4ce6` reverted that and did not update the ledger.
- **`NIGGLES.md:419-427`.** It names `_session_ledgered_plan`, which no longer exists.
- **`NIGGLES.md:485-491`.** It says the `replace_all` case is fixed and pinned. See RV3-m1.
- **Release note 13.** Three statements are false:
  - "drops it from every owning session's combined `/goal` text, however it reaches that state" (RV3-M1 A4; RV3-m3);
  - "an edit … whose replaced span never touched the Status line emits nothing … THROUGH THE FLIP PATH" (RV3-m1 C2; RV3-m2 C7b and C8b);
  - "a Write that rewrites an already-In-Progress plan" (RV3-m6).
- **`PLAN.md:41` and `NIGGLES.md`.** N3 shows ✅ Remedied.

**Fix direction:** Correct these statements. Hold N3 at 🔄 until RV3-M1 is fixed.

### RV3-m8 — RV-m5 fixed the ledger file, but a non-UTF-8 PLAN.md of any live ledgered plan still crashes the handler, and the branch reaches it on more paths

**Where:** `goal_ledger.py:185-189` (`_plan_state`) and `:158-162` (`_find_plan_md_text`) catch only `OSError`. The same is true of `goal_injection.py:1132-1136` (`_read_plan`).

**Failure scenario:** `probe_gfv3_x6debug`. Plan 00298 is live and its PLAN.md contains byte `0xe9`.

- A fresh session ticking 00296 raises `UnicodeDecodeError` on the branch.
- So does a real flip of another plan, on both branch and main.

The branch adds two new triggers: the re-assert path and the per-owner refresh path. Under `strict_mode: true` (this repo), each is a PostToolUse `SYSTEM ERROR … blocking for safety`, caused by an unrelated plan's bytes.

**Fix direction:** Catch `ValueError` next to `OSError` in these three readers, as `entries()` now does. Treat the plan as unreadable, which never retires it.

## Nit

- **RV3-n1 — `c40d4ce6` is correct and honestly documented. The failure it exposes cannot happen in a real daemon.** Probe D ran a real `HandlerChain` with `ProjectContext` uninitialised:

  | Path               | `strict=True`                                                                                                                   | `strict=False`                 | Main                |
  | ------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------- |
  | Non-flip tick      | `deny`: "SYSTEM ERROR: Handler goal-injection crashed - blocking for safety", with context `Handler exception: RuntimeError: …` | `allow` with that context line | `allow`, no context |
  | Terminal write     | Same                                                                                                                            | Same                           | `allow`, no context |
  | Real flip (caught) | `allow`                                                                                                                         | `allow`                        | `allow`             |

  - The controller initialises `ProjectContext` before `register_all` (`daemon/controller.py:259-267`), so no daemon dispatch reaches this path. Only an in-process caller could.
  - The docstrings (`goal_injection.py:891-902`, `:942-955`) leave one thing out. In strict mode the chain also **stops** at this handler (`core/chain.py:505-511`), so PostToolUse handlers after priority 31 do not run for that event.
  - Cosmetic: `:1051` writes the tuple literal instead of the `latch_key` computed at `:1028`.

- **RV3-n2 — `session_has_entries` (`goal_ledger.py:468-478`) says "EVER recorded", which is not what it does.** `record_emission` overwrites `session_id` with the latest flipper, and `_prune` drops entries.

  - A session whose plan was later re-flipped by someone else therefore counts as new, and can absorb unrelated plans through the re-assert.
  - A session that has only re-asserted also absorbs every live plan it touches (B4: T becomes an owner of 00298). The combined text is global, so this mostly just widens RV3-m5.

- **RV3-n3 — review history in code comments and docstrings.** The project rule is that a comment describes the current state. These passages narrate review rounds instead. `comment_changelog` does not catch them, because they are not keyed to a version.

  - The `_open_ledger` docstring ("RV-n2 (round 1) … round 2 rejected that");
  - `docs_generator.py:210-219` and `claude_md_injector.py:683-690` ("an earlier version of this comment named pkgutil");
  - many "review M3/RV-m3" asides in the module docstring.

- **RV3-n4 — the branch's CLAUDE.md block is main's order, not the order the branch's own code renders.** It was last written by `d23b56f0`, which came in with the main merge. For example, the committed promoted tier starts `sed_blocker, error_hiding_blocker, …`, where the code orders by `promoted_handlers`: `lsp_enforcement, pipe_blocker, sed_blocker, …`. After the merge, the first daemon restart will auto-commit one final reorder. Regenerate before merging.

- **RV3-n5 — a value-only real flip is still missed when "In Progress" also appears as a table cell** (C3b, like m4d's title case C3). Main emits in both. From the Edit payload alone the two pre-edit texts really are indistinguishable, so the conservative answer is defensible. The PreToolUse snapshot in RV3-m6 would remove the ambiguity.

## Recommended order of work

1. RV3-M1: a transition-based retirement refresh, plus `owning_sessions` choosing the right entry, with tests for A4, A4b and X2.
2. RV3-m1: the `replace_all` ambiguity check, with tests built from real post-edit files.
3. RV3-m4: set the re-assert latch in the flip path and bound the map. RV3-m8: catch `ValueError` in the three readers.
4. Correct the ledger and release note (RV3-m7), and regenerate CLAUDE.md (RV3-n4).
5. Later, possibly as a follow-up niggle: a PreToolUse status snapshot keyed by `tool_use_id`. It removes the inference behind RV3-m1, RV3-m2, RV3-m6 and RV3-n5.
