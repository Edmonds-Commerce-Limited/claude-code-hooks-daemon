# N449 (GitHub #101): merge_qa_report places a merge by the directory it runs in

Branch `worktree-issue-101-merge-dir`.

## Change

- `merge_directory(command, cwd)` moved from `daemon_sync_after_merge._merge_directory` into `utils/merge_scope.py`, behaviour unchanged. `_MERGE_SUBCOMMANDS` moved with it. No import cycle (`merge_scope` imports only utils).
- `daemon_sync_after_merge._is_foreign_repo` uses the shared function; its docstring no longer says "Mirrors ..." and points at `merge_directory`.
- `merge_qa_report._is_foreign_repo` resolves `GitRepo.resolve_for(merge_directory(get_bash_command(hook_input) or "", cwd_raw))`; docstring likewise.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/049-merge-qa-report-places-a-merge-by-where-it-runs.md` (Audience: client projects).

## Red first

- `test_merge_qa_report.py::TestForeignRepoByMergeDirectory`: 2 failed (the `cd <nested>` and `git -C <nested>` cases), 2 passed (plain merge, unplaceable `cd $DIR`, which already matched today's behaviour).
- `test_merge_scope.py::TestMergeDirectory` (6 tests): the whole file errored at collection (ImportError, `merge_directory` absent), so none could run.

## Tests

Added: `TestForeignRepoByMergeDirectory` (4, real `git init` repos, nested repo under the project) and `TestMergeDirectory` (6: plain, cd before, `git -C`, cd after the merge, computed cd target, no merge in the command). Changed: none; the `daemon_sync_after_merge` tests did not patch the old private name and are untouched.

## QA

- pytest on test_merge_scope, test_merge_qa_report, test_daemon_sync_after_merge, test_reserved_word_command_heads: 182 passed.
- `./scripts/qa/llm_qa.py changed`: the first run flagged 3 files for `format` (with a still-tree warning, because two runs overlapped); after `run_autofix.sh` the re-run exited 0 with no failing check. It printed "not recorded for this tree" only because the run preceded the commit.

## Deviations

None to the ruling. Two `llm_qa.py changed` runs overlapped once by mistake, which is what produced the stale-tree warning.
