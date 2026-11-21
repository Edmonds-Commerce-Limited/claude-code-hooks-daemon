## 14:50 · action · — — Review fix 3: unresolved review attempts

Review fix (3), F-BYPS F2: a review that ends with no verdict is now an unresolved attempt on the same work.

- It is derived: a dispatch with no verdict of its own, unioned by nonce with the new `failures/<nonce>.json` records. The recorder writes one on a damaged transcript, a reply mismatch or an unparseable reply.
- Each attempt adds one reviewer, and two (`MAX_UNRESOLVED_REVIEWS`) close the route until a human decides. This follows the handoff, not the dispatch's "3 attempts".
- `same_work` is the one relation for the keep history and the attempts.
- `issue_requests` and `approve_removal` both recompute the count, so an older no-value verdict cannot meet the raised count.
- Fail closed: a misnamed or damaged dispatch or failure record raises, and so does one with no request.
- In-flight reviews block approval by design.

Tests come first in `test_branch_reject_unresolved.py`. 672 pass across the branch_reject, branch_safety and branch_sweep tests. Report: `subagent-reports/261120-review-fix3-done.md`.
