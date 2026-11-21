# Task 4.9 report: park commits are signed when the repository requires it

Branch: `plan-00594-task-4-9-signed-park` (ledger N611).

## Change

- `src/claude_code_hooks_daemon/core/branch_park.py`: `_write_park_commit` now asks `git config --type=bool --get commit.gpgsign`. When true it runs `commit-tree ... -S` (so `user.signingkey`, `gpg.format` and `gpg.program` apply). When unset or false the command is unchanged.
- A failed signing raises `BranchParkError` carrying git's stderr plus a hint (check `user.signingkey`, `gpg.format`, `gpg.program`, or unset `commit.gpgsign`). It happens before `update-ref`, so the branch, its park record and the remote are untouched, and no unsigned commit is written.
- `commit-tree` use: a grep of `src/claude_code_hooks_daemon` found one call site, `_write_park_commit`. The local park, the `--clear` path and the remote-only park all go through it, so all three are covered. The other hit (`utils/shell_segmentation.py`) is a command-name list, not a writer.
- Constants: `_GPGSIGN_KEY`, `_SIGN_FLAG`, `_SIGNING_HINT`. Release note `048-branch-park-commit-is-signed-when-signing-is-required.md`.

## TDD

Tests are in `tests/unit/core/test_branch_park_signing.py` (real temp repos, a fake `gpg.program` script that records its arguments and emits `SIG_CREATED`, or exits 1). They were written first. I ran them before the implementation and saw 6 fail: signed park, signed clear, signed remote-only park, and the three failure cases (DID NOT RAISE). The 2 unsigned-path tests passed as expected. After the change all 8 pass, as do the existing park tests (37 in the three park files).

## Verification

- Neighbouring suites: tests/unit/core 4223 passed; session_start 988 passed; post_tool_use 962 passed; tests/unit/scripts 614 passed; the three integration files 419 passed.
- tests/unit/daemon: 2 failed, the known `test_paths_diagnose_venv_start.py` artefacts.
- tests/unit/handlers/pre_tool_use: 1 failed, the known `TestProjectRootDoublePatchDoesNotLeakAcrossFiles`.
- `run_autofix.sh` clean; `llm_qa.py format lint type_check error_hiding magic_values semgrep plan_qa docs_qa` reported 8/8 PASSED.
- PLAN.md checkbox not touched.
