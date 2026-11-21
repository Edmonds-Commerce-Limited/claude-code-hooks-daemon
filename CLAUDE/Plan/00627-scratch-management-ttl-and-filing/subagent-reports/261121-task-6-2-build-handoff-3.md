# Task 6.2 build: handoff 3

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Build order: `261121-task-6-2-build-handoff-2.md` (steps 1-5 are this builder's; Unit 3 and the documents belong to another builder). Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch `agent-acff915e4bf3b86e6-0a26f829`, head `42f1bdad2` (pushed). Tests: `untracked/py/bin/python -m pytest -q -p no:cacheprovider <files>`.

## Done (steps 1-2)

- `65e1e9b14`, `42f1bdad2`: `core/worktree_scratch_evacuation.py` plus `tests/unit/core/test_worktree_scratch_evacuation.py` (25 tests, green). The name `evacuation.py` was already taken by Plan 00558.
  - `evacuation_gate(report, *, ttl_hours, max_inodes, max_depth) -> EvacuationGate(blockers, consent, entries, not_due, by_verdict)`.
  - It blocks on: an incomplete report; a session directory (`SESSION_BLOCKER` names the human's step, deduped when the directory is both a row and a sub-report); any row that is not "due and ACTIONABLE" or "not due with `ttl_hold` in ACTIONABLE"; an incomplete walk; a name on disk that no row lists (`NOT_LISTED`: a skipped name, a leftover `.sweeping-*`, `.scratch-keep`); no or unreadable birth stamp; a foreign inode; an unwalkable entry; a root that cannot be opened or listed; and a not-due row that the consent did not bind.
  - `consent` is `consent_to(report, Pressure(idle_hours=0, ttl_hours=ttl))`, and is None whenever anything blocks. The key is `str(Path(report.root) / name)`, so `ApplySettings.root` must be `Path(sweep_root.path)`, the same path the classification used.
- `e0cc1fc49`: `ApplySettings.expire: bool = True`. `apply_sweep` skips `_expire` when it is False. Tested: `test_a_run_with_expiry_off_expires_nothing`.

## Not done: steps 3-5

Put the runner in a NEW module, e.g. `daemon/worktree_evacuate.py`, with its test file written first (TDD gate). `cli.py` is 15,346 lines and is listed by `check_module_length.py`. Import `_ScratchSources` lazily inside functions to avoid an import cycle. Keep the change to `cmd_worktree_reap` small (a call at the blockers check, ~line 11122).

3. **`confirm_evacuate_interactively(relative_worktree, gate, *, stdin, stdout, prompt_stream) -> bool`.** Copy the rules of `confirm_apply_interactively` (`cli.py` 7089): both streams must be TTYs, and the phrase is exactly `evacuate <worktree path relative to main>`. The prompt states the worktree, `gate.entries`, `gate.not_due` and `gate.by_verdict`, that the archives go to the main store with their restore commands, and that the worktree is then removed. Reuse the `_Stream` test helper from `tests/unit/daemon/test_cli_scratch_apply.py:259`. Assert that no argparse key contains `confirm` or `yes`.
4. **Wiring.**
   - **Background records.** Add `extra_background: tuple[Path, ...] = ()` and a `background()` method to `_ScratchSources` that merges `read_background_records` over `(background_file, *extra_background)`. Concatenate the commands. If either file has an error, the merged reading carries an error. Use it in `classify` (line ~7190) and in the `live_in` closure of `_scratch_apply` (~7319).
   - **Do NOT call `_scratch_apply`.** It runs `apply_sessions`, expiry and the cap notice. Extract its `live_in`/`references_of` facts building into a shared helper, or rebuild it in the new module.
   - **Sources.** `_ScratchSources(repo=wt, store_checkout=repo_root, extra_background=(main's file,), config=main's Config, budget_seconds/max_inodes = the scratch-sweep parser defaults, seams...)`. Classify with `resolve_sweep_root(wt/untracked/scratch, project_root=wt, ...)`.
   - **Order.** Preconditions, `find_gnu_tar`, gate, then the question. If the gate blocks, print `KEEP <name>: ...` and do not ask. If there is no TTY or the phrase is wrong, KEEP and name `hooks-daemon worktree-reap --reap --only <name>`. Only then open `ArchiveStore.open(main/untracked/scratch-archive)` under `store.lock()` and run `apply_sweep` once with `expire=False`, `empty_session_hours=None`, `pressure=gate.consent`, `original_prefix="untracked/scratch"` and `checkout=str(wt)`.
   - **Re-judge.** Every outcome must be `archived`; otherwise KEEP and print `hooks-daemon scratch-sweep restore <id>` for each archive made. Then run `worktree_blockers` again; only `()` reaches `reap_worktree`.
   - **Dry run (no `--reap`).** It prints the gate's verdict and what would be packed, and never asks and never opens the store.
   - **Refusal paths.** No refusal path may open the store, because opening creates it. Assert in tests that the store directory is absent.
   - **New seams on `cmd_worktree_reap`.** `confirm_evacuate`, a scratch `wall_clock` and `process_cwds` for the scratch side. The process map must be NON-empty: `entry_in_use` treats an empty map as live.
5. **Tests on a real repository.** Use the Unit 1 fixture in `tests/unit/daemon/test_cli_worktree_reap_ignored_content.py`.
   - **Minimum set first:** the happy path, including a NOT-DUE entry (the only proof that the consent keys match), with each archive restored byte for byte from main after the reap; no TTY (store absent, worktree kept, command named); session children (no question, zero archives, KEEP, by-hand step named); a dry run that changes no inode.
   - **Then the rest:** wrong phrase and end of input; both background files blocking; a replaced not-due inode; an entry created after the question (clock between `min_age_minutes` and the TTL); `after_step` failures converging; retention; the `"*"`/link/locked/prunable/linked-run refusals; store busy; no tar; the housekeeping step; and the main archive not expired.
   - **Regressions.** Rerun `tests/unit/daemon/test_cli_worktree_reap*.py`. Unit 1's KEEP text for a scratch-only worktree will change if the evacuation offer prints a different line. Include the deletion-surface inventory test.

## Note for the record

An entry created after the question that is already past its TTL is due, and the run packs it without asking. That matches `--apply` for due entries, so it is not a blocker. Name it in DESIGN.md section 13.

## Checks run

- `tests/unit/core/test_worktree_scratch_evacuation.py`: 25 passed. `tests/unit/core/test_scratch_archive_apply.py`: 83 passed.
- black, ruff and pyright are clean on the touched files. `audit_error_hiding.py` and semgrep (`QA_SEMGREP_TARGETS=<module>`) are clean on the new module.
