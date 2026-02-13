# Plan 00048: Repository Cruft Cleanup

**Status**: Complete (2026-02-11)
**Created**: 2026-02-11
**Owner**: Main Claude
**Priority**: Medium
**Estimated Effort**: 1-2 hours

## Overview

Full audit of the repository identified accumulated cruft: spurious files, stale worktrees (~700MB), duplicate/empty plan folders, stale root-level docs, and config backup clutter. This plan tracks cleanup of all identified items.

## Goals

- Remove all spurious/accidental files from the repo
- Clean up stale worktrees (reclaim ~700MB disk)
- Archive or delete empty/duplicate plan folders
- Consolidate stale root-level documentation
- Clean up config backup files
- Update Plan README.md to reflect changes

## Non-Goals

- Refactoring code or handlers (separate plans exist for that)
- Changing documentation architecture (just removing clear cruft)
- Modifying active plans (only touching empty/stale ones)

## Tasks

### Phase 1: Delete Spurious Files (Immediate)

- [x] **Task 1.1**: Delete `/workspace/=5.9` (accidental pip output redirect)
  - Verified: Contains `pip install psutil` output, clearly accidental
  - Action: `rm /workspace/=5.9`

### Phase 2: Clean Up Stale Worktrees (~700MB)

- [x] **Task 2.1**: Remove stale worktrees from `untracked/worktrees/`
  - `worktree-child-plan-00021-refactor` (204MB) - Plan 00021 completed 2026-02-06
  - `worktree-child-plan-003-integration` (173MB) - Plan 003 completed 2026-02-06
  - `worktree-plan-00021` (165MB) - Plan 00021 completed 2026-02-06
  - `worktree-plan-003` (165MB) - Plan 003 completed 2026-02-06
  - Action: `git worktree remove` for each, then delete directories
  - Verify: `git worktree list` shows only main worktree

### Phase 3: Plan Directory Cleanup

- [x] **Task 3.1**: Delete empty plan `00036-sleepy-puzzling-backus/`
  - PLAN.md is 0 bytes, completely empty draft
  - README.md lists it as "(Unnamed Draft)"
  - Action: `rm -rf` the directory

- [x] **Task 3.2**: Rename duplicate-named plans for clarity
  - `00034-sleepy-puzzling-backus/` - Actually "Model-Aware Agent Team Advisor" (147 lines)
    - Rename to `00034-model-aware-agent-team-advisor/`
  - `00035-sleepy-puzzling-backus/` - Actually "StatusLine Data Cache + Model-Aware Advisor" (216 lines)
    - Rename to `00035-statusline-data-cache-model-advisor/`
  - Action: `git mv` to rename
  - Note: There's also a `Completed/00034-library-plugin-separation-qa/` which is a different plan (completed). The active 00034 is a different topic that reused the number. This is confusing but renaming will help distinguish them.

- [x] **Task 3.3**: Update `CLAUDE/Plan/README.md`
  - Update links for renamed plans
  - Remove entry for deleted 00036
  - Fix plan statistics (Active count: 7 not 8 after removing empty draft)

### Phase 4: Root-Level Stale Documentation

- [x] **Task 4.1**: Evaluate `BUG_FIX_STOP_EVENT_SCHEMA.md`
  - This is a historical bug-fix write-up (141 lines) for a specific bug from 2026-01-27
  - All the info is captured in code/tests already
  - Action: Move to `CLAUDE/Plan/Completed/` as historical reference, or delete
  - Decision needed: Keep as historical doc or remove?

- [x] **Task 4.2**: Evaluate `BUG_REPORTING.md`
  - Active user-facing document (195 lines) with bug reporting guide
  - References `scripts/debug_info.py` and GitHub issues URL
  - This is legitimate - referenced in CLAUDE/CLAUDE.md
  - Action: Keep (no change needed)

### Phase 5: Config Backup Cleanup

- [x] **Task 5.1**: Clean up `.claude/hooks-daemon.yaml.bak`
  - Only one backup file found (plus .example which is legitimate)
  - `.bak` is from installer backup mechanism - may be regenerated
  - Action: Delete `.bak` if it's stale (compare dates)
  - Note: `.example` is a template file, keep it

### Phase 6: Verification

- [x] **Task 6.1**: Run full QA suite
  - `./scripts/qa/run_all.sh` - ensure nothing broke
- [x] **Task 6.2**: Restart daemon
  - `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - Verify: Status RUNNING
- [x] **Task 6.3**: Commit cleanup changes

## Success Criteria

- [x] No spurious files in repo root
- [x] Stale worktrees removed (~700MB reclaimed)
- [x] No empty plan folders
- [x] Plan folders have descriptive names (no "sleepy-puzzling-backus")
- [x] Plan README.md accurate and up-to-date
- [x] QA passes, daemon starts successfully

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Worktree removal fails (dirty state) | Low | Low | Force remove if needed, data is in completed plans |
| Plan rename breaks references | Low | Low | grep for old names, update any refs |
| Removing .bak breaks installer | Low | Low | Installer recreates backups as needed |

## Notes

### Items Investigated but NOT Cruft

- **Active plans 00032, 00038, 00041, 00044, 00045**: Legitimate "Not Started" or "In Progress" plans with real content. Not stale.
- **`BUG_REPORTING.md`**: Active user-facing doc, referenced in CLAUDE/CLAUDE.md
- **`.claude/hooks-daemon.yaml.example`**: Template file, keep
- **`untracked/` directory**: Properly gitignored, only worktrees inside are stale
- **`docs/` directory**: Legitimate user-facing documentation

### Duplicate Plan Number Issue

Plan 00034 exists in TWO places:
- `CLAUDE/Plan/00034-sleepy-puzzling-backus/` (active, model-aware advisor topic)
- `CLAUDE/Plan/Completed/00034-library-plugin-separation-qa/` (completed, different topic)

This happened because the auto-naming system generated the same random name. The completed plan was moved to Completed/ and the number was reused. Renaming the active one will reduce confusion.
