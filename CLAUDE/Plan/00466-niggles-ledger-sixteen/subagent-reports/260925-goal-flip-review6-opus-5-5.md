# Plan 00466 — sixth review of the goal-flip branch (N3)

**Reviewer**: Opus 5.5. Read-only adversarial verification. I edited no tracked file, committed nothing, and did not start or restart a daemon. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `24b64d50`. The fix is `f014cbdb`; `24b64d50` merges main.
**Earlier review**: `260925-goal-flip-review5-opus-5-5.md`. A previous review-6 attempt was cut off; I reran and checked its scratch probes rather than trusting them.

## Findings by severity

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 1     |
| Minor    | 3     |
| Nit      | 4     |

**Verdict: NOT READY.**

All three review-5 majors are fixed, and so are K4, m2, m5 and the `goal_ledger` EACCES half of m6. One new major blocks the merge:

- **RV6-M1.** `markdown_table_formatter` is a PostToolUse handler at priority 26. It rewrites `PLAN.md` before `goal_injection` (priority 31) hashes the file. So the RV5-M2 forward-hash check reports STALE on any write whose markdown is not already in mdformat's canonical form. The fallback then misses real flips that main catches. This project enables all three handlers.

## How I verified

- **Environment.** The branch was run from the worktree venv. Main comparisons used `probe_gf6_main_src/src` and the main venv.
- **Targeted pytest: 224 passed.** The files were `test_goal_injection`, `test_goal_ledger`, `test_plan_status_snapshot` (utils and pre_tool_use), `test_plan_trigger` and `test_qa_package_dependency_direction`. Output: `probe_gf6_pytest_targeted.txt`. I did not run the whole suite.
- **Mutants** were run in a `git archive` copy (`probe_gf6_mut/`):
  - `_snapshot_is_fresh` always False goes RED, on the C3b test.
  - Always True goes RED, on the stale-from-another-session test.
  - Both freshness sides are now pinned.
- **Probes.** All of them are in `/workspace/untracked/scratch/`, and every payload carries `"synthetic_source": "review-goalflip-v6"`.

| Script                                             | Covers                                                                                               | Output                                                                           |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `probe_gf6_rerun.sh` (gf4/gf5 probes against HEAD) | evict2, evict_main, attack, race, rv3 snap/fallback, completer (branch and main), threads, timebound | `probe_gf6_rerun/*.txt`                                                          |
| `probe_gf6_formatter.py`                           | RV6-M1: the real Post chain with and without `markdown_table_formatter`, branch against main         | `probe_gf6_formatter{,_fallback,_main}_out.txt`, `probe_gf6_run2/fmt_branch.txt` |
| `probe_gf6_mdstable.py`                            | How many live PLAN.md files are already formatter fixed points                                       | `probe_gf6_mdstable_out.txt`                                                     |
| `probe_gf6_break.py`                               | Write race, identical Write, overlapping `replace_all`, CRLF, symlinked folder, 300-entry flood      | `probe_gf6_break_out.txt`                                                        |
| `probe_gf6_gate_cost.py`                           | RV5-m1: can the sensor be gated on `goal_injection`, and what does each option cost                  | `probe_gf6_gate_cost_out.txt`                                                    |
| `probe_gf6_ccsearch.py`                            | Claude Code's own Edit/Write implementation (quote normalisation, `userModified`, `staleRecovered`)  | `probe_gf6_cc_*.txt`                                                             |

## Status of review 5's findings

| Finding     | Status                                                                                                           | Evidence                                                                                                                                                                                                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV5-M1      | **Fixed**                                                                                                        | `completer_branch.txt` matches main for K1, K2 and K2b: `<no signal>`, `names 00400`, `names 00400`. The unconditional add is gone (`goal_injection.py:1235`).                                                                                                                                    |
| RV5-m4 (K4) | **Fixed**                                                                                                        | K4: after S3 completes B, S1 gets `<no signal> +clear`. Main keeps a stale `names 00298`. `GoalLedger.add_owners` (`goal_ledger.py:767`) is one lock and one save, and it skips retired entries.                                                                                                  |
| RV5-M2      | **Fixed as specified, but see RV6-M1**                                                                           | The clock is gone: `_snapshot_is_fresh` is a single hash comparison (`goal_injection.py:936`), and the store has no TTL. The `timebound.txt` T6 oracle agrees. With the formatter off, T1, T3, T4 and T7 now resolve correctly (`rv3_snap`: C2r `names 00300`; FT4 formatter OFF: `names 00300`). |
| RV5-M3      | **Fixed**                                                                                                        | `utils/plan_status_snapshot.py` no longer imports `plan_qa`. The `_KNOWN_EDGES` entry is deleted (`test_qa_package_dependency_direction.py:40`), and the test passes.                                                                                                                             |
| RV5-m1      | **Documented, not gated. The stated reason is wrong** (RV6-m1).                                                  | —                                                                                                                                                                                                                                                                                                 |
| RV5-m2      | **Fixed**                                                                                                        | Both the `config-changes/v3.67.0.yaml` entry and the HANDLER_REFERENCE entry are present.                                                                                                                                                                                                         |
| RV5-m3 (K3) | **Documented.** The conclusion holds, but the evidence is incomplete (see the judgement below).                  | K3: L2 keeps `names 00296` and L gets `+clear`. Main keeps both stale, so this is not a regression.                                                                                                                                                                                               |
| RV5-m5      | **Fixed**                                                                                                        | The mutants above. The RV3-m2 pin now uses a unique `old_string`.                                                                                                                                                                                                                                 |
| RV5-m6      | **Mostly fixed.** The `_plan_state`/`_find_plan_md_text` EACCES fix is in. Stale "TTL'd" text survives (RV6-n1). | `plan_status_snapshot.py:13` and `:246`                                                                                                                                                                                                                                                           |
| RV5-n1…n5   | Acceptable as documented. n4 is slightly undercut by RV6-n1.                                                     | —                                                                                                                                                                                                                                                                                                 |

**Rerun of the review-4/5 scenarios.** `rv3_snap.txt` matches review 5 line for line except A2 `completer=U`, which is now `<no signal>` (the RV5-M1 fix). `rv3_fallback.txt` matches too, except that C2r, C3 and C3b give `<no signal>` there, which is expected in fallback mode. evict2, E (49/50/60), F1, F2, G and H all hold. threads: 205,380 iterations and 0 exceptions.

## Major

### RV6-M1 — `markdown_table_formatter` rewrites PLAN.md before `goal_injection` hashes it; the snapshot is thrown away and real flips are missed (a regression against main)

**Where:**

- `constants/priority.py:206`: `MARKDOWN_TABLE_FORMATTER = 26`.
- `:224`: `GOAL_INJECTION = 31`.
- The formatter is non-terminal and formats in place (`markdown_table_formatter.py:182-195`).
- `goal_injection.py:936`: `return hash_plan_text(post_edit_text) == snapshot.predicted_post_hash`, which compares against the formatter's output, not against the tool's.
- `.claude/hooks-daemon.yaml:719-720` enables the formatter in this project, next to `goal_injection` (`:748`) and `plan_status_snapshot` (`:660`).

**Reproducer** (`probe_gf6_formatter.py`; it runs the real `HandlerChain` in priority order and was re-run at HEAD into `probe_gf6_run2/fmt_branch.txt`):

| Case                                                                   | Branch, formatter OFF           | Branch, formatter ON                                              | Main, formatter ON             |
| ---------------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------------------- | ------------------------------ |
| FE: a plain flip Edit whose `new_string` adds an unpadded table        | `names 00300`                   | **STALE, then `<no signal>`: flip missed**                        | `names 00300`                  |
| FT4: a Write reopening Complete→In Progress with an unpadded table     | `names 00300`, live entry       | **STALE, then `<no signal>`, no entry**                           | `names 00300`                  |
| FT3: a Write keeping an unledgered In Progress plan (HEAD Not Started) | `no-advisory`, ledger unchanged | **STALE, then ADVISORY (GOAL DISPLACED), Q `displaced_by=00300`** | ADVISORY (the same N3 symptom) |
| FC3b: a `replace_all` completion that changes column widths            | `+clear`, retired               | **STALE, then `<no signal>`, entry left live**                    | `<no signal>`, live            |

**Why the fallback does worse than main in FE and FT4.** The branch's fallback reverses `new_string` against the text on disk (`_reconstruct_pre_edit_candidates`). The formatter re-padded that text, so `new_string` is no longer in it verbatim. Main's inference does not read the post-image for that decision.

**Why it matters:**

- The live tree is currently all fixed points (`probe_gf6_mdstable_out.txt`: 0 of 39). So a status-only Edit is safe.
- But 17 of the 39 live plans contain tables. A model-authored Write, or an Edit that adds a row, usually types `|---|---|` without padding. mdformat also normalises list markers and numbering. Those writes are exactly the Write, reopen and bulk-edit shapes RV5-M2 set out to rescue.
- In the dogfood configuration they all run on inference again, and FE and FT4 are worse than main.
- No test runs `goal_injection` together with the formatter, so the suite cannot see this.

**Direction:**

1. Run `goal_injection` BEFORE the formatter. Give it a priority below 26, or make the formatter run last among PostToolUse handlers that read `PLAN.md`. Then Post hashes exactly what the tool wrote, and the fallback sees the tool's text too, which fixes FE and FT4 in both modes.
   - If priority cannot move, accept `hash(format_markdown_text(predicted))` as a second fresh value when the formatter is enabled. That couples the two handlers, so prefer ordering.
2. Add a chain-level test with the formatter enabled for FE, FT4 and FC3b. Add a guard test that pins `GOAL_INJECTION < MARKDOWN_TABLE_FORMATTER`, or whatever ordering invariant is chosen, so a later priority shuffle cannot silently reintroduce this.
3. Check every other non-terminal Post handler that can rewrite a `.md` file before priority 31.

## Minor

### RV6-m1 — gating the sensor on `goal_injection` IS possible, and cheap; the NIGGLES justification is false

`NIGGLES.md:1389-1393` says: "No existing primitive in this codebase lets one handler read another's resolved enabled-state at runtime". That is not so. Five handlers already read the whole project config at runtime through `utils/config_cache.load_config_cached(ProjectContext.project_root()/".claude"/"hooks-daemon.yaml")`: `recovery_cron_advisor.py:533`, `cron_stop_enforcer.py:126`, `cron_subagent_stop_enforcer.py:93`, `failsafe_cron_session_advisor.py:113` and `remote_docs_routing.py:109`. The registry's first gate is the public `handlers/registry.config_skip_reason`.

Measured (`probe_gf6_gate_cost_out.txt`):

| Operation                                                                            | Cost            |
| ------------------------------------------------------------------------------------ | --------------- |
| Cached load plus a `handlers.post_tool_use["goal_injection"]` lookup                 | **43 µs/call**  |
| The ungated sensor work on a real 7.9 KB PLAN.md (read, `PlanDoc.parse`, two hashes) | **331 µs/call** |

In a default install (`goal_injection` off), the gate would save about 290 µs per plan write, and the store would stop filling with snapshots nobody consumes.

**Caveats:**

- An absent key has to be resolved together with `GoalInjectionHandler.get_default_enabled()` (False). `config_skip_reason` treats absent as enabled because the default is applied at a later gate.
- `depends_on` really has no consumer, as NIGGLES says. That just isn't the only route.

The cost is small either way, so this stays Minor. But the recorded reason for not doing it is wrong.

**Direction:** Gate `matches()` on the resolved `goal_injection` enabled state, using the config cache, with the default resolved as above. Or keep it ungated and correct the NIGGLES reasoning to "chosen not to", with the measured cost.

### RV6-m2 — a Write's freshness check is blind to a writer that landed BEFORE it, and the docs say it covers Write "uniformly"

For a Write, `would_be_content` returns `content` (`would_be_content.py:37-39`), whatever the pre-image was. So `hash(disk) == predicted` only proves that nobody wrote AFTER the Write. It says nothing about whether the recorded pre-image status is still true.

**Reproducer W1** (`probe_gf6_break_out.txt`): S2's Pre reads Not Started. S1 then flips the plan during S2's prompt, and S2's Write lands.

- The result is "fresh" (no STALE), and S2, which flipped nothing, gets `names 00300` and co-ownership.
- W1e, the same race done with an Edit, is correctly STALE.
- The fallback misattributes it in the same way, so this is not worse than inference.

Claude Code's own "modified since read" guard (`probe_gf6_cc_write.txt`, `recheckBeforeWrite`) probably refuses most such Writes. So the practical exposure is small.

What is wrong is the text:

- `_snapshot_is_fresh`'s docstring (`goal_injection.py:925-932`): "covers every shape uniformly — a Write …".
- Release note 13.
- `NIGGLES.md:1336-1345`.

They claim a detection property that the Write case cannot have.

**Direction:** State the limit in those three places: a Write is verified only against a later writer. Optionally, also record `hash(pre-image)` for a Write and compare it with the Edit tool's `originalFile` if a captured PostToolUse payload proves that field exists. Do not rely on it until one does.

### RV6-m3 — the "narrow window" description of the fallback is now wrong in several places

- `plan_status_snapshot.py:17-20` says inference is kept "for the narrow window where no snapshot exists (a daemon restart … or a payload carrying no `tool_use_id`)".
- `goal_injection.py:898-907` makes a similar claim.

The fallback is also taken on:

- STALE, which includes every non-canonical-markdown write while the formatter is on (RV6-M1);
- NO-PREDICT, when `old_string` is not found verbatim. Claude Code normalises curly quotes before matching (`Pwe` in `probe_gf6_cc_apply.txt`), so a straight-quote `old_string` against a curly-quote plan succeeds in the tool but not in `would_be_content`;
- a user editing the proposal in the permission prompt (`userModified`, `probe_gf6_cc_notfound.txt`);
- a flood that evicts the entry (F1 below).

**Direction:** List the real fallback triggers once, in one place, and point the other docstrings at it.

## Nit

- **RV6-n1 — "TTL'd" survives RV5-m1's claimed removal.** It appears at `plan_status_snapshot.py:13` ("bounded, TTL'd :mod:`utils.plan_status_snapshot` store") and in the acceptance-test description at `:246`. `NIGGLES.md:1395-1396` says it was dropped.
- **RV6-n2 — a stale project-config comment.** `.claude/hooks-daemon.yaml:661` says `plan_status_snapshot` is "Opt-in (false) elsewhere". It ships `enabled: true` (`hooks-daemon.yaml.example:299`).
- **RV6-n3 — a symlinked plan folder is ledgered under the link's number.** In S1, `CLAUDE/Plan/00301-l → 00300-c`, and a flip through the link signals `names 00301`. The snapshot path itself behaves: it is fresh and has no log noise. I did not compare against main. It is an unusual layout.
- **RV6-n4 — the snapshot store still hand-rolls select-then-evict** (`utils/plan_status_snapshot.py:106-107`). It is correct because `_lock` is held, and the merged `unlocked-eviction` semgrep rule exempts `with $LOCK:`. But the merge introduced `BoundedFifoMap` for exactly this, and `goal_injection` now uses it for `_fired`/`_reasserted`. Reusing it would remove a second implementation.

## Judgement on the choices documented rather than changed

- **m1: gating is not impossible** (RV6-m1). The cost of leaving it ungated is about 290 µs per plan write, plus a store that stays full.
- **K3: the conclusion holds, but the search was of the wrong things.**
  - NIGGLES grepped this codebase and the PostToolUse fields. The obvious place to look is SessionStart, whose `source` is `startup|resume|clear|compact|fork` (`remote-docs/.../hooks.md:1166`). None of those carries a parent or previous session id (`:1162-1178`), and `transcript_path` is per-session.
  - The local transcripts under `~/.claude/projects/-workspace/` each carry exactly one `sessionId`, including this long-lived session with many `leafUuid` summary records. That fits `--resume`/`--continue` and compaction keeping the id (`hooks.md:1870` resumes by `<session-id>`).
  - So the new-id case is mostly `/clear` and `fork`, and there really is no link to key on. Documenting it is the right call. NIGGLES should cite the SessionStart schema as the evidence and narrow K3 to `/clear`/`fork`.
- **n1–n5:**
  - n1: the `# nosec` count is net zero against main and inert, so it is fine.
  - n2 and n3: fine.
  - n4: fine, apart from RV6-n1.
  - n5: fine.

## Break attempts

| Attack                                                              | Result                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `replace_all` with overlapping text (`aa`→`b` over `aaa aaaa`)      | Python and JS `replaceAll` are both left-to-right and non-overlapping. The snapshot is fresh and there is no spurious signal (R1).                                                                                                                |
| `replace_all` flip that also hits a body line (R2)                  | Fresh, `names 00300`.                                                                                                                                                                                                                             |
| Edit denied later in the Pre chain (no Post)                        | The orphan is keyed by `tool_use_id`, and a retry gets a new id. G: the store stays at 256 after 5000 orphans. The only Pre handler that rewrites input (`updatedInput`) is `bash_safe_mode`, so no Pre rewrite can desynchronise the prediction. |
| Write of identical content (W2)                                     | Fresh, no signal, no ledger entry.                                                                                                                                                                                                                |
| Concurrent sessions (F1, F3, W1e)                                   | Detected as STALE and correctly resolved. W1, the Write case, is RV6-m2.                                                                                                                                                                          |
| CRLF plan with a single-line or multi-line LF `old_string` (C1, C2) | Fresh, `names 00300`. Both sides read with universal newlines, so CRLF disappears before hashing.                                                                                                                                                 |
| A Write whose `content` itself carries CRLF (C3)                    | STALE (the prediction keeps `\r\n` and the disk read drops it). The fallback still gives `names 00300`. Safe; worth one line in RV6-m3's list.                                                                                                    |
| Relative `file_path`                                                | Not reachable: Claude Code's Write/Edit require absolute paths.                                                                                                                                                                                   |
| Symlinked folder (S1)                                               | The snapshot is fine (RV6-n3).                                                                                                                                                                                                                    |
| Flood: 300 orphan Pres between one call's Pre and Post (F1)         | The entry is evicted, NO-SNAPSHOT, and the fallback still gives `names 00300`. Orphans never leave now that there is no TTL, so the store sits at 256 permanently. The memory is bounded, so this is acceptable.                                  |
| Merge: `BoundedFifoMap` for `_fired`/`_reasserted`                  | Correct. B5 gives `(256, 1)`, and `_record_latch` now only assigns.                                                                                                                                                                               |
| New exclusions or suppressions                                      | None. `error_hiding_exclusions.json` goes from 2 `goal_injection` entries on main to 1. No `noqa`, `type: ignore`, `pragma` or skip marks were added in `f014cbdb`. The only `_KNOWN_EDGES` change is the RV5-M3 deletion.                        |

## Recommended order of work

1. **RV6-M1:** put `goal_injection` ahead of `markdown_table_formatter`, add the chain-level test and the ordering guard, and rerun `probe_gf6_formatter.py`. FE, FT4 and FC3b with the formatter ON should match the formatter-OFF column.
2. **RV6-m1 to m3:** gate the sensor or correct the reasoning, state the Write limit, and list the real fallback triggers.
3. **The nits.** Hold N3 at 🔄.

**Verdict: NOT READY.**
