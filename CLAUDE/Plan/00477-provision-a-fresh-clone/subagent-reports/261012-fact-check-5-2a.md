# Fact check: Plan 00477 Task 5.2a diff (against /workspace main)

No claims REFUTED.

| #   | Claim                                                                                           | Verdict           | Evidence                                                                                                                                                                     |
| --- | ----------------------------------------------------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "by the steps Task 5.2 names"                                                                   | VERIFIED          | PLAN.md:128-132 Task 5.2 lists fetch tag, check version.py, rebuild venv, restart                                                                                            |
| 2   | "the target release's pre-deploy gate (Task 5.3)"                                               | VERIFIED          | PLAN.md:133-138 Task 5.3 says the sync runs the target release's own pre-deploy gate; pre-deploy phase exists (tests/integration/test_upgrade_pre_deploy_phase_placement.py) |
| 3   | Drift advisories exist in `init.sh`, `version_check`, `daemon_sync_after_merge`                 | VERIFIED          | init.sh:48,2826 (VERSION_MISMATCH); src/.../session_start/version_check.py:321-361; src/.../post_tool_use/daemon_sync_after_merge.py                                         |
| 4   | These advisories currently name `upgrade` (implied by "name `provision` rather than `upgrade`") | VERIFIED          | init.sh:48 "upgrade needed"; version_check.py:324-325 `args=upgrade {expected}`; daemon_sync_after_merge.py:184 `daemon_cli_command("upgrade")`                              |
| 5   | `provision` exists as a command to extend                                                       | VERIFIED          | .claude/provision.sh exists; init.sh:383-431 recognises `provision`                                                                                                          |
| 6   | Header `**GitHub Issue**: #78`                                                                  | UNVERIFIABLE-HERE | Needs `gh issue view 78`; the repo's git log references "Addresses #78" only                                                                                                 |

Remaining added text (refuses modified clone or foreign origin, restores previous version on failure) states intended behaviour, not current state, and was skipped.

Counts: 6 claims: 5 verified, 0 refuted, 1 unverifiable.
