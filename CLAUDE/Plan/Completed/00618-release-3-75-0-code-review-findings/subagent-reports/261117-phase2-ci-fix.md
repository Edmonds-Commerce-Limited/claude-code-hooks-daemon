# Phase 2 CI fix (CI run 43995304132)

Branch `agent-a4c70e8f0e0ea55fb-91a87d12`, base tip 9610a7f84.

## Failures and root causes

1. `tests/unit/utils/test_scan_scope.py::TestWalkFiles::test_a_root_that_is_itself_a_checkout_is_still_walked`

   - Root cause: a real behaviour regression from this branch's N-20 change, visible only on newer git.
     `_git_ignored` treats exit 128 as "no repository" only when stderr says `not a git repository`.
     Git 2.47 (local) reports a `.git` file whose `gitdir:` names nothing that way; git 2.56 (CI) says
     `fatal: gitfile does not point to a valid repository`, so the walk raised `WalkError`.
   - Fix (test first): new `TestGitFatalExit::test_a_git_file_naming_no_repository_means_no_ignore_rules`
     (red, then green); `_NOT_A_REPOSITORY_MESSAGES` recognises both messages.
   - Loosening: none. Main treated every exit 128 as "no ignore rules"; the branch still fails every
     other fatal error, and this case walks the same files main walked.

2. `tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan::test_repo_is_clean_under_widened_scope`

   - Root cause: six findings, all in code this branch added. Fixed in the code, with no exclusions added:
     - `branch_park._record_from_fields`: validates parked-at with a regex, so there is no try/return None.
     - `branch_park.park_branch`: `_restore_tip` returns the error and the caller does `raise ... from exc`.
     - `venv_lock._latest_result_path`: the stat race uses a narrow `suppress(FileNotFoundError)`
       (the module is stdlib-only, so it cannot use `log_and_continue`).
     - `long_running_command_guard._policy` and `version_check._cache_ttl_seconds`: the deliberate
       fallbacks go through the sanctioned `log_and_continue` with a reason. version_check now logs a
       bad TTL where before it did nothing.

3. `tests/unit/qa/test_check_generated_doc_drift.py::test_real_repository_handler_doc_is_fresh`

   - Root cause: this branch changed `branch_creation_guard`'s description and did not regenerate
     `.claude/HOOKS-DAEMON.md`. The file was regenerated with the generator
     (`python -m claude_code_hooks_daemon.daemon.cli generate-docs`, run from this checkout's src). The
     regenerated file went into the merge commit.

## Follow-up after the merge

- The parked-at regex is bounded to 18 ASCII digits. `int()` refuses a string longer than 4300 digits,
  and that failure would otherwise escape the batched reader. New test:
  `test_a_parked_at_too_long_for_int_is_no_record` (red, then green).
- The scan_scope fix was verified with a mocked test that uses the verbatim CI message. Local git 2.47
  cannot reproduce the failure, so the next CI run is the real confirmation.
- Verification: the 32 touched test files passed (986 passed), and so did ruff, black (py311) and mypy on
  the touched sources.

## Merge of origin/main

Conflicts were only in imports, in `core/branch_creation.py` and `core/branch_inventory.py`. Main added
`is_park_residue`/`park_marked_refs`/`walk_park_range`, and this branch moved to batched
`read_park_records`. The union of the names each file uses was kept, and the unused single-record import
was dropped. Release notes: main ends at 091 and this branch's note is 092, so there was no clash.
