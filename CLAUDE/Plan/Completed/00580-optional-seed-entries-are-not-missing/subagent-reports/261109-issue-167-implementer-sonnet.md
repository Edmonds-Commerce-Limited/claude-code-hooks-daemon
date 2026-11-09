# Issue 167 implementer report

Brief was correct; implemented as written.

## RED (before the fix)

Tests added in tests/unit/utils/test_worktree_seed_suggestions.py (class TestDiffSeedConfig): absent optional not
missing, absent required still missing beside an optional one, present optional not missing. Two failed, one passed:

```
E  AssertionError: assert (SeedEntry(pa...tional=True),) == ()
E  Left contains one more item: SeedEntry(path='.env.gone', mode='symlink', optional=True)
```

## GREEN

`diff_seed_config` (src/claude_code_hooks_daemon/utils/worktree_seed_suggestions.py) now excludes absent optional
entries from `missing`. The CLI rendering in src/claude_code_hooks_daemon/install/worktree_seed_report.py says MISSING
entries abort the next worktree creation and to remove or restore them. That is now true for everything left in
`missing` (required entries only), so the wording is unchanged; only the two `missing` docstrings were made precise. No new
report section. Creation-time seeding, the removal guard and `unconfigured` are untouched.

Release note: CLAUDE/UPGRADES/UNRELEASED/release-notes/016-optional-seed-entries-are-not-missing.md.

## QA

`./scripts/qa/llm_qa.py changed`: QA: 42/42 PASSED.
