# Finding I3 fix — vendor-exception wildcard un-pruning `_OWN_EXCLUDED_DIR_NAMES`

## Root cause

`_walk_into` in both `source_tree_markdown.py` and `module_doc_budget.py` computed
a single `excluded` flag covering BOTH the daemon's own always-prune set
(`.git`, `untracked`, `worktrees`) and genuinely vendored directories, then
asked `may_contain_vendor_exception_in_scopes` whether to override it. That
function is deliberately conservative: a pattern with no literal prefix
(`**/ours/**`) returns `True` unconditionally, since a `vendor_exceptions`
entry is a vendored-tree carve-out and can legitimately live anywhere under a
vendored root. But the override applied to the own-excluded set too, even
though a repo-relative exception path can never resolve inside `.git` or
`untracked` — so one wildcard exception un-pruned the whole always-excluded set.

## Fix

In both files, `_walk_into` now checks `_OWN_EXCLUDED_DIR_NAMES` first and
returns `False` immediately — before the vendored check or the conservative
exception fallback ever runs. The fallback still applies, but only to the
vendored-directory branch, which is where an exception can legitimately live.
Small, isolated diff; no behavioural change to the vendored-directory case.

## Before/after (probe script)

```
no exceptions                       leading-wildcard exception (**/ours/**)
  .git:           False               .git:           False (was True)
  untracked:      False               untracked:      False (was True)
  node_modules:   False               node_modules:   True  (unchanged)
  src:            True                src:            True  (unchanged)
```

## Duplication note

`_walk_into` is near-identical between the two files (module_doc_budget's
version has an extra `scope_exclude_globs` parameter/check). Both already
carried a comment explaining why the vendored-set union isn't shared (the
configurable half must stay a parameter). A shared helper is plausible but
was not done here — out of scope for a small, reviewable fix; flagging for a
future pass if the two drift again.

## Tests added

New class `TestVendorExceptionWildcardNeverUnprunesOwnExcludedDirs` in both
`tests/unit/docs_qa/checks/test_source_tree_markdown.py` and
`test_module_doc_budget.py`, each with two tests against `_walk_into`
directly:

1. `test_own_excluded_dirs_stay_pruned_despite_the_wildcard` — `.git`,
   `untracked`, `worktrees` all stay pruned under a leading-wildcard
   exception. Confirmed RED before the fix (asserted `False`, got `True`).
2. `test_a_genuinely_vendored_dir_is_still_descended_for_the_wildcard` —
   `node_modules` (declared vendored) is still descended under the same
   wildcard exception, preserving the Plan 00331 Phase 3 behaviour. This one
   already passed pre-fix; kept as a regression lock.

## Test results

- Targeted new tests: RED confirmed pre-fix (2 failed as expected, 2 passed),
  GREEN post-fix (4 passed).
- `tests/unit/docs_qa/checks/test_source_tree_markdown.py` +
  `test_module_doc_budget.py` + `tests/integration/test_source_tree_markdown_no_double_report.py`:
  65 passed.
- `tests/unit/docs_qa/`: 409 passed.
- `tests/unit/docs_qa/` + `tests/integration/`: 2434 passed, 2 skipped
  (unrelated: no config-changes manifest staged; fingerprint-parity
  interpreter-pair test has no unrelated pair available here).

No files outside `src/claude_code_hooks_daemon/docs_qa/checks/` and its two
test files were touched.
