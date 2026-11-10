# Plan 00591 fact-check (diff claims only)

REFUTED: none.

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Delivered from loaded handler classes outside the daemon package | VERIFIED | claude_md_injector.py (a9e0dacdb) l.455 `not path_is_relative_to(path, _DAEMON_PACKAGE_DIR)`, l.468 `inspect.getsourcefile(handler_class)` |
| 2 | One `git status --porcelain -- <paths>` | VERIFIED | l.509 `run_git(cwd, "status", "--porcelain", "--", *inside)` |
| 3 | Log line naming the file on hold | VERIFIED | l.~698-702 logger.info naming claude_md_path and held_by, then return |
| 4 | Test `test_untracked_handler_source_holds_the_commit` exists | VERIFIED | tests/unit/core/test_claude_md_injector.py:2078 |
| 5 | Release note 025-claude-md-auto-commit-waits-for-handler-sources.md exists | VERIFIED | present in CLAUDE/UPGRADES/UNRELEASED/release-notes/ |
| 6 | Commits ff62dc932, ddf285d42, 7e9a03f28, merge a9e0dacdb | VERIFIED | all `commit` objects; a9e0dacdb contained in origin/main |
| 7 | Main CI run 42732895459 green | VERIFIED | `gh run view`: "main QA" success, QA gate passed |
| 8 | GitHub #172 closed | VERIFIED | `gh issue view 172`: state CLOSED |
| 9 | Status Complete (2026-11-10) | VERIFIED | consistent with date and archival in Completed/ |
