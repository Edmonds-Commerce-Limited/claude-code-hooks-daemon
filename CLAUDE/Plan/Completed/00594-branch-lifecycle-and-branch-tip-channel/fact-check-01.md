# Fact-check 01 (Plan 00594 PLAN.md)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | `--journal --title` with no `--ref` gives heading `· —   — title` | VERIFIED | CLAUDE/Plan/mkplan.bash:517 (`ref="—"`), :625-627 (`## time · cat · $ref` + `   — title`) |
| 2 | Daemon formatter skips journal files | VERIFIED | handlers/post_tool_use/markdown_table_formatter.py:329 `is_journal_file` exemption |
| 3 | Plan 00571 exists, about three pools | VERIFIED | Completed/00571-branch-pools-parked-merged-caps |
| 4 | Plan 00254 exists (tip re-check before delete) | VERIFIED | Completed/00254-delete-branch-tip-recheck-before-delete |
| 5 | Plan 00570 exists (containment, remote archive refs) | VERIFIED | Completed/00570-branch-containment-remote-archive-refs |
| 6 | Plan 00535 exists (upgrade handover) | VERIFIED | CLAUDE/Plan/00535-upgrade-handover-without-live-daemon-rebuild (Not Started) |
| 7 | Parking is a commit trailer | VERIFIED | core/branch_park.py:1-4 Parked-Reason/Parked-By trailers |
| 8 | Regenerable list exists for worktree removal | VERIFIED | utils/regenerable_paths.py:25 DEFAULT_REGENERABLE_STORES; core/branch_cleanup.py:15 |
| 9 | Pools have no owner dimension | VERIFIED (by absence) | no owner/creator reference in core/branch_inventory.py, branch_creation.py, guard |
| 10 | "Branches have no owner" (class 7) | PARTLY REFUTED | core/branch_records.py:34 already stores a `hooksDaemonCreator` record (3 keys under branch.<name>); the plan's Owner open question lists "creator trailer/branch-touch record" candidates without noting this existing record. Remote-only branches lacking it remains plausible. |
| 11 | Client-use counts (275/135 branches etc.) | UNVERIFIABLE-HERE | by design |

Not checked: whether the default regenerable list lacks the specific vendor dirs in class 6 (list is present at regenerable_paths.py:25; not compared item by item).

Refuted: none outright; #10 needs a wording fix (mention the existing creator record).
