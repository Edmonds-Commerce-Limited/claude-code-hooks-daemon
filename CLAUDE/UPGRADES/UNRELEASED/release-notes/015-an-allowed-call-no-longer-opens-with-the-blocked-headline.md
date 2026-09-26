# Callout: an allowed call no longer opens with the BLOCKED headline

**Plan**: 00466
**Audience**: operators

`reference_repo_freshness`'s `block_once` repeat and `advise` mode both
returned `Decision.ALLOW` with a context built from the same verbose DENY
rendering used for a call that was actually stopped, so an allowed call's
context opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]` or
`BLOCKED [R-REFERENCE-REPO-STALE]`. `RuleFormatter` gained a fourth
rendering, `advisory()`, used on every ALLOW path instead — same rule ID and
teaching content, headed `ADVISORY` so it can never be mistaken for a call
that was actually blocked. A repository-wide sweep for the same defect shape
found no other handler affected.
