# Signed branch-park end-to-end test

Test: tests/integration/test_branch_park_signed_commits_e2e.py (4 tests, real tmp repo,
bare tmp origin, throwaway ed25519 SSH signing key, allowed-signers file).

- Positive: gpgsign=true, park then unpark; both new commits beyond the original tip
  pass `git verify-commit` and show %G? = G; origin/work equals the unpark commit.
- Negative 1: gpgsign unset: park succeeds, pushed, commit shows %G? = N.
- Negative 2: gpgsign=true with a missing key: park raises BranchParkError carrying the
  commit.gpgsign hint; branch tip, origin/work and park record unchanged.
- Negative 3: same on unpark: tip and existing park record unchanged.
- Skip policy: skipped only when ssh-keygen/git ssh signing is unavailable and neither CI
  nor GITHUB_ACTIONS is set; in CI it calls pytest.fail.

Results: 4 passed. ruff, black --check, mypy clean on the file.

Mutation evidence: a pytest plugin (untracked/scratch, not committed) set
`branch_park._signing_requested = lambda repo: False`. Result: 3 failed, 1 passed.
Failed: test_every_park_and_unpark_commit_verifies (AssertionError at verify-commit),
test_broken_key_fails_with_hint_and_changes_nothing and
test_broken_key_on_unpark_keeps_tip_and_record (DID NOT RAISE). The unsigned test
passes, as it should. So the tests do depend on the -S flag.
