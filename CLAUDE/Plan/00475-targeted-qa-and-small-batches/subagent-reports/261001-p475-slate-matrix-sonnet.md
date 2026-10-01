# Plan 00475 Task 3b.2: slate gate full-matrix requirement

**Gate now requires**: a completed, successful `qa.yml` run on HEAD's exact sha whose `QA (Python...)` matrix jobs all concluded success (at least one such job; a skipped or absent matrix does not count). Any run of the sha may supply it, so a newer tier run does not hide an older full run.

**Mechanism**: `_gh_ci_lookup` in `src/claude_code_hooks_daemon/daemon/cli.py` lists runs with `--workflow qa.yml` plus `databaseId`, then calls `gh run view <id> --json jobs` for a successful run. `full_matrix_green` and `CiRunState.full_matrix` live in `core/release_slate.py`. A tier-only green renders a message naming `gh workflow run qa.yml --ref main`.

**Fail closed**: `gh` failure or timeout (SubprocessError), or unparseable list or jobs output (ValueError, OSError), is caught by `_head_ci` and becomes a `problem`, which is never green.

**Dispatch**: `emit_tier.bash` gives workflow_dispatch an empty base, and `classify_range` returns full for an empty base (already tested by `test_missing_or_zero_base_is_full` and `test_range_without_base_prints_full`). No classifier change was needed.

**Callers**: `_gh_ci_lookup` is used only by `release-slate-check`, so no everyday-status caller exists to preserve.

**Not verified**: no live `gh` call was made (the fake covers argv shape and JSON only). TDD red phase was written as tests-first in the file but the failing run was not captured separately.
