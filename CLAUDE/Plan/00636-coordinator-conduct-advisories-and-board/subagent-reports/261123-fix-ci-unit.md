# 261123 fix-ci-unit

Verdict: (a) a real failing test from this branch, not a hang or infra flake.

Run 45228570394 (QA, head 748a3199b). Unit durations of ~37-41 minutes are the normal full-suite time (55922 passed in ~2400s on py3.11/3.12); nothing hung.

Every unit job (py3.11, 3.12, 3.13 unit-tooling, arm64) has exactly one failure: `tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan::test_repo_is_clean_under_widened_scope` - `utils/stop_hook_helpers.py:267 [silent-continue]`. That is the `except json.JSONDecodeError: continue` added by d48de45f2 (Plan 00636 F3). Coverage-all-shards and QA gate failed as followers.

Fix: route the skip through `log_and_continue(..., level=DEBUG)` with a reason. Verified locally (PYTHONPATH to this worktree's src): 206 selected tests pass, including the self-scan.
