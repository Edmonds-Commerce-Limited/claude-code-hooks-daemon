# Plan 00595 Task 1 implementer report

Tasks 1.1-1.4 done. Fix commit b9a890c31 (pushed to origin/worktree-595-secret-guard-misreads).

- 1.1 `_ends_in_git_search_option` (separate form, in `_opens_files`), `_git_search_value_prefix_before` and `_is_git_search_word` (attached `-Sx`, `--grep=x`) in utils/secret_file_matching.py.
- 1.2 `_is_scoped_filter_value`: an attached `--include=`/`--exclude=`/`--exclude-dir=`/`--glob=`/`--iglob=` value is allowed only when the grep/rg segment names path operands and `index.find_under` finds no protected file under any of them. No path operand, a glob/variable operand, `-e`/`-f` patterns, or no index fall through to the old verdict.
- 1.3 `_colon_path_parts` drops a part that is only `*`/`?` characters.
- 1.4 release note CLAUDE/UPGRADES/UNRELEASED/release-notes/045-secret-guard-search-string-option-value-and-bold-colon.md.
- Tests: tests/unit/handlers/pre_tool_use/test_secret_file_guard_option_values.py (44 tests). RED before the fix: 19 failed / 23 passed.
- Secret guard suites (1982 tests) pass.

QA `changed`: 39/42 pass. Failures not caused by this change:

- pyright: tests/integration/test_branch_install_tracking_record.py:141 (file untouched here).
- changed_tests: 4739 passed, 0 failed, but src/.../secret_file_matching.py is "unmapped [too-broad]" in changed_tests_map.yaml, which fails the run.

## Review fixes

The grep/rg filter-value relaxation (`_searched_paths_hold_no_protected_file`) now allows only when every searched root, after `os.path.realpath`, lies inside the index's project root, and no link-following flag is present (grep `-R` or a cluster containing R, `--dereference-recursive`; rg `-L` or a cluster containing L, `--follow`). Otherwise the old deny stands. grep `-L` (files-without-match) is not treated as link-following.

Tests added (class `TestGrepFilterRelaxationNeedsRootsInsideProject`): `/etc`, `/root/.ssh`, an outside dir holding a protected file, the `outlnk` symlink root, `-R`, `--dereference-recursive`, `rg -L` and `rg --follow` all deny; clean in-project roots (relative and absolute) still allow. RED first (9 failures), now green; 1918 passed over test_secret_file_guard\*.py and tests/unit/utils/test_secret\_\*.py.

Probe harness: the four classes now deny.

Open follow-up (not fixed): `rg --follow x clean -g '*'` still ALLOWs. The separate-value quoted `'*'` after `-g` never reaches the filter-value judgement (already allowed on main), so the new flag check is not consulted. Fixing needs the separate-value filter spelling judged by the same function.

### Round 3 review fixes

1. Separate filter spelling (`--include *`, `-g *`, `--exclude-dir d*`, `-g [d]*`) now counts as a filter value only when the value word is quoted (`_follows_separate_filter_option` requires the opening quote); bash expands an unquoted glob into cwd file names. RED tests: all nine reviewed commands deny; quoted forms (`rg x sub -g '*'`) stay allowed. Attached forms (`--include=*`) unchanged: bash cannot expand them into a protected file name.
2. Cwd symlink resolving outside the project: relative roots are anchored at `realpath(cwd)`, and an attached wildcard filter (`--include=*`) with any effective cwd really outside the project is not judged clean (`_is_wildcard_filter_over_foreign_cwd`). RED test `test_cwd_symlink_resolving_outside_project_denied`. Plain `grep -r x .` from such a cwd (no filter) is still not judged: the index lists only the project, pre-existing design.

Results: option_values file 77 passed; test_secret_file_guard\*.py + tests/unit/utils/test_secret\_\*.py 1939 passed; probe harness: the nine deny, no regressions (remaining ALLOWs are the pre-existing out-of-scope ones).

### Round 4 review fixes

Review: `task-1-review-round4-code-reviewer.md`.

1. (Critical) A separate filter value is decided from the WHOLE shell word, not the character before it. `_quoted_separate_filter_values` walks `shell_word_spans` and keeps a value only when the word after a `_FILTER_SEPARATE_OPTIONS` word is exactly one quoted literal (`_is_one_quoted_literal`: matching opening and closing quote, nothing outside; a double-quoted body holds no `$`, backtick, backslash or `"`). Both `_is_separate_filter_value` and `_is_scoped_filter_value` use it, and `_follows_separate_filter_option` is gone. `''*`, `""*`, `''*.secret`, `''[d]*`, `'*'*`, `*'*'` and `"$X"*` now deny.
2. (Suggestion) `_is_wildcard_filter_over_foreign_cwd` now also covers the quoted separate spelling (`-g '*'`, `--include '*'`, `--glob "*"`). With a cwd that is a link leading out of the project, `rg x -g '*' .`, `rg x -g '*'` and `grep -r x --include '*' .` deny.

RED first: 10 failed. Now green: option_values file 107 passed; test_secret_file_guard\*.py + tests/unit/utils/test_secret\_\*.py 1954 passed. Probe harness over cmdsV, cmdsV2, cmdsR, cmdsR2 and cmdsR9: compared with the reviewer's HEAD results, the only changes are the nine reviewed commands going ALLOW -> DENY. Every remaining ALLOW also allowed in the reviewer's run.
