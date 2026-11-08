# Fact check: Plan 00572 Task 4.2 diff

Diff: untracked/plan-fact-check/00572-ci-wall-clock-sharding-arm-and-hygiene.diff

| #   | Claim                                                                                           | Verdict           | Evidence                                                                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Task 4.2: every external `uses:` pinned to a full commit SHA with the tag in a trailing comment | VERIFIED          | `grep -rn "uses:" .github` excluding `./` refs and excluding `@<40-hex> # v` lines returns nothing. 28 external uses across qa.yml, test-shards.yml, release-gate.yml, release-assets.yml and .github/actions/setup-env/action.yml, all pinned.                           |
| 2   | "Pinned at the release each floating tag pointed to"                                            | VERIFIED          | `git ls-remote --tags` shows each pinned SHA is the commit of both the floating major tag and the named release tag (table below).                                                                                                                                        |
| 3   | `tests/integration/test_ci_actions_pinned.py` fails on any unpinned external action             | VERIFIED          | File exists and is tracked. It scans every .yml/.yaml under .github, parametrises over each external `uses:`, and asserts `^[\w.-]+/[\w./-]+@[0-9a-f]{40}$` plus a `# vX.Y.Z` comment. It has a self-check that a tag is rejected. Not executed (no test runs per brief). |
| 4   | Task 2.3 done: composite `setup-env` action with uv cache keyed on `uv.lock`                    | VERIFIED          | .github/actions/setup-env/action.yml:49 `key: uv-...-${{ hashFiles('uv.lock') }}`; used by qa.yml, test-shards.yml and release-gate.yml. The "8+ copies replaced" count was not audited.                                                                                  |
| 5   | Task 3.1 done: `native-builds` matrix, x86_64 on ubuntu-latest, aarch64 on ubuntu-24.04-arm     | VERIFIED          | qa.yml:524 `native-builds:`, qa.yml:537 `runner: ubuntu-24.04-arm`. The smoke-run of relay and hooks-screen was not inspected.                                                                                                                                            |
| 6   | Task 3.2 done: tag release assets for both triples, merged SHA256SUMS, attest-build-provenance  | VERIFIED (partly) | release-assets.yml:52 arm runner, :122-128 merged SHA256SUMS (4 lines), :111 `attestations: write`, attest-build-provenance@e8998f9 # v2.4.0. "Relay's download path selects asset by architecture" not checked.                                                          |

## SHA to release tag (git ls-remote --tags)

| Action                          | Pinned SHA                               | Comment | Remote tag at SHA   | Result |
| ------------------------------- | ---------------------------------------- | ------- | ------------------- | ------ |
| actions/checkout                | 11d5960a326750d5838078e36cf38b85af677262 | v4.4.0  | v4, v4.4.0          | match  |
| actions/download-artifact       | d3f86a106a0bac45b974a628896c90dbdf5c8093 | v4.3.0  | v4, v4.3.0          | match  |
| actions/upload-artifact         | ea165f8d65b6e75b540449e92b4886f43607fa02 | v4.6.2  | v4, v4.6.2          | match  |
| actions/setup-python            | a26af69be951a213d495a4c3e4e4022e16d87065 | v5.6.0  | v5, v5.6.0          | match  |
| actions/cache                   | 0057852bfaa89a56745cba8c7296529d2fc39830 | v4.3.0  | v4, v4.3.0          | match  |
| actions/attest-build-provenance | e8998f949152b193b063cb0ec769d69d929409be | v2.4.0  | v2 (peeled), v2.4.0 | match  |

## REFUTED

None.

## Notes

- The diff also flips Tasks 2.3, 3.1 and 3.2 to done, beyond Task 4.2; those were checked as rows 4-6.
- Not verified: that these are the latest releases (the plan claims only the release each floating tag pointed to, which holds).
