# Plan 00572 completion fact-check

12 claims: 9 verified, 3 refuted, 0 unverifiable.

## REFUTED (most consequential first)

R1. "Phases 3 and 4 merged through PRs #179 to #187."
- Only #180 (3.1), #183 (3.2) and #187 (3.3) carried Phase 3 work. #179 is Release v3.73.0. #181, #182, #185 are Dependabot PRs (#181 closed, #182 and #185 open). #184 is Task 2.3 (Phase 2). #186 is Plan 00571 Phase 3. Tasks 4.1 and 4.2 reached main as direct commits (6e60e160f, 965951009 on the first-parent line of main), not through any PR.
- Correct wording: "Phase 3 merged through PRs #180 (3.1), #183 (3.2) and #187 (3.3). Phase 4 landed as direct commits to main (6e60e160f for 4.1, 965951009 for 4.2)."

R2. "Phases 1 and 2 merged to main at 4b1317734 through PR #178" (Delivery, not in diff but in the section checked).
- Task 2.3 (Phase 2, composite setup-env action) merged through PR #184 (merge 194601591, 2026-11-07T23:30Z), not #178 (merged 19:07Z).
- Correct wording: "Phases 1 and 2.1-2.2 merged through PR #178; Task 2.3 through PR #184."

R3. Criterion 1 "Code tier: PR #186" read as plan 00572 evidence.
- PR #186 is "Plan 00571 Phase 3: three branch pools", a different plan. Run 42427957281 (head 8f21c8409 = PR #186 head) is a valid code-tier measurement on the post-Phase-2 workflow, so the numbers hold, but the label misattributes the PR.
- Correct wording: "Code tier: QA run 42427957281 on PR #186 (an unrelated Plan 00571 PR, used as a real code-tier sample)".

## Verified

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Run 42427957281 took 27.8 min | VERIFIED | runwall.py: wall 27.8 min, event pull_request, success |
| 2 | Its slowest shard ended at 27.6 | VERIFIED | "tests py3.11 unit" ends 27.6 min (the "QA gate" job ends at 27.8) |
| 3 | Nightly 42442365191 took 28.5 min | VERIFIED | runwall.py: 28.5 min, event schedule, head 8dd877a6a, success |
| 4 | Its slowest shard ended at 27.9 | VERIFIED | "Full suite / tests py3.12 unit" ends 27.9 (coverage aggregate 28.4 and gate 28.5 follow the shards) |
| 5 | Previous nightly was 116 min | VERIFIED | gh run list: 42333472211 created 03:19:25Z, updated 05:15:25Z = 116 min |
| 6 | Task 3.3 merged at f2d532f89 (PR #187) | VERIFIED | git log: f2d532f89 is "Merge pull request #187"; gh pr list: #187 merged 2026-11-08T02:58:44Z |
| 7 | Nightly 42442365191 was green | VERIFIED | conclusion=success |
| 8 | Status: Complete consistent with ticks | VERIFIED | PLAN.md line 3 Complete; all tasks 1.1-4.2 and all four Success Criteria are [x]; no [ ] remain |
| 9 | Phase 1/2 merged at 4b1317734 via #178 CI | not re-checked beyond R2 (PR #178 merged 19:07Z, exists) | gh pr list |

Which PRs carried which task: 3.1 #180; 3.2 #183; 3.3 #187; 4.1 and 4.2 no PR (direct main commits). 2.3 was #184.
