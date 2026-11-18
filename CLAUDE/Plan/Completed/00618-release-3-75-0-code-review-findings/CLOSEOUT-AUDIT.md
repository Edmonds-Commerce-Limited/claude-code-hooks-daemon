# Plan 00618 close-out audit

Every task and every finding the plan tracked, with its disposition and evidence. Every commit cited below is reachable from tag `v3.75.0` (checked with `git rev-list v3.75.0`). Report paths are relative to `subagent-reports/`. Ledger ids are entries in [ledger 00474](../../00474-niggles-ledger-seventeen/NIGGLES.md).

## Tasks

| Task                     | Disposition                                   | Evidence                                                                                                                                                                                                                       |
| ------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1.1 B-1                  | Fixed                                         | red `cd6631424`, fix `8d0e37de4`, budget nit `09f149d7c`; `261116-fix-b1-b2.md`                                                                                                                                                |
| 1.2 B-2                  | Fixed                                         | red `6e16b8ac8`/`9111cee6c`, fix `95e5dc55e`/`d4aa70de7`; `261116-fix-b2-rework.md`, `261116-fix-b2-counter.md`; residuals ledgered N652                                                                                       |
| 1.3 B-3, B-4             | Fixed                                         | red `9348caa50`, fix `2f3349403`; `261116-fix-b3-b5.md`, `261117-fix-older-holes-review.md`; over-deny residuals ledgered N654                                                                                                 |
| 1.4 B-5                  | Fixed                                         | red `9348caa50`/`d4974189c`, fix `42180df61`/`7f0331142`                                                                                                                                                                       |
| 2.1 non-blocking defects | Fixed or owner-decided                        | 17 fixed plus N-16 already fixed (Phase 2 merge `73cd364e5`, `261117-phase2-defects.md`); N-7 and N-8 are D-1 and D-2, implemented (merge `d7c7efe37`, red `6b51f5a0e`, fix `7eb802919`, review `261117-d1-d2-review.md` PASS) |
| 2.2 nits                 | Fixed or owner-decided                        | 12 of 13 fixed (`261117-phase2-defects.md`); T-7 is D-3, owner answered no (journal 2026-11-17 `111756Z`)                                                                                                                      |
| 2.3 format gate          | Fixed                                         | `873880239`                                                                                                                                                                                                                    |
| 2.4 contract hash        | Done inside the release                       | `78999499b` (release branch, regenerated the handler doc and refreshed the contract hash after the re-capture)                                                                                                                 |
| 2.5 load-scaled probe    | Harness half fixed; daemon half owner-decided | red `ce15433cc`, fix `6d309904b`; D-4 answered option A (journal `111756Z`), limit stated in release note 092; option B carried as N632                                                                                        |
| 3.1 hand-off             | Done                                          | loosening reviews per group; the owner's release ran; v3.75.0 tagged and merged through PR 209 (`1e194b693`)                                                                                                                   |

## Step 10 findings (first run, `261116-step10-code-review.md`)

| Item                                            | Disposition                | Evidence                                                                                                             |
| ----------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| B-1 to B-5                                      | Fixed                      | Tasks 1.1 to 1.4 above; all HOLD in the re-run (`261118-step10-rerun.md`)                                            |
| N-1 to N-6, N-9                                 | Fixed                      | branch group merge `dd1e65349`, per-item SHAs in `261117-phase2-branch-group.md`                                     |
| N-7, N-8                                        | Fixed (owner D-1, D-2 yes) | `d7c7efe37`; release note 093; review nits ledgered N650, N651                                                       |
| N-10, N-18, N-20                                | Fixed                      | `261117-phase2-daemon-group.md` (red/fix SHAs per row)                                                               |
| N-11 to N-15, N-17                              | Fixed                      | long-running/config group merge `95e77f0d7`, `261117-phase2-lr-config-group.md`; N-11/N-14 owner notes ledgered N655 |
| N-16                                            | Already fixed              | red `31edbba11`, fix `b0349a116`                                                                                     |
| N-19                                            | Tests added, no defect     | `f5569b91c`; the unchecked `d696d45cc` coverage ledgered N657                                                        |
| T-1, T-2, T-3, T-5, T-6                         | Fixed                      | `261117-phase2-branch-group.md`; T-3 template comment `9610a7f84`                                                    |
| T-4, T-9, T-10, T-12                            | Fixed                      | `261117-phase2-daemon-group.md`                                                                                      |
| T-7                                             | Owner-accepted (D-3 no)    | journal `111756Z`                                                                                                    |
| T-8, T-11, T-13                                 | Fixed                      | `261117-phase2-lr-config-group.md`                                                                                   |
| Speculative: `ls-remote` stderr in problem text | Ledgered                   | N656                                                                                                                 |
| Speculative: `_proven_refnames` cache key       | Not a defect               | the review states it errs to the safe side                                                                           |

## Step 10 re-run findings (`261118-step10-rerun.md`)

| Item                                                              | Disposition     | Evidence                                                                                                                                                                                              |
| ----------------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S-1 `git -C` search unjudged                                      | Fixed           | red `6401e9fa1`, fix `45f713dd2`; review follow-up red `ba740bffc`, fix `b05e57cda`; release note 094                                                                                                 |
| S-1 second review F1, F2, F5                                      | Fixed           | red `72e5a7c0d`, fix `df00a1e70`; release note 095; `261118-s1b-fix.md`                                                                                                                               |
| S-1 second review F3, F4                                          | Ledgered        | N634 to N644                                                                                                                                                                                          |
| S-1 first review test gaps 1 to 5                                 | Pinned by tests | `test_secret_file_guard_git_relocation.py` (`core.worktree`, `--config-env`, `GIT_WORK_TREE`, `--work-tree=sub`, `de*`, `{deep,sub}`, `~`), `test_recursive_search_git_relocation.py` (`sudo -u git`) |
| S-1 fix known limits (wrapper before `git -C`, nested repository) | Ledgered        | N653                                                                                                                                                                                                  |
| S-2 delete-guard wording                                          | Fixed           | `8f3f469cd`                                                                                                                                                                                           |
| S-3 dormancy `warn` unreachable                                   | Ledgered        | N650                                                                                                                                                                                                  |

## Other items

| Item                                              | Disposition | Evidence     |
| ------------------------------------------------- | ----------- | ------------ |
| Playbook test 379 cannot pass                     | Ledgered    | N630         |
| Plan 00609 proof script hard-coded root           | Ledgered    | N631         |
| Lint budget versus the PostToolUse chain deadline | Ledgered    | N632         |
| `test_relay_binary_checker.py` under `--cov`      | Ledgered    | N633         |
| Claude Code changelog review rows for 3.75.0      | Ledgered    | N645 to N648 |
