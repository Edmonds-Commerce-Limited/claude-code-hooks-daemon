# Fact check, Plan 00584 diff (Task 1.2)

No REFUTED claims.

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `utils/github_issue_validity.py` exists | VERIFIED | src/claude_code_hooks_daemon/utils/github_issue_validity.py (git ls-files) |
| 2 | It looks up repository permissions lazily | VERIFIED | `_cached_admin` (line 535) calls gh api on demand; class docstring line 266 "looked up lazily and cached" |
| 3 | ...with TTL caches | VERIFIED | FACTS_TTL_SECONDS 300 (line 69), FAILURE_TTL_SECONDS 60 (line 72), `_cached_admin` expiry logic lines 542-554 |
| 4 | Config in tracked files would drift if a repo goes public / plan changes | UNVERIFIABLE-HERE | Rationale/opinion about GitHub behaviour, not a repo state claim |
| 5 | Which probe is readable by non-admin token | Intent (verify later), not a claim | n/a |
