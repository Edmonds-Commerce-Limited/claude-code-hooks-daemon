# Plan 00567 report (python-developer, sonnet)

The brief's approach was sound; implemented as specified. Release note numbered 003 (001 exists; 002 may arrive from another branch).

## Red phase (commit 18348ecf8)

Four new tests in tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py (TestLspCoverageFromPlugins):
2 failed, 2 passed (the mixed-list and nonexistent-target tests are guards that pass before and after).

- test_two_extensionless_files_are_advised_not_denied: `AssertionError: assert <Decision.DENY: 'deny'> == <Decision.ALLOW: 'allow'>`
- test_extensionless_files_get_the_same_verdict_by_directory: the by-directory ALLOW assertion passed; the parity
  assertion failed (files DENY vs directory ALLOW).

## Fix

lsp_enforcement.py: `_searched_directories` split into `_searched_targets` (resolved paths) and `_judged_targets`
(directories plus regular files, None if any target is missing or unreadable, or none is named). `_lsp_coverage` takes
the named files' suffixes (none means unserved) plus the directory survey; None keeps the old "any server covers"
fallback. get_claude_md wording left unchanged (still accurate).

## Verification

pytest on test_lsp_enforcement.py and test_lsp_enforcement_grep_file_path.py: 118 passed.
Targeted QA: see the final reply.
