# Large parked branch assessment (ledger 00466, read-only)

Method: `git merge-tree --write-tree --name-only main <branch>` (conflicts per file counted as `<<<<<<<` hunks in the resulting tree), `git rev-list --count`, ledger rows compared with `git grep` of `| N<n> |` rows across every `CLAUDE/Plan/**/PLAN.md` and `NIGGLES.md` on the branch versus main (152 distinct N-numbers on main). Live checks used `bin/hooks-daemon probe` and `git show main:<path>` greps. No worktree or branch was touched. Nothing here is a code review.

Common note: every branch conflicts in `CLAUDE/Plan/00466-.../PLAN.md` and usually `NIGGLES.md`. Those are ledger-table text conflicts (mechanical, resolved by taking both rows) and are counted below as "ledger files". Source conflicts are the ones that matter.

## 1. worktree-upgrade-scripts

1. For: Plan 00464 upgrade-scripts (installer/upgrade hardening: staged swap, rollback, Layer 2 launch, env -S walking, review rounds 13-20b). Also carries the Plan 00464 commit-gate code via merges.
2. Merge: 201 ahead / 227 behind. Conflicts: 14 files (4 doc/ledger: HOOKS-DAEMON.md, CLAUDE.md, NIGGLES.md, PLAN.md; 10 source/test): `scripts/install/venv.sh`, `core/chain.py`, `docs_qa_commit_gate.py`, `guard_config_commit_gate.py`, `plan_qa_commit_gate.py`, `project_containment.py` (6 hunks), `git_commit_parsing.py` (3), `shell_segmentation.py` (11), `test_project_containment.py`, `test_reserved_word_command_heads.py`. Diff vs merge-base: 301 files, +61k/-8.7k.
3. Still needed: yes. Main has only the old `scripts/upgrade.sh`, `upgrade_version.sh`, `install/upgrade_transition.sh`; the branch's new scripts (`staged_swap.sh`, `in_place_handoff.sh`, `rollback.sh` changes, etc.) do not exist on main, and Plan 00464 is "Not Started" on main. Checked via `git ls-tree main` and plan status.
4. Branch-only rows: N108 (`destructive_git` denies a git call split across lines; Open), N121 (secret/flaggable guards deny ordinary review commands; Open).
5. Recommendation: REFIX-SMALL. It overlaps the plan-464 branch (shared commit-gate/shell_segmentation code, 11 hunks in one file) and is 301 files. Land the plan-464 branch first in slices; the upgrade-scripts installer work is shell-script-only (`scripts/install/*`, `scripts/upgrade*.sh`) and can be split off as its own small branch cut from this one's `scripts/` tree, leaving the commit-gate half to plan-464. Only `venv.sh` conflicts in that slice.

## 2. worktree-d-00421

1. For: Plan 00421 security detectors and CI enforcement, review rounds 4-8 (secret_file_guard exemptions, scan_scope walk, remote-docs refusals, secret word list handling).
2. Merge: 124 ahead / 212 behind. Conflicts: 9 files (CLAUDE.md, NIGGLES.md, PLAN.md; `daemon/cli.py` 2 hunks, `handlers/registry.py` 2, `process_probe.py` 1, `secret_file_matching.py` 1, `test_secret_file_guard.py` 4, `test_secret_file_matching.py` 2). Diff: 368 files, +38k/-2.9k.
3. Still needed: yes. Plan 00421 is "Not Started" on main. Spot check: main `daemon/cli.py` ~line 6875 still only prints a WARNING when the remote-docs sensitive-content scanner cannot load (N250 fix makes it refuse). Checked by reading main.
4. Branch-only rows (all Remedied): N170, N171, N172, N173, N174, N175, N228, N229, N230, N231, N242, N243, N248, N250.
5. Recommendation: REFIX-SMALL. Modest conflict count but 368 files and it overlaps small-a in `secret_file_matching.py`/`test_secret_file_guard.py`. Minimal path: land a small-a decision first, then cut fresh small branches per row group (N250 remote-docs refuse-on-unloadable-scanner in `cli.py` is a few lines; N172 ImportError of secret-term rule; N231 unreadable word list fails closed). Owner may prefer LAND after small-a is settled, since text conflicts are only 9 files.

## 3. worktree-plan-464-commit-gate-repo

1. For: Plan 00464 commit gates judge the checkout the command runs in (worktree commits; M4 script-read ordering; eval re-walk N117/N119; landing merges).
2. Merge: 89 ahead / 212 behind. Conflicts: 12 files (3 ledger/doc; `core/chain.py`, `docs_qa_commit_gate.py`, `guard_config_commit_gate.py`, `plan_qa_commit_gate.py`, `project_containment.py` 6 hunks, `git_commit_parsing.py` 3, `shell_segmentation.py` 11, two test files). Diff: 102 files, +37k/-1.1k.
3. Still needed: yes. Plan 00464 is "Not Started" on main; main's N23 row says worktree commits are judged against the main checkout's staged content ("Graduated to Plan 00464"). Checked via ledger and plan status. Main contains the N106 containment rewrite, so `project_containment.py` conflicts are real overlaps, not textual noise.
4. Branch-only rows: N119 (eval re-walk 3^depth; Remedied). Note: N117 is used on main for a different entry (n101 branch).
5. Recommendation: REFIX-SMALL. The 11 hunks in `shell_segmentation.py` and 6 in `project_containment.py` need semantic resolution against main's newer code. Minimal fresh fix: change the three commit gates (`docs_qa_commit_gate`, `plan_qa_commit_gate`, `guard_config_commit_gate`) to resolve the repo from the command's `git -C`/cd target instead of the payload `cwd`, using main's current containment helper; leave the shell_segmentation walker changes to a later slice.

## 4. worktree-n466-small-a

1. For: ledger 00466 "small-a" guard batch: secret_file_guard / quarantine_artefact_read_guard read commands (grep regex vs path, glob scans, recursive readers, cd/pushd tracking, `git grep`, `/proc/self/cwd`).
2. Merge: 61 ahead / 212 behind. Conflicts: 12 files (2 ledger; `quarantine_artefact_read_guard.py` 1, `secret_file_guard.py` 3, `secret_file_matching.py` 11, `shell_expansion.py` 4, `shell_segmentation.py` 4, and five test files with 3+6+2+1+2 hunks).
3. Still needed: mostly yes. Live check on this session's main: a Bash command whose text contained a `$VAR/...` glob and a brace group was denied with `TooManyToEnumerateError` (N183, N134 shape still live). A plain `grep -rn 'x[.]yaml' src/` probe was allowed (N124's simple shape not reproduced; the bug is shape-specific, so unknown for that row).
4. Branch-only rows: Remedied: N124, N125, N129, N130, N131, N132, N136, N143, N144, N150, N151, N152, N153, N154, N183, N184, N201, N220, N221; N134 "Remedied (heredoc half: N101)"; Open: N249, N257.
5. Recommendation: REFIX-SMALL. Heavy text conflict in `secret_file_matching.py` (11 hunks) with main's n101 and containment changes, plus overlap with d-00421 and agent-a9ed. Minimal fresh fix: (a) make the strict glob/brace scan expand or skip `$VAR` and `{a,b}` words instead of crashing (N183, N130/N131); (b) treat the first non-option grep operand as a pattern, not a path (N124/N129/N201). Do those two as separate small branches; defer the rest of the rows.

## 5. agent-a9ed87335fdbd2ee9-2dda8b46

1. For: ledger 00466 N23 (remote_docs_provenance containment check that never returns None-on-error; symlink loop on Python 3.13) and N66 (singleton race tests forced by interleaving instead of `time.sleep`).
2. Merge: 47 ahead / 212 behind. Conflicts: 5 files (PLAN.md; `core/chain.py`, `secret_file_guard.py`, `handlers/registry.py`, `secret_file_matching.py`, 1 hunk each). Smallest of the source-conflicting branches.
3. Still needed: yes. Main still lists N23 and N66 as Open, and `tests/unit/core/test_bounded_dispatch.py` on main still has `time.sleep(0.02)` at lines 302, 384, 387. Checked by `git grep` on main.
4. Branch-only rows: none (it changes the status of N23 and N66 to Remedied; both already exist on main as Open).
5. Recommendation: LAND. Five files, one hunk each, and the ledger conflict is a status cell. Resolve `chain.py`/`registry.py`/`secret_file_guard.py` by taking main's side and re-applying the branch's small diff; then run only the N23/N66 tests. If a hunk in `secret_file_matching.py` is not trivial, fall back to REFIX-SMALL for N66 alone (test-only change).

## 6. worktree-p422-close

1. For: closing ledger 00422 (niggles ledger fifteen) rounds 8e-8j: shell-string depth reading, the plan-folder `mkdir` guard, wrapper tables, heredoc parse, git guard time budget, release notes 211.
2. Merge: 45 ahead / 227 behind. Conflicts: 18 files (5 ledger/report incl. Completed/00422 NIGGLES and PLAN; `orchestrator_simulate.py` 3, `core/chain.py` 3, `daemon_location_guard.py`, `merge_to_main_approval.py`, `plan_journal_guard.py`, `plan_number_helper.py` 2, `bash_file_writes.py` 7, `shell_expansion.py`, `shell_segmentation.py` 13, four test files).
3. Still needed: yes for at least N241. This session's main denied a `bash -c` command whose inner git commit message contained the text `git stash` (the R-GIT-STASH-PUSH guard read the message value as a command), which is the N241 defect ("live on main"). Checked by an accidental live probe.
4. Branch-only rows: Remedied: N141, N178, N180, N185, N186, N187, N188, N198, N199, N200, N239, N240, N241; N134 (Open, small-a); N179 (a row whose table cell is split by `\|`, status unreadable here).
5. Recommendation: REFIX-SMALL. 13 hunks in `shell_segmentation.py` and 7 in `bash_file_writes.py` against main's rewritten code make a merge a re-implementation. Minimal fresh fix for the live defect: in the git guards, treat the value after `-m`/`-F` as data at any nesting depth of `bash -c` strings (N241), and add `setsid`/`doas`/`chronic`/`coproc`/`strace`/`sg` to the shared wrapper table (N185, N198). Leave the plan-folder mkdir rows (N141, N178-N199) unless a live probe shows them.

## 7. worktree-n466-lifecycle

1. For: daemon lifecycle and PID-file safety (start lock, stale PID removal, successor's PID/socket, EPERM as alive, recovery deny carve-out, installer removal locking, concurrent hook starts).
2. Merge: 42 ahead / 212 behind. Conflicts: 3 files only, all docs: NIGGLES.md (2 hunks), PLAN.md (2), `CLAUDE/Security/FailOpenBoundaries.md` (1). No source or test conflicts (source auto-merges, including `daemon/cli.py` and `handlers/registry.py`).
3. Still needed: yes. `git grep` on main finds no start-lock (`flock`/`start_lock`) in `init.sh`, `.claude/init.sh` or the lifecycle module. The ledger rows are not on main at all.
4. Branch-only rows (all Remedied): N126, N127, N128, N139, N140, N160, N161, N162, N163, N164, N165, N190, N191, N192, N193, N202, N203, N204, N205, N206, N225, N232.
5. Recommendation: LAND. Only ledger/doc table conflicts; code merges clean. Resolve the three doc files by keeping both sides' rows, then run the lifecycle test subset. Best value-for-effort of the nine.

## 8. worktree-d-00376

1. For: Plan 00376 pre-upgrade phase with migration and confirm gate (env sanitising, Layer 1/Layer 2 launch, N29/N56 fixes, error-hiding audit; review 3 and 4 fixes).
2. Merge: 31 ahead / 262 behind (oldest base). Conflicts: 5 files, all non-Python: `.claude/HOOKS-DAEMON.md`, `CLAUDE.md` (2 hunks), PLAN.md, `UNRELEASED/post-upgrade-tasks/README.md`, `scripts/qa/error_hiding_exclusions.json` (1 hunk). Source and test files auto-merge. Diff: 107 files, +14k/-0.9k.
3. Still needed: yes for the plan's deliverable. Plan 00376 is "Not Started" on main and main has no `scripts/install/env_sanitise.sh` (branch adds it). But it overlaps upgrade-scripts (both edit `upgrade.sh`, `venv.sh`, `resolve_venv.sh`, `python_discovery.sh`); the upgrade-scripts branch may supersede parts. Unknown whether upgrade-scripts fully contains this branch's content; not verified.
4. Branch-only rows: none.
5. Recommendation: LAND, conditional on ordering: land this before or instead of the upgrade-scripts branch, since its conflicts are docs/JSON only. If the owner decides upgrade-scripts supersedes it, DROP this one instead; check `git merge-base --is-ancestor worktree-d-00376 worktree-upgrade-scripts` before deciding (not run).

## 9. agent-aa0e5105724aa123b-b9ce2f39

1. For: ledger 00466 N38/N42 (PreToolUse chain quadratic time on quote-heavy commands; quoted-heredoc blanking hides executed text), gate fixes and goal_injection latching.
2. Merge: 37 ahead / 212 behind. Conflicts: 9 files, all source/test: `core/chain.py` 3, `core/utils.py` 3, `command_evasion.py` 2, `shell_segmentation.py` 8, and five test files (1+1+1+3+4).
3. Still needed: yes. Main lists N38 and N42 as "In progress" (not remedied) and this branch is where the work sits. Not reproduced by a timing run (unknown for current speed on main, since main's later chain changes may have reduced it).
4. Branch-only rows: N41 (chain still spends linear seconds on a heredoc-opener-heavy command; Open).
5. Recommendation: REFIX-SMALL. 8 hunks in `shell_segmentation.py` plus `chain.py`/`utils.py` collide with main's bounded_dispatch and signal-safety work. Minimal fresh fix: time a quote-heavy 5k-character command on main first; if quadratic, memoise the quote-scan per command in the segmenter (one pass, cached offsets) and add a performance test that asserts a linear bound. N42 (heredoc blanking) is a separate small fix in `command_evasion.py`.

## Summary

| branch                             | recommendation                               | conflicts (files: ledger/doc + source/test) | branch-only entries                                         |
| ---------------------------------- | -------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------- |
| worktree-upgrade-scripts           | REFIX-SMALL                                  | 14 (4 + 10)                                 | N108, N121 (Open)                                           |
| worktree-d-00421                   | REFIX-SMALL                                  | 9 (3 + 6)                                   | N170-N175, N228-N231, N242, N243, N248, N250 (14, Remedied) |
| worktree-plan-464-commit-gate-repo | REFIX-SMALL                                  | 12 (3 + 9)                                  | N119 (Remedied)                                             |
| worktree-n466-small-a              | REFIX-SMALL                                  | 12 (2 + 10)                                 | 19 Remedied, N134 half, N249 and N257 Open                  |
| agent-a9ed87335fdbd2ee9-2dda8b46   | LAND                                         | 5 (1 + 4)                                   | none (flips N23, N66 to Remedied)                           |
| worktree-p422-close                | REFIX-SMALL                                  | 18 (5 + 13)                                 | 13 Remedied, N134 Open, N179                                |
| worktree-n466-lifecycle            | LAND                                         | 3 (3 + 0)                                   | 22 Remedied (N126-N232 lifecycle set)                       |
| worktree-d-00376                   | LAND (or DROP if upgrade-scripts supersedes) | 5 (5 + 0)                                   | none                                                        |
| agent-aa0e5105724aa123b-b9ce2f39   | REFIX-SMALL                                  | 9 (0 + 9)                                   | N41 (Open)                                                  |

Suggested order: lifecycle, d-00376 and a9ed first (cheap merges), then small fresh fixes for small-a, p422-close and N38/N42, then slice plan-464, 00421 and upgrade-scripts.
