# Plan 00466 — seventh review of the goal-flip branch (N3)

**Verdict: NOT READY** — 1 BLOCKER, 1 MAJOR, 4 MINOR, 3 NIT.

**Reviewer**: Opus 5.5, adversarial and read-only. No tracked file edited, nothing committed, no daemon started or restarted. This report is the only file written inside the worktree.
**Branch**: `worktree-n466-goal-flip` at HEAD `88991a06` (the review-6 fix commit).
**Earlier review**: `260925-goal-flip-review6-opus-5-5.md`.
**Probes**: all under `/workspace/untracked/scratch/probe_gf7/` (plus `probe_gf7_*` outputs there). Every hand-built hook payload carries `"synthetic_source": "review-goalflip-v7"` (the rerun of review 6's formatter probe keeps its own `review-goalflip-v6` stamp).

## Findings by severity

| Severity | Count | IDs                  |
| -------- | ----- | -------------------- |
| Blocker  | 1     | RV7-B1               |
| Major    | 1     | RV7-M1               |
| Minor    | 4     | RV7-m1 to RV7-m4     |
| Nit      | 3     | RV7-n1 to RV7-n3     |

## Status of review 6's findings

| Finding | Claimed | Verified                                                                                                                                                                                                                                                                                                                                  |
| ------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RV6-M1  | Fixed   | **Fixed in behaviour, but the renumbering broke 4 unit tests (RV7-B1) and one of the two new chain tests is not RED against the old order (RV7-m2).** The real PostToolUse chain orders goal_injection (30) before the formatter (31) from all four config sources, with no priority collisions (`postorder_out.txt`). Review 6's `probe_gf6_formatter.py` rerun at HEAD: FE, FT4 and FC3b with the formatter ON now match the formatter-OFF column exactly, and no STALE is logged (`formatter_head.txt`). The FT3 "ADVISORY" in the ON column is the formatter's own "Reformatted markdown in PLAN.md" message, not GOAL DISPLACED (`ft3_ctx.txt`). |
| RV6-m1  | Fixed   | **Gated, but in the wrong place and on the wrong source of truth** (RV7-M1, RV7-m1).                                                                                                                                                                                                                                                      |
| RV6-m2  | Fixed   | Fixed. The `_snapshot_is_fresh` docstring (`goal_injection.py:990-1012`) and release note 13 now state the Write limitation accurately.                                                                                                                                                                                                   |
| RV6-m3  | Fixed   | Mostly fixed. The list at `goal_injection.py:909-943` is good but omits one trigger this very commit introduced (RV7-n3).                                                                                                                                                                                                                 |
| RV6-n1  | Fixed   | Fixed.                                                                                                                                                                                                                                                                                                                                    |
| RV6-n2  | Fixed   | Fixed.                                                                                                                                                                                                                                                                                                                                    |
| RV6-n3  | "Harmless, no Direction" | **Not harmless: a real defect, reproduced** (RV7-m3). It predates this branch, but "no Direction given" does not close it.                                                                                                                                                                                                  |
| RV6-n4  | Fixed   | Fixed and equivalent. A differential test of the old hand-rolled store against the `BoundedFifoMap`-backed one ran 200 random record/consume sequences, including re-insert of a live key, a full store, empty ids and capacities 1/2/3/7/256. Contents, order and every consume result were identical (`probe_gf7_store_diff.py`, `store_diff_out.txt`). |

## Blocker

### RV7-B1 — the renumbering broke four PostToolUse unit tests; the branch is red

**Where:**

- `tests/unit/handlers/post_tool_use/test_command_hints.py:46`: `assert handler.priority == 29`, now 28.
- `tests/unit/handlers/post_tool_use/test_git_hooks_executable_fixer.py:61`: `== 27`, now 26.
- `tests/unit/handlers/post_tool_use/test_background_process_tracker.py:46`: `== 28`, now 27.
- `tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py:175`: `test_priority_is_30`, now 29.

RV6-M1's fix renumbered four handlers it did not need to touch semantically (`constants/priority.py:205-218`) and never ran their tests.

**Reproduction:**

```
.venv/bin/python -m pytest -q -o addopts="" \
  tests/unit/handlers/post_tool_use/test_command_hints.py \
  tests/unit/handlers/post_tool_use/test_git_hooks_executable_fixer.py \
  tests/unit/handlers/post_tool_use/test_background_process_tracker.py \
  tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py
```

The full targeted batch (12 files) gives **4 failed, 492 passed** (`pytest_targeted.txt`). The failures are `assert 28 == 29`, `assert 26 == 27`, `assert 27 == 28` and `assert 29 == 30`.

**Direction:**

- Change the four assertions to compare against the constant (`Priority.COMMAND_HINTS`, and so on) rather than a literal. Rename `test_priority_is_30` accordingly.
- Before re-claiming "fixed", run every test module of every handler whose priority moved.

## Major

### RV7-M1 — the RV6-m1 gate runs BEFORE the cheap trigger match, so every PreToolUse event now pays a config stat, and an unparseable config costs about 80 ms per tool call

**Where:** `handlers/pre_tool_use/plan_status_snapshot.py:173-178`.

```python
if not self._goal_injection_enabled():
    return False
return matched_plan_write_or_edit(hook_input, self._project_layout) is not None
```

`HandlerChain` calls every registered handler's `matches()` on every event (`core/chain.py:431`), and this sensor ships enabled in every client. So the gate's `Path.resolve()`, `stat()` and lock now run on every Bash, Read, Grep and other PreToolUse call. Before this commit, those calls cost a tuple membership test.

When the YAML cannot be parsed, `load_config_cached` raises and caches nothing (`utils/config_cache.py:74-82`). `_load_config` then swallows the error and returns defaults (`plan_status_snapshot.py:127-132`), so the next event re-reads and re-parses the whole file. The daemon keeps running on the config it loaded at startup, so a config broken by an edit after startup is a live state until the next restart.

The test at `test_plan_status_snapshot.py:342` (`test_gate_runs_before_the_trigger_match_so_a_non_plan_write_is_still_false`) pins the ordering by name.

The established idiom does the opposite. `remote_docs_routing._read_target` says "a prefix test before any file I/O … the overwhelming majority of Reads are nowhere near this tree".

**Reproduction** (`probe_gf7_gatecost.py` → `gatecost_out.txt`; the host is overloaded, so compare ratios, not absolutes):

| Payload                                  | Before RV6-m1 (trigger match only) | At HEAD             |
| ---------------------------------------- | ---------------------------------- | ------------------- |
| Bash, real project config                | 0.9 µs/call                        | 117.0 µs/call       |
| Read, real project config                | —                                  | 154.5 µs/call       |
| Bash, syntactically broken YAML          | 0.9 µs/call                        | **80,400 µs/call**  |

The gate was added to save about 290 µs per **plan write** in installs where goal_injection is off. Instead it charges about 100 µs to **every** PreToolUse event in every install, and about 80 ms per event while the config is broken. That inverts the finding it closes.

**Direction:**

1. Swap the two checks. Return False from `matched_plan_write_or_edit` first, and consult the gate only for an actual plan Write/Edit.
2. Replace the misnamed test with one that proves the order: monkeypatch `_load_config` to raise, and assert that `matches()` on a Bash payload and on a non-plan Write returns False without calling it.
3. Optional: memoise a failed load by the file's `(mtime_ns, size)` signature, so a broken config is re-parsed once per change rather than once per event.

## Minor

### RV7-m1 — the gate does not agree with what the daemon actually runs, and its docstring and test assert the opposite

**Where:**

- `plan_status_snapshot.py:134-171` (`_goal_injection_enabled`): an absent `goal_injection` block resolves to False, as "goal_injection's own opt-in default".
- `get_default_enabled()` is never consulted at registration. Its only callers are the config-optimisation checklist and the template drift guard. `register_all` treats an absent block as ENABLED (`handlers/registry.py:234-239`, `:538-548`) and applies tag filters that the gate ignores (`:557`).
- The gate also reads the file on disk at call time, while the registry is fixed at startup. The daemon has no config hot-reload.
- The docstring of `test_a_config_load_failure_resolves_like_an_absent_block` (`test_plan_status_snapshot.py:330-341`) states the opposite of real behaviour: "matching what the real registry would do … under which `goal_injection` is not registered".

**Reproduction** (`probe_gf7_registry.py` → `registry_out.txt`). It uses the daemon's real startup path: `Config.load`, then `cli._build_handler_config_mapping`, then `register_all`.

| Config text                                     | Daemon runs goal_injection | Snapshot gate | Result   |
| ----------------------------------------------- | -------------------------- | ------------- | -------- |
| no `goal_injection` block                       | True                       | False         | DISAGREE |
| `goal_injection: {enabled: true}`               | True                       | True          | agree    |
| `goal_injection: {enabled: false}`              | False                      | False         | agree    |
| `goal_injection: {priority: 30}`                | True                       | True          | agree    |
| bare `goal_injection:`                          | True                       | True          | agree    |
| `disable_tags` covering goal_injection          | False                      | True          | DISAGREE |

In the first row, goal_injection runs while its ground-truth sensor is switched off. Every write falls back to inference with nothing but an INFO log, which is exactly the state this branch exists to remove.

The same happens when the config is edited from enabled to disabled without a restart, or breaks after startup: goal_injection keeps running and the sensor goes dark. The reverse disagreements (tags, a config edited on without a restart) only waste the sensor's cost.

The first population is narrow, because the documented upgrade path writes the block explicitly. That is why this is Minor. But the code's stated contract is false.

**The "config load failure" test is theatre.** The fixture writes no config at all, so the load returns defaults for an ABSENT file. The `except` branch is never reached. A mutant that makes that branch raise survives: `test_plan_status_snapshot.py` and `test_goal_injection.py` give 141 passed (`mut2_out.txt`, copy in `probe_gf7/mut2/`).

**Direction:**

1. Decide the gate from the same predicate the daemon uses. Either:
   - build the post_tool_use mapping as `_build_handler_config_mapping` does and call `handlers.registry.handler_is_enabled(mapping, HandlerID.GOAL_INJECTION.config_key, <GoalInjectionHandler tags>)`; or
   - better, because it also covers "edited but not restarted": have `register_all` inject the set of registered handler ids onto handlers that declare an attribute for it (the same attribute-selected injection it already does for `_reference_repos`), and read that.
2. Fix the test at `:292` to expect the registry's answer for an absent block.
3. Add a table-driven test that asserts the gate equals `register_all`'s outcome for the six shapes above.
4. Make the load-failure test actually write invalid YAML.

### RV7-m2 — the FT4 chain test passes against the pre-fix ordering; the commit's "every finding has a RED-confirmed test" is false

**Where:** `tests/unit/handlers/post_tool_use/test_goal_injection.py:2912-2946`.

The test asserts only that a signal file exists. `tmp_path` is not a git repository, so when the snapshot goes STALE the Write fallback finds no HEAD and still reports a flip.

**Reproduction:**

- `git archive HEAD` into `probe_gf7/mut/`, then swap the constants back to `GOAL_INJECTION=31`, `MARKDOWN_TABLE_FORMATTER=26`.
- Run the class there (`mut_red.txt`): the guard test and FE fail as they should, but **FT4 passes**.
- With `--log-level=INFO` (`mut_ft4_log.txt`), the passing FT4 run logs `pre-write snapshot for tool_use_id='tu-ft4' is stale … falling back`. The test passes on the very fallback RV6-M1 is about.

FC3b, which review 6's Direction #2 named, has no chain test at all.

**Direction:**

1. In both chain tests, assert that the snapshot was consumed fresh. Either `caplog` has no "is stale" WARNING, or spy on `_snapshot_is_fresh` and require it to return True.
2. Give FT4 a git repo whose HEAD holds `**Status**: In Progress`. That is the real FT4 shape, where the fallback says "no flip", so the test fails when the snapshot is lost.
3. Add the FC3b chain test: a `replace_all` completion that changes column widths must retire the entry and write `+clear`.

### RV7-m3 — RV6-n3 is a real defect: a plan flipped through a symlinked folder is ledgered under the link's number and never retires

**Where:**

- `utils/plan_trigger.py:85-107`: the plan folder is the regex capture from the UNRESOLVED `file_path`.
- `is_inside_project` (`:61-82`) resolves the path, but only to check containment.
- `NIGGLES.md:1601` records this as "Confirmed harmless … no direction was given, so no code change made".

**Reproduction** (`probe_gf7_symlink.py`; branch output in `symlink_branch.txt`, main output in `symlink_main.txt`, main taken from `git archive main` at `8528b1ad`). The setup is `CLAUDE/Plan/00301-l -> 00300-c`.

| Step                                               | Branch                                | Main                                            |
| -------------------------------------------------- | ------------------------------------- | ----------------------------------------------- |
| S1 flips through the link                          | signal `names 00301`, ledger 00301 live | same                                          |
| S1 completes through the REAL path                 | **no clear; 00301 stays live forever** | same                                           |
| S1d: S3 ticks a box through the link while 00300 is live | no signal, ledger unchanged (correct) | spurious `names 00300,00301`, new 00301 entry |
| S2: whole `CLAUDE/Plan` symlinked outside the project | inert (no match, no snapshot)       | inert                                           |

In S1 the plan is Complete, yet the ledger keeps a live entry for a plan number that only exists as an alias. The supervisor's `/goal` is never retracted, and the Stop-hook side keeps treating it as owed work. This predates the branch (main does the same, and is worse in S1d), so it is not a regression. It is not "harmless", though, and it sits squarely in N3's scope: a plan's identity across its transitions.

S2 is the containment rule working as designed, so it is not a finding. It should be documented as "a plan directory symlinked outside the project is not tracked".

**Direction:** In `matched_plan_write_or_edit`, after `is_inside_project` passes, re-apply `plan_path_pattern` to `Path(file_path).resolve().relative_to(<resolved root>).as_posix()`, and return THAT capture as `folder`.

- If the resolved path no longer matches the pattern, return None and log it once.
- Both `goal_injection` and the sensor share this function, so one change fixes both.
- Add a test: flip through `00301-l`, complete through `00300-c`, and assert that a single 00300 entry is retired with `+clear` written.
- Replace the NIGGLES "harmless" text.

### RV7-m4 — release artefacts: the priority change has no config-changes entry, and two shipped texts still describe the pre-gate sensor

**Where:**

- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.67.0.yaml` gained no `changed` entries for the six priorities that moved:
  - `goal_injection` 31→30
  - `markdown_table_formatter` 26→31
  - `git_hooks_executable_fixer` 27→26
  - `background_process_tracker` 28→27
  - `command_hints` 29→28
  - `recovery_cron_advisor` 30→29

  The same file's own precedent (Ledger 00422 N1) documents shipped priority changes this way. Here the ordering is load-bearing.
- An operator who customised either of the two priorities keeps the old order through an upgrade, because the merger preserves customisations. That silently reintroduces RV6-M1, and nothing at runtime notices.
- `config-changes/v3.67.0.yaml:54` still says the sensor "Runs unconditionally on every matching write, whether or not goal_injection is enabled".
- `docs/guides/HANDLER_REFERENCE.md:2063` still says "Runs unconditionally on every matching write whenever enabled, whether or not `goal_injection` itself is enabled".
- Both are false since RV6-m1.

**Direction:**

1. Add `changed` entries for the six keys. On the two that matter, add a `migration_note`: "if you set your own priorities, keep goal_injection below markdown_table_formatter".
2. Optionally, add a startup `ConfigValidator` warning when both handlers are enabled and `goal_injection.priority >= markdown_table_formatter.priority`.
3. Rewrite the two "unconditionally" sentences to describe the gate, once RV7-M1 and RV7-m1 have settled its semantics.

## Nit

- **RV7-n1 — goal_injection's commented `options:` block now sits under `markdown_table_formatter`.** In this project's config (`.claude/hooks-daemon.yaml:744-757`), the formatter block was inserted between `goal_injection`'s `priority` line and its commented options (`mode`, `once_per_plan_per_session`, `lines: subagents-encouraged`). Uncommenting it now configures the wrong handler. The `.example` got the order right (`:462-476`). **Direction:** move the formatter block below the comment block, as the `.example` does.
- **RV7-n2 — release note ordinal and size.**
  - `13-goal-injection-no-longer-fires-on-any-edit-of-an-already-in-progress-plan.md` shares ordinal 13 with main's `13-acceptance-probe-fixtures-move-out-of-the-scratch-directory.md`. Main is now at 32.
  - It does match `^\d{2}-` and carries `**Plan**: 00466`, so the holding-area test passes.
  - The release-notes README's schema asks for "one to three sentences". This callout runs to roughly 1,300 words, and a reader of the release notes needs about three.
  - **Direction:** renumber to the next free ordinal at merge time (33 today). Cut the body to the operator-facing change: what stopped firing, that the snapshot sensor ships on, and what an operator who disabled it gets. Move the mechanism narrative to NIGGLES.
- **RV7-n3 — the "single authoritative list" of fallback triggers (`goal_injection.py:909-943`) omits a trigger:** the sensor not running at all, because `plan_status_snapshot` is disabled or its RV6-m1 gate reads goal_injection as off (RV7-m1's disagreeing rows). **Direction:** add it as its own bullet under "No snapshot recorded at all".

## Checks that passed

- **Ordering and collisions.** From the constants, this project's yaml, the `.example` (both handlers forced on) and `init_config.generate_full()` (both forced on), the chain runs lint_on_edit 25, git_hooks 26, background 27, command_hints 28, recovery_cron 29, goal_injection 30, formatter 31, budget 32, then model_downgrade 33. No duplicate priorities in the PostToolUse chain (`postorder_out.txt`). The four handlers that moved kept their relative order.
  - Of the handlers the formatter now runs after, only recovery_cron_advisor reads PLAN.md, and only its Status line, which mdformat does not change.
  - The PreToolUse `plan_status_snapshot` shares 30 with other PreToolUse handlers, but it was already there and it is observe-only.
- **Worktree daemon.**
  - The gate reads `ProjectContext.project_root()/.claude/hooks-daemon.yaml`.
  - The daemon loads `<project_path>/.claude/hooks-daemon.yaml` (`daemon/cli.py:544`), and `ProjectContext` is initialised from `<workspace_root>/.claude/hooks-daemon.yaml` (`daemon/controller.py:258`).
  - So a worktree daemon's gate reads that worktree's own config: the same FILE, though not the same STATE (RV7-m1).
- **goal_injection enabled, `plan_status_snapshot` disabled.** The sensor is not registered, so the gate is moot and goal_injection runs on inference, unchanged from before this commit.
- **Docs.**
  - The priorities in `HANDLER_REFERENCE.md` (the `command_hints` and `goal_injection` property tables and config examples, and the quick-reference table) and the regenerated `.claude/HOOKS-DAEMON.md` table match the new constants.
  - No live doc still states an old priority for the four handlers that moved; only historical CHANGELOG and RELEASES entries do, which is correct.
- **Targeted tests.**
  - Batch 1: `test_goal_injection`, both `test_plan_status_snapshot`, the four moved handlers, `test_markdown_table_formatter`, `test_template_priorities_match_the_constants`, `test_example_config`, `test_handler_reference_check` and `constants/test_config`. Result: 492 passed, 4 failed (RV7-B1).
  - Batch 2: `test_eviction_sites`, `test_registry`, `test_qa_package_dependency_direction`, `test_plan_trigger`, `test_goal_ledger` and `test_docs_generator`. Result: 231 passed (`pytest_targeted2.txt`).
  - No whole-suite run.

## Recommended order of work

1. RV7-B1: fix the four assertions.
2. RV7-M1: swap the gate and trigger order, and fix the misnamed test.
3. RV7-m1: make the gate agree with registration; write a real load-failure test.
4. RV7-m2: make the chain tests genuinely RED; add FC3b.
5. RV7-m3: resolve the plan folder before keying the ledger; add a test.
6. RV7-m4 and the nits.

**Verdict: NOT READY.**
