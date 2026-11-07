# Plan 00573 sub-agent report: admin seat issue assignment override

Agent: python-developer, model sonnet. Branch worktree-plan-00573-admin-override.

## What changed

- `utils/github_issue_validity.py`: new `CheckStatus.ADVISORY` (does not affect the verdict), `TAKEOVER_FIX_NAME`, `FixAction.previous`, `AccessInfo` / `AccessAwareCheck` protocols. `AssigneeCheck.evaluate` takes an optional access object. The service adds cached `is_viewer_admin` (`gh api repos/{owner}/{repo} --jq .permissions.admin`) and `is_protected_assignee` (`collaborators/{login}/permission`), one call each while cached; lookups happen only when someone other than the seat is assigned. `claim()` posts one comment naming the previous assignees after a verified sole-assignee takeover; the back-off is unchanged.
- `daemon/issue_validity_cli.py`: `--claim` also acts on an admin's advisory; the plain check prints a "to take it over" line; a takeover that fails or loses a race never exits 0 (exit 1 lost race, exit 2 gh error).
- Guard: allows with an advisory naming the assignee and the takeover command; never takes over itself (auto_claim included). Resident guidance updated.
- Docs: `CLAUDE/development/IssueSdlc.md` (exit table and takeover section), release note 004, truth-change `v3.73.0.yaml`, PLAN.md ticked.

## RED output (quoted)

```
TypeError: AssigneeCheck.evaluate() takes 3 positional arguments but 4 were given
tests/unit/utils/test_github_issue_validity.py:527
1 failed, 50 passed   (first failure, run with -x)
```

Guard and CLI RED: 6 failed, 99 passed (for example `assert 'alice' in ''` and `assert '--claim' in 'issue #5: valid ...'`).

## Disagreement with the spec (evidence)

"Unknown permission counts as non-admin" is applied to the SEAT only. For the ASSIGNEE it is the unsafe direction: a rate limit or a 404 would then authorise a takeover of a possibly-admin claim. So an assignee whose permission cannot be read counts as protected (blocking). Cost: an assignee removed from the repo (404) still needs a human. Test: `test_a_failed_assignee_lookup_never_grants_an_override`. Easy to flip in `is_protected_assignee` if the owner prefers the literal ruling.

## Results

Targeted pytest on the three touched test files plus the release-note holding-area test: 184 passed. ruff clean. mypy clean on touched src; the test files have one pre-existing indexing error at test_issue_validity_cli.py line 161 (not from this change).

One `llm_qa.py changed` run finished before the coordinator's pause note. Everything was green except: format (fixed by run_autofix), pyright and mypy test indexing (fixed), error_hiding log-and-continue (now `log_and_continue` with a reason), release note Audience line (fixed), and three unmapped files for changed_tests (needs `--allow-unmapped`). No re-run was done, per the coordinator's instruction not to start another run. The dogfood success criterion needs the live admin seat after merge.
