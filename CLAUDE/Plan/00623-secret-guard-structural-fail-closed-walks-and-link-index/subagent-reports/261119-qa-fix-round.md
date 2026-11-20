# Plan 00623 QA fix round (full gate 40/46 on e80cb685e)

Branch `agent-a13d7c8504105d4c9-aeae03b4`. `main` merged as `1598da6b8`. Commits `178cab629`, `6c16ce510` and `981801172` are pushed.

## Fixed

1. **format**: the 4 harness scripts under `subagent-reports/review2-tools/` are black-formatted (the gate's autofix had left them uncommitted). Committed in `178cab629`.
2. **lint E741**: the variable `l` in `cmp.py` and its single-letter siblings are renamed to `cap`/`lifted`/`cold`/`main` (`178cab629`). `llm_qa.py format lint` passes.
3. **test_branch_pressure `test_over_cap_with_nothing_touched_by_this_session_allows`**: this is NOT a branch regression. It fails identically in isolation on the `/workspace` main checkout (7a24f0cf7). Plan 00619 added a pool-wide warning ladder at stop (`branch_stop_gate.py:292`, context only), so `context == ()` is stale. The test now asserts its intent: no deny, and no left-behind or over-cap line. 19/19 pass (`981801172`).
4. **ordinary-command gate `a9-grep-proc-self-status`**: this is a real over-deny from N668. `refuse_process_view` refused every path through `/proc/self`. The fix places one allowlisted plain file directly under `/proc/self` or `/proc/thread-self` (`status`, `cgroup`, `mountinfo`, ...; `environ` is deliberately excluded). Everything else is still refused: `cwd`, `root`, `fd`, `exe`, `task`, `map_files`, any glob (`/proc/self/*`, `c?d`), any deeper path (`status/../cwd/x`, `status/x`), the bare view, and all of `/dev/fd`. Done test-first: RED was `test_other_paths_are_placed[/proc/self/status]`. GREEN: `test_resolution_failure.py`, `test_secret_file_guard_bounded_walks.py` (the N668 deny cases plus new deny cases, and the pinned "ordinary read denied too" test flipped to allow) and `test_ordinary_command_regression_gate.py` give 614 passed. ruff, black and pyright are clean (`6c16ce510`).

## Diagnosed, not changed

6. **hostile-input perf `test_bash_command[letter_sequences]`** (root-recursion-guard 29x for 8x): this is a load flake. Run alone, it passed 2/2 on the branch and 2/2 on main (about 1.4 s each). The branch does not touch `root_recursion_guard.py`.
7. **playbook probes**: the test needs a fresh worktree daemon. It was stale after the source edit and was restarted with `cli --project-root <wt> restart`. After that the probes still fail on the branch and pass on main.
   - **#350, #351** (`git commit --dry-run && cd - && git commit --dry-run`, `cd - && git commit -m ... -- path`): the secret guard denies with "moves into more than 16 existing directories". The worktree's link index finishes (73k dirs, 0.4 s verify) but holds **152 directory links**, and 148 of them are review fixtures under `untracked/scratch/` (for example `614-r6/fx/proj/*`). Each one is a real base for a computed move, so every `cd -`/`cd ~`/`cd "$X"` followed by any relative word (even the command name `git`) is denied. Outside scratch there are only 4 directory links (venv `lib64`, `lsp-venv`), which is below 16. The failure therefore depends on the worktree's scratch contents, but it is the same over-deny class as ledger N670. This needs an owner or coordinator decision: either remove or move the scratch fixtures out of the worktree before the gate, or exclude `untracked/scratch` and other checkouts from the index, which needs its own fail-closed argument. Not changed.
   - **#125** (WorktreeFileCopy probe, denied by R-WRITE-OUTSIDE-PROJECT-ROOT): not reproduced by `probe --only project_containment` (allow) from the worktree root. It is probably the harness's dispatch cwd or the probe's `untracked/worktrees/` path relative to a worktree checkout. The branch does not touch project_containment. Not yet diagnosed.

## Not done

- 7. Timeouts (`tests/unit/qa/test_run_test_matrix.py` plugin tests, `tests/integration/test_client_owned_asset_lint.py` shellcheck) were not re-run. Another worktree's full run held the host-wide QA lock throughout, and my targeted `llm_qa.py` wait timed out at 600 s.
- 8. dependencies: not re-run, for the same lock reason. `smoke_test.json` (3/3) and `project_handlers.json` (301/301) in `untracked/qa/` both report passed, so "not meaningful" is the full-run annotation, not a failure.
- Scratch probe tools: `untracked/scratch/probe_many.py` (secret guard via the worktree daemon), `index_status.py` (link index verify), `cmds1.txt`.
