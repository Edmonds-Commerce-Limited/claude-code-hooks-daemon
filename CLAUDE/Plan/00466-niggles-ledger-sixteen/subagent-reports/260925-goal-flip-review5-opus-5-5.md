# Plan 00466 — fifth review of the goal-flip branch (N3)

**Reviewer**: Opus 5.5. Read-only adversarial verification. I edited no tracked file, committed nothing, and did not start or restart a daemon. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `95ac6de9`. Review-4 base: `f9622e75`.
**Earlier review**: `260924-n466-goalflip-review4-opus-5-5.md`.

## Findings by severity

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 3     |
| Minor    | 6     |
| Nit      | 5     |

**Verdict: NOT READY.**

Most of review 4's fixes hold. E2 and E are fixed, the store is thread-safe, the Edit hash check is exact, and EACCES is wrapped. But three problems block the merge:

- **RV5-M1.** The RV4-M1 half-fix "always refresh the completing session" is a regression against main. A session that never owned the plan, or that carries a manual goal, is handed another plan's `/goal`, or has its own goal cleared. Nothing later retracts that goal.
- **RV5-M2.** The RV4-m2 recency bound is a wall-clock heuristic. It throws away correct snapshots whenever Pre→Post takes longer than 5 s, which includes every permission prompt a person answers. The inference fallback then brings back N3's symptom: a false flip, a `GOAL DISPLACED` advisory and a bogus ledger entry. It also misses a real flip. A backward clock step makes a stale snapshot trusted instead. A design with no time bound exists, and no test pins the bound.
- **RV5-M3.** The `_KNOWN_EDGES` entry for `utils/plan_status_snapshot.py` is a new QA exclusion. The list says "never grow it to make a new edge pass", and the import is avoidable.

## How I verified

- **Environment.** Everything ran from the worktree venv (`untracked/venv-workspace_untracked_worktrees_worktr-0f21-py311-81c29529`). Main comparisons ran from `/workspace/src` (main at `86d90fa0`) with `untracked/venv-workspace-py311-81c29529`.
- **Probe roots.** All of them sit under `/workspace/untracked/scratch/probe_gf5_rerun/`. `ProjectContext` was monkeypatched onto each root, and every hand-built payload carries `"synthetic_source": "review-goalflip-v5"`.
- **Targeted pytest: 658 passed.** The files were `test_goal_injection`, `test_goal_ledger`, `test_plan_status_snapshot` (utils and pre_tool_use), `test_plan_trigger`, `test_git_facts`, `test_recovery_cron_advisor`, `test_qa_package_dependency_direction`, `test_claude_md_guidance_coverage`, `test_default_enabled_template_consistency`, `test_reference_config_completeness`, `test_eacces_safe_predicates_static_check` and `test_check_generated_doc_drift`. Output: `probe_gf5_pytest_targeted.txt`.
- **`scripts/qa/audit_error_hiding.py`: 0 violations.** Output: `probe_gf5_audit_error_hiding.txt`.
- **Suppressions.** `git diff f9622e75..95ac6de9` adds no `noqa`, `type: ignore` or `pragma`, and no error-hiding exclusion. It adds one `# nosec` in `tests/support/git_fixtures.py:17`, which replaces three (see RV5-n1). It adds one `_KNOWN_EDGES` entry (RV5-M3).

The scripts, all in `/workspace/untracked/scratch/`:

| Script                                             | Covers                                                                                                        | Output                                  |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `probe_gf4_{evict2,evict_main,attack,race,rv3}.py` | Review-4 probes rerun against HEAD (`probe_gf4_threads2.py` no longer runs: `record()` now takes 3 arguments) | `probe_gf5_rerun/*.txt`                 |
| `probe_gf5_lib.py`                                 | Wrapper around `probe_gf4_lib`, re-tagged v5. Adds a DELAYED Pre→Post step by ageing the recorded snapshot    | —                                       |
| `probe_gf5_timebound.py`                           | RV5-M2 (T1–T7)                                                                                                | `probe_gf5_timebound_out.txt`           |
| `probe_gf5_completer.py`                           | RV5-M1, RV5-m3, RV5-m4 (K1–K4), branch against main                                                           | `probe_gf5_completer_{branch,main}.txt` |
| `probe_gf5_threads.py`                             | The RV4-m1 lock: stress, hold time and re-entrancy                                                            | `probe_gf5_threads_out.txt`             |
| `probe_gf5_mutate.py`                              | 7 mutants in a `git archive` copy of HEAD (`probe_gf5_mut/`)                                                  | `probe_gf5_mutate_out.txt`              |
| `probe_gf5_eacces.py`                              | RV5-m6: an unsearchable plan folder, run under `setpriv` without the DAC capabilities, branch against main    | `probe_gf5_eacces_out.txt`              |
| `probe_gfv3_n7.py` + `probe_gf5_docdiff.py`        | RV4-m6: renders the docs from the branch's code and diffs them against the committed files                    | `probe_gf5_docdiff_out.txt`             |

## Status of review 4's findings

| Finding   | Status                                                                                                                    | Evidence                                                                                                                                                                                                                                                                                           |
| --------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV4-M1    | **E2/E fixed. The completer half is a regression (RV5-M1). A resumed lead is still evictable (RV5-m3).**                  | `evict2`: L gets `names 00298` at n=10 and n=50. `evict_main_branch`: `refreshed=True names00296=False`. `attack` E: L is retracted at n=49, 50 and 60, and for either completer.                                                                                                                  |
| RV4-m1    | **Fixed**                                                                                                                 | `probe_gf5_threads`: 4 threads, 38,568 iterations, 0 exceptions. No I/O runs under the lock (only `time.time()` and dict operations). No method acquires the lock twice. The worst hold is 16.8 µs (`record` on a full store). The lock-removal mutant goes RED.                                   |
| RV4-m2    | **Fixed for a non-`replace_all` Edit. The Write and `replace_all` halves are defective (RV5-M2).**                        | F3 (`race.txt`): snap mode now matches fallback. `00304` is no longer displaced and `00300` keeps `displaced_by=00304`. F2: `<no signal>`. T2: the value-only flip is detected at 0, 60 and 290 s.                                                                                                 |
| RV4-m3    | **Fixed for the ledger file and the Pre handler.** A sibling shape remains (RV5-m6, pre-existing).                        | Rerun of `probe_gf4_eacces`: `entries()` gives `[]`, `session_has_entries()` gives `False`, and Pre `handle()` gives `allow` with a WARNING.                                                                                                                                                       |
| RV4-m4    | **Default flipped. Upgrade-manifest and doc gaps remain (RV5-m2). The docstring's harmlessness claim is false (RV5-m1).** | See those findings.                                                                                                                                                                                                                                                                                |
| RV4-m5    | C7b/C8 fixtures fixed. The new RV3-m2 pin uses an Edit no tool can produce (RV5-m5).                                      | I did not rerun the literal-substring mutant.                                                                                                                                                                                                                                                      |
| RV4-m6    | **Fixed**                                                                                                                 | Rendering the docs from the branch's code gives the same built-in handler lines as the committed CLAUDE.md block and HOOKS-DAEMON.md. The only diff is project and plugin handlers, which the render harness does not load (`probe_gf5_docdiff_out.txt`). `test_check_generated_doc_drift` passes. |
| RV4-m7    | Partly fixed. New over-claims are in RV5-m6.                                                                              | —                                                                                                                                                                                                                                                                                                  |
| RV4-n1…n7 | n2, n3, n5 and n7 are fixed. n4 consolidated three suppressions into one (RV5-n1). n1 and n6 are acceptable.              | `attack` H: a symlink-loop PLAN.md records nothing and does not raise. ENAMETOOLONG gives `allow` under both strict modes.                                                                                                                                                                         |

**Rerun of the review-3/4 scenarios (`rv3_snap.txt`, `rv3_fallback.txt`).** Every line matches review 4's output in both modes except one, which is RV5-M1's reproducer:

```
[br/snap]     A2 completer=U: S1|S2|S3|U   names 00298 | names 00298 | names 00298 | <no signal>
[branch/snap] A2 completer=U: S1|S2|S3|U   names 00298 | names 00298 | names 00298 | names 00298
```

## Blocker

None.

## Major

### RV5-M1 — "always refresh the completing session" gives a non-owner a `/goal` it never had, and wipes a manual goal (regression against main)

**Where:** `src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py:1229-1235`:

```python
        if session_id and session_id not in owners:
            owners = [*owners, session_id]
```

The retirement fan-out then writes the combined text of the remaining live plans to that session (`:1253-1254`), or clears its goal when no plan is left live (`:1240-1243`). It does not register the session as an owner of the plans that text names: `_extend_ownership` is skipped on this path by design (`:1428-1434`).

**Reproducers** (`probe_gf5_completer.py`; branch against main):

| Case                                                                            | Branch                                         | Main          |
| ------------------------------------------------------------------------------- | ---------------------------------------------- | ------------- |
| K1: U has no goal and owns nothing. U completes 00296 while 00298 is live.      | U gets `names 00298`                           | `<no signal>` |
| K1, continued: S3 then completes 00298                                          | U still has `names 00298`, **permanently**     | `<no signal>` |
| K2: U holds an `inject-goal 00400` goal and completes 00296, the only live plan | `<no signal> +clear`: the manual goal is wiped | `names 00400` |
| K2b: same as K2, but 00298 is live too                                          | `names 00298`: the manual goal is replaced     | `names 00400` |

The same change shows up in `rv3_snap.txt` A2 as `completer=U: … | names 00298`.

**Why it matters:**

- **K1 is the everyday case in this project's workflow.** A coordinator with no goal of its own performs a teammate's Plan Completion Checklist, and its first touch of that plan is the Complete flip. The supervisor then types a `/goal` naming every other teammate's live plan into the coordinator's chat. Because the coordinator was never made an owner of those plans, their later completion never retracts it.
  - That combines N3's original harm ("a goal for a plan nobody started") with Plan 00321's ("a finished plan challenges every stop").
- **K2 turns the `.goal-clear` trigger on a session whose goal the daemon never set.** The supervisor types the clearing form, which also clears a goal a person typed by hand.
- The only test for the change (`test_goal_injection.py:2421-2455`) builds its case by hand-corrupting the ledger JSON. No test pins the negative case.
- Release note 13 (`:49-53`) advertises the behaviour.

**Direction:**

1. Remove the unconditional inclusion. The `primary_owner` pin already fixes E2 on its own: in `probe_gf5_mutate`, the "completer NOT added" mutant turns only the corrupt-ledger test RED.
2. If a completer really must be covered after it has been evicted, record evictions: add an `evicted_owners` list on the entry and refresh `owners ∪ evicted_owners`. Include the completer only when it is in that union.
3. Add RED tests for K1 and K2: a non-owner completer's signal and a manual signal must be untouched.

### RV5-M2 — the 5 s recency bound discards correct snapshots and trusts stale ones; a design with no time bound exists

**Where:**

- `goal_injection.py:250-256`: `_SNAPSHOT_RECENCY_BOUND_SECONDS = 5.0`.
- `:966-975`: the Write, `replace_all` and empty-candidate path returns `(time.time() - snapshot.recorded_at) <= 5.0`.
- `utils/plan_status_snapshot.py:116` and `:147`: `time.time()`, a wall clock, sets both `recorded_at` and the TTL.

PreToolUse runs before the permission prompt. `/workspace/remote-docs/code.claude.com/docs/en/hooks.md:2039` says PostToolUse's `duration_ms` "Excludes time spent in permission prompts and PreToolUse hooks". So the Pre→Post gap includes the prompt.

**Reproducers** (`probe_gf5_timebound_out.txt`; "delay" ages the recorded snapshot):

| #   | Scenario                                                                                                                                                                                                                            | 0 s                              | ≥ 6 s                                                                                                                         |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| T1  | A genuine bulk `replace_all` flip (status plus a cell)                                                                                                                                                                              | `names 00300` (also at 4.9 s)    | `<no signal>`: **real flip missed**                                                                                           |
| T3  | A Write that leaves an unledgered plan at In Progress. HEAD reads Not Started, as it does whenever the flip landed while `goal_injection` was not recording (the handler was off, a Bash edit, a lost ledger). Q is S0's live goal. | `no-advisory`, ledger unchanged  | **`ADVISORY` (GOAL DISPLACED)**, Q `displaced_by=00300`, S1 ledgered and signalled `names 00300,00302`: N3's full symptom set |
| T4  | A Write reopening a Complete plan (Complete→In Progress, HEAD In Progress)                                                                                                                                                          | S1 `names 00300`, new live entry | `<no signal>`, no entry: **real flip missed**                                                                                 |
| T2  | A non-`replace_all` value-only flip                                                                                                                                                                                                 | `names 00303`                    | `names 00303` at 60 and 290 s: the hash path is time-free                                                                     |

T5 checks what the wall clock does:

- A snapshot recorded "in the future" (clock stepped back 1 h) is judged **fresh**, and the store keeps it past its 300 s TTL. Every stale snapshot then looks fresh for the size of the step.
- A 6 s forward step on an unchanged file makes the snapshot stale.

T7: a non-`replace_all` Edit with an empty `new_string` (a deletion) gives no candidates (`_reconstruct_pre_edit_candidates` returns `[]`). It therefore silently takes the time path. A snapshot of a *different* file 0 s old is judged fresh.

**Why it matters:**

- In default permission mode, every PLAN.md Write and `replace_all` Edit that prompts a person runs on inference and logs a WARNING. So the release note's claim that the snapshot is "the common case" (`:28-31`) is false for those modes.
- The fallback is the machinery N3 replaces, with its documented misses (C2r, C3, C3b) and HEAD-lag false flips (T3).
- The bound is not pinned. In `probe_gf5_mutate`, the "recency bound never expires" mutant is **GREEN** (195 passed). Only the opposite mutant (bound 0 s) is RED, via the `replace_all` C3b test.

**A time-free design.** Freshness is a question about bytes, not time. Pre already has the pre-image and the call's `tool_input`, so it can predict the post-image exactly:

- **Write:** `content`.
- **Edit:** `pre.replace(old, new, 1)` after a uniqueness check, or `pre.replace(old, new)` for `replace_all`.

Record `hash(predicted post-image)` alongside the status. In Post, the snapshot is fresh if and only if `hash(disk) == predicted`.

- A forward application is unambiguous where a reverse reconstruction is not.
- It covers Write, `replace_all` and deletions alike.
- It needs no clock.
- Any mismatch (another writer, a Pre handler's `updatedInput`, an Edit-tool normalisation) degrades safely to the fallback.
- T6 checks the oracle on the same shapes. It answers fresh for a `replace_all` bulk flip and for a Write at any delay. It answers stale for "another writer landed" in both cases and for F3, and it covers the deletion Edit.

The existing key is right: `tool_use_id` is documented on both the PreToolUse and PostToolUse inputs (`hooks.md:1613`, `:2032`). No captured real Edit/Write PostToolUse payload exists in the repo (`/workspace/untracked/payload-capture/` holds only `Status.jsonl`, and `grep originalFile tests/ src/` is empty). So do not reach for `tool_response` pre-image fields without capturing one first.

A related claim does not rescue the time bound. Claude Code's Edit and Write tools are widely understood to refuse a write to a file modified since the session's last Read. If true, the cross-session race in RV4-m2 mostly ends in a failed call, with no PostToolUse. But I found nothing in `remote-docs/` that says so, so do not rely on it. It does not help with the false discard (T1, T3, T4), which needs no concurrent writer at all.

**Direction:** Replace `_snapshot_is_fresh`'s time branch, and the reverse-candidate branch, with the forward-image hash. Use `time.monotonic()` for the store TTL. Add tests for a Write and a `replace_all` delayed past any bound (still trusted) and for a raced Write (discarded).

### RV5-M3 — the new `_KNOWN_EDGES` entry is a QA exclusion, and it is avoidable

**Where:** `tests/integration/test_qa_package_dependency_direction.py:43-48` adds `utils/plan_status_snapshot.py -> plan_qa.model`. The list's own contract, at `:36-37`, says: "Shrink this list when one goes; never grow it to make a new edge pass."

**Comparison with the precedent** (`goal_ledger.py`, `:39-42`):

- That entry records an unresolved question ("Whether a plan-shaped utility belongs in utils at all is the open question").
- It predates the ratchet.
- `goal_ledger` uses `PlanDoc` for real: it parses plan text in `_plan_state` (`goal_ledger.py:273-280`).

`utils/plan_status_snapshot.py` parses nothing. It imports `PlanStatus` (`:54`) only to annotate the `status` field and parameter (`:83`, `:104`). The parsing happens in the Pre handler (`handlers/pre_tool_use/plan_status_snapshot.py:121`), which is outside the ratcheted trees.

**Verdict:** this is a new exclusion added to make a new edge pass, and the standing rule forbids it.

**Direction** (any one of these removes the edge):

1. Make the store generic over the status type, `PlanStatusSnapshotStore(Generic[T])`, and instantiate it in the handler layer.
2. Store `status.value` (a `str`) and re-hydrate it with `PlanStatus(value)` in `goal_injection`.
3. Move the store module out of `utils/`, next to its only two users, for example `handlers/_shared/plan_status_snapshot.py`.

Then delete the entry, which `test_every_declared_edge_still_exists` will demand. Also fix the module docstring's "the five that remain" (`:16`); the list now has 3 entries.

## Minor

### RV5-m1 — default-on runs the sensor in every client on every PLAN.md write, and its "harmless" claim is false

`handlers/pre_tool_use/plan_status_snapshot.py:33-36` says the handler is "Harmless when goal_injection is off: `get_relevance` still gates it to an armed ccy PTY supervisor". But `get_relevance` is not a runtime gate:

- Its only caller is `config_optimisation/checklist.py:128`, the `/hooks-daemon optimise` review.
- Its contract (`core/handler.py:409-419`) is "worth it, knowing the project".

`goal_injection` ships disabled (`goal_injection.py:698`). So the default configuration reads, parses and SHA-256-hashes every PLAN.md before every Write or Edit, and records a snapshot that nothing consumes. The store sits at its 256-entry cap. The cost is small (review 4 measured about 0.2 ms per plan Edit), but it is pure waste, and the stated reason it is harmless is wrong.

**Upgrade impact.** None, because `config_skip_reason` treats an absent key as ENABLED (`handlers/registry.py:224-236`). Every existing client was already running the sensor before the flip. The flip changed the template and the docs, not the behaviour.

**Direction:** Gate at runtime on `goal_injection` being enabled, for example via the resolved handler config that `project_loader` and the registry already have. Otherwise correct the docstring and the release note to say the sensor runs unconditionally.

### RV5-m2 — the new handler has no config-changes manifest entry and no HANDLER_REFERENCE entry

- **Manifest.** `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.67.0.yaml` lists only `plan_journal_guard`, a new handler in the same release. `plan_status_snapshot` is missing. `UNRELEASED/config-changes/README.md` requires an entry for a new key, so `check-config-migrations` will not mention the handler on upgrade.
- **Reference.** `docs/guides/HANDLER_REFERENCE.md` still has no entry. Review 4's RV4-m4 direction asked for one.

### RV5-m3 — only the original session id is pinned; a resumed lead is still evicted

`primary_owner` protects one session id (`goal_ledger.py:183`). A lead that resumes under a new id and reasserts is an absorbed owner.

**Reproducer (K3):** L flips 00296. L2 (L resumed) ticks it and gets `names 00296`. Then 50 teammates tick it, and TM049 completes the plan.

- **Branch:** L2 keeps `names 00296` (evicted), while the dead id L gets `+clear`.
- **Main:** both stay stale, so this is not a regression.

But release note 13 (`:69-72`) claims the cap "can never evict the one session that most needs its own signal refreshed".

**Direction:** Make eviction least-recently-touched: move an owner to the end on every touch, as RV4-M1's direction 2 asked. Also consider the `evicted_owners` idea from RV5-M1.

### RV5-m4 — the retirement fan-out leaves the owners it refreshes out of the plans their new text names

**Reproducer (K4):** S1 flips A and S3 flips B. S1 completes A, and gets `names 00298`. S3 then completes B, and S1 **still** has `names 00298`. The same happens on main.

This breaks RV3-m3's own invariant: "a session reading a plan's number in its own text" must be refreshed when that plan completes. RV5-M1 widens the hole to sessions that owned nothing at all.

**Direction:** In `_maybe_refresh_on_retirement`, register every refreshed session as an owner of every plan named in the text it was sent. Do it as ONE batched ledger mutation, `add_owners(sessions, plan_numbers)` under a single lock, which answers RV3-m5's cost concern.

### RV5-m5 — test gaps in the review-4 fixes

`probe_gf5_mutate_out.txt`:

| Mutant                                                                           | Result                                                    |
| -------------------------------------------------------------------------------- | --------------------------------------------------------- |
| The recency bound never expires                                                  | **GREEN** (see RV5-M2)                                    |
| A re-emission hands `primary_owner` to the re-emitter (`goal_ledger.py:581-583`) | **GREEN**                                                 |
| Remove the completer inclusion                                                   | RED on one test, whose premise is a hand-corrupted ledger |
| `_snapshot_is_fresh` always True                                                 | RED                                                       |
| `primary_owner` not protected                                                    | RED                                                       |
| Lock removed                                                                     | RED                                                       |

Two tests have fixture problems:

- **The RV3-m2 pin** (`test_goal_injection.py:2497-2511`) dispatches an Edit whose `old_string` (`**Status**: In Progress`) occurs twice in its own pre-image: the real line and the fenced example. The Edit tool rejects that. Every reconstruction candidate is therefore filtered out, and the test passes only through the 5 s time path. This is the same fixture-realism defect class as RV3-m1 and RV4-m5.
- **The C3b snapshot test** (`:1578-1611`) is a `replace_all` Edit. It also depends on the time path. It goes RED only when the bound is 0 s.

**Direction:** Pin both the accept and the reject side of freshness. Use a fenced example whose text differs from the real Status line, so the Edit is producible.

### RV5-m6 — documentation over-claims

- **Release note 13, `:23-31`**: says a snapshot "is discarded … if the file it actually modified no longer matches". For a Write or a `replace_all` Edit there is no match check, only a 5 s clock (RV5-M2).
- **Release note 13, `:49-53`**: advertises RV5-M1.
- **Release note 13, `:69-72`**: see RV5-m3.
- **`NIGGLES.md:931-935`** says RV4-m3 "is what makes that catch actually complete (an EACCES no longer escapes it unwrapped)". It does not:
  - `goal_ledger.py:265` (`_plan_state`) and `:234` (`_find_plan_md_text`) keep a raw `plan_md.is_file()` outside their `try`.
  - `probe_gf5_eacces_out.txt`: a live ledgered plan whose folder denies search makes `live_plan_numbers()` raise `PermissionError`. Main does the same, so the defect is pre-existing, but the claim is not true, and `auto_continue_stop` relies on `live_plan_numbers` failing open.
- **`NIGGLES.md:906-912`** says the RV4-m6 regeneration found "no diff". `:1019-1023` of the same entry then says HOOKS-DAEMON.md was still stale. Separately, commit `6d63971a` auto-regenerated 570 lines of CLAUDE.md. Reconcile the two sentences.
- **`handlers/pre_tool_use/plan_status_snapshot.py:33-36`**: see RV5-m1.

## Nit

- **RV5-n1 — the consolidated `# nosec` suppresses nothing.**
  - `tests/support/git_fixtures.py:17` keeps one `# nosec B603 B607`.
  - Every bandit surface scans only `src/` (plus the supervisor script): `scripts/qa/run_security_check.sh:36`, and `pyproject.toml:256-262` documents all three. So the comment was inert in all three old locations too.
  - Removing it did not move a subprocess call to an unscanned place, because tests were never scanned. The call is genuinely safe: list form, a fixed `git` binary, `check=True` and a timeout, in test-only code.
  - "Removed" in the brief is inaccurate. It went from 3 to 1, which is net zero against main. It could go entirely.
- **RV5-n2 — the legacy `primary_owner` back-fill uses `session_id`** (`goal_ledger.py:423-427`). That field is the *last* re-emitter, not the creator. It is a documented approximation that applies only to pre-upgrade entries.
- **RV5-n3 — a directory named `PLAN.md` records "no prior status"** (`attack` H: `status=None`). `path_is_file` answers False for a directory. The Write would fail, so there is no Post and no effect.
- **RV5-n4 — the new docstrings keep narrating review rounds.** Examples: the module docstring at `utils/plan_status_snapshot.py:1-45` ("previously had to INFER", RV4-m1/m2 paragraphs) and `_snapshot_is_fresh`. Most of this is rationale keyed to failure modes, which is allowed, but it adds length.
- **RV5-n5 — `threads2` probe breakage is expected.** `probe_gf4_threads2.py` calls the old 2-argument `record()`. That is not a defect; it is superseded by `probe_gf5_threads.py`.

## Things I attacked that held

- **RV4-M1 E2/E.** L survives 50 and 60 absorbed teammates and is refreshed by either completer.
  - **Bounds.** Entries are capped at 100 (retired entries are pruned first) and owners at 50 including the pin. The only way the owner list grows past the cap is `cap == 1`.
  - **Release.** The pin is released with the entry, on retirement and then pruning.
  - **Plan archived without a terminal write (`git mv`).** Nobody is refreshed, but that is pre-existing and outside the Plan Completion Checklist.
  - **Session end.** It has no ledger hook; that is pre-existing. A dead primary owner costs one file write when its plan completes.
- **The lock.**
  - It is held only around dict operations and `time.time()`, with no I/O, logging or callbacks under it.
  - `consume()` calls `consume_snapshot()` outside the lock, so nothing acquires it twice.
  - `GoalLedger._locked` uses per-open-file-description `flock`, which excludes threads, and the store lock is never held while it is taken. So there is no lock-order deadlock.
- **The non-`replace_all` Edit hash check.** It is exact, it is immune to delay (T2), and it catches F3.
- **Denied or failed calls (Pre without Post).** The orphaned snapshot is keyed by `tool_use_id`, capped at 256 and TTL-evicted, and cannot reach another call (`attack` G).
- **`is_inside_project`.** A symlink loop reads as "not inside" (RV4-n7).
- **Latency.** `matches()` takes 0.4 µs on Bash and 2.9 µs on a non-plan Edit. `matches()` plus `handle()` takes 331 µs on a plan Edit.
- **Regressions in other behaviours.** None beyond RV5-M1. The A-, B-, C- and X-series are identical to review 4 in both modes. The RV4-n2 delegation to `matched_plan_write_or_edit` keeps the `/Completed/` exclusion and the project-membership check.

## Recommended order of work

1. **RV5-M1:** drop the unconditional completer inclusion, and add the K1/K2 RED tests. RV5-m4 is cheapest to fix in the same change.
2. **RV5-M2:** replace the time bound with the forward-image hash, move the TTL to a monotonic clock, and pin both freshness sides.
3. **RV5-M3:** remove the `utils → plan_qa` edge and delete the `_KNOWN_EDGES` entry.
4. **RV5-m1 and RV5-m2:** gate or document the sensor honestly, and add the config-changes and HANDLER_REFERENCE entries.
5. **RV5-m3, RV5-m5 and RV5-m6:** LRU eviction, the test fixtures, and the documentation. Hold N3 at 🔄.

**Verdict: NOT READY.**
