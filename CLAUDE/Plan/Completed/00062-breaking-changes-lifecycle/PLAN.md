# Plan 00062: Breaking Changes Lifecycle - Complete Documentation Loop

**Status**: Complete (2026-02-17)
**Created**: 2026-02-17
**Owner**: Claude (Sonnet 4.5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Fix the systemic breaking changes documentation gap that causes users to upgrade across multiple versions and encounter "unknown handler" errors without guidance. This plan closes the complete loop: from release process documentation → upgrade guides → config migration → validation.

**Triggering Issue**: User upgraded v2.10.1 → v2.13.0 and encountered unknown handler errors for `validate_sitemap`, `remind_validator`, and `validate_eslint_on_write` which were removed/renamed in intermediate versions. No upgrade guides existed for v2.10→v2.11, v2.11→v2.12, or v2.12→v2.13.

## Goals

1. **Close Documentation Loop**: Ensure breaking changes are properly documented from release through upgrade
2. **Generate Missing Guides**: Create upgrade guides for v2.10→v2.11, v2.11→v2.12, v2.12→v2.13
3. **Enhance Release Process**: Update `/release` skill to mandate breaking change documentation
4. **Smart Config Migration**: Detect removed/renamed handlers during upgrade with migration suggestions
5. **Pre-Upgrade Validation**: Warn users about incompatible config before starting upgrade
6. **Enforce Guide Reading**: Make upgrade script require confirmation of reading breaking change docs

## Non-Goals

- Automatic config migration (too risky - user confirmation required)
- Retroactive fixes for versions older than v2.10.0
- Changes to current handler removal process (that's working correctly)

## Context & Background

### Current State

**Documentation**:
- CHANGELOG.md documents what changed but not how to migrate
- RELEASES/*.md has detailed release notes but no prominent breaking changes section
- UPGRADES/ directory only has v2.0-to-v2.1 guide (missing 12 versions)
- RELEASING.md defines release process but doesn't enforce upgrade guide creation

**Upgrade Process** (`scripts/upgrade_version.sh`):
- Lines 408-414: Mentions UPGRADES/ directory but doesn't enforce reading
- Config preservation (lines 278-306): Blind merge that doesn't detect removals
- Validation happens AFTER upgrade completes (line 372)
- No pre-upgrade validation of config compatibility

**Validation** (`src/claude_code_hooks_daemon/config/validator.py`):
- Line 349-370: Detects unknown handlers with fuzzy matching suggestions
- Works correctly but runs too late (after upgrade completes)

### What Went Wrong (v2.10.1 → v2.13.0)

**v2.11.0 Breaking Changes** (2026-02-12):
- Removed `validate_sitemap` (PostToolUse) - project-specific
- Removed `remind_validator` (SubagentStop) - project-specific
- CHANGELOG line 201-204: Documents removal but no migration guide

**v2.12.0 Breaking Changes** (2026-02-12):
- Renamed `validate_eslint_on_write` → `lint_on_edit`
- Extended to 9 languages (was ESLint-only)
- No upgrade guide, no migration documentation

**User Experience**:
```
1. User at v2.10.1 runs upgrade script
2. Upgrade completes successfully (code updated)
3. Daemon starts in degraded mode
4. Config validation shows errors AFTER success message
5. User confused - "upgrade succeeded" but broken
6. No guidance on what to change
```

## Tasks

### Phase 1: Document Historical Breaking Changes

**Goal**: Create missing upgrade guides for v2.10→v2.11→v2.12→v2.13

- [ ] **Task 1.1**: Create `CLAUDE/UPGRADES/v2/v2.10-to-v2.11/` structure
  - [ ] Write `v2.10-to-v2.11.md` main guide
  - [ ] Document `validate_sitemap` removal (move to project handlers)
  - [ ] Document `remind_validator` removal (move to project handlers)
  - [ ] Create `config-before.yaml` example
  - [ ] Create `config-after.yaml` example
  - [ ] Create `migration-script.sh` to help users

- [ ] **Task 1.2**: Create `CLAUDE/UPGRADES/v2/v2.11-to-v2.12/` structure
  - [ ] Write `v2.11-to-v2.12.md` main guide
  - [ ] Document `validate_eslint_on_write` → `lint_on_edit` rename
  - [ ] Document strategy pattern changes (9 languages)
  - [ ] Create `config-before.yaml` example
  - [ ] Create `config-after.yaml` example
  - [ ] Create `migration-script.sh` for rename

- [ ] **Task 1.3**: Create `CLAUDE/UPGRADES/v2/v2.12-to-v2.13/` structure
  - [ ] Write `v2.12-to-v2.13.md` main guide
  - [ ] Document any breaking changes (if none, mark as safe upgrade)
  - [ ] Create `config-before.yaml` example
  - [ ] Create `config-after.yaml` example

- [ ] **Task 1.4**: Update `CLAUDE/UPGRADES/README.md`
  - [ ] Add v2.10→v2.11→v2.12→v2.13 upgrade path
  - [ ] Document how to find upgrade guides for multi-version jumps
  - [ ] Add examples of chaining guides

### Phase 2: Enhance Release Process Documentation

**Goal**: Ensure `/release` skill mandates breaking change documentation

- [ ] **Task 2.1**: Update `CLAUDE/development/RELEASING.md`
  - [ ] Add mandatory "Breaking Changes Check" step after Opus review (before QA)
  - [ ] Require BREAKING CHANGES section in release notes if any exist
  - [ ] Mandate upgrade guide creation for breaking changes
  - [ ] Add checklist for release agent to verify

- [ ] **Task 2.2**: Update `.claude/agents/release-agent.md`
  - [ ] Add breaking changes detection to agent workflow
  - [ ] Instruct agent to scan CHANGELOG for "Removed", "Changed", "BREAKING"
  - [ ] Require agent to create upgrade guide template if breaking changes found
  - [ ] Add validation step to confirm upgrade guide exists

- [ ] **Task 2.3**: Update `.claude/skills/release/skill.md`
  - [ ] Add breaking changes check to skill orchestration
  - [ ] Require main Claude to verify upgrade guide before proceeding
  - [ ] Block release if breaking changes exist without upgrade guide
  - [ ] Add example output showing blocked release

- [ ] **Task 2.4**: Update CHANGELOG format documentation
  - [ ] Add "Migration:" sub-section template for Removed/Changed entries
  - [ ] Document standard migration patterns (rename, remove, move to project)
  - [ ] Provide examples of good vs bad migration documentation

### Phase 3: Smart Config Migration

**Goal**: Detect removed/renamed handlers during upgrade with suggestions

- [ ] **Task 3.1**: Create `scripts/install/config_diff_analyzer.sh`
  - [ ] Compare handler names in old config vs new default
  - [ ] Detect removed handlers (exist in old, not in new)
  - [ ] Detect renamed handlers (fuzzy match to suggest replacements)
  - [ ] Detect new handlers (exist in new, not in old)
  - [ ] Output structured JSON for Python consumption

- [ ] **Task 3.2**: Create `src/claude_code_hooks_daemon/install/breaking_changes_detector.py`
  - [ ] Parse config_diff_analyzer.sh output
  - [ ] Build handler removal/rename database from CHANGELOG parsing
  - [ ] Match detected changes to known breaking changes
  - [ ] Generate migration suggestions (remove, rename, disable)
  - [ ] Format user-friendly warnings

- [ ] **Task 3.3**: Integrate into `scripts/upgrade_version.sh`
  - [ ] Call breaking_changes_detector after config backup (Step 5, line 207)
  - [ ] Display warnings BEFORE proceeding with upgrade
  - [ ] Require user confirmation if breaking changes detected
  - [ ] Log detected issues to upgrade log file

- [ ] **Task 3.4**: Update `scripts/install/config_preserve.sh`
  - [ ] After merge, call breaking_changes_detector on result
  - [ ] Append warnings to preserved config as comments
  - [ ] Generate `config-migration-notes.txt` next to backup
  - [ ] Print summary of issues found

### Phase 4: Pre-Upgrade Validation

**Goal**: Validate config compatibility before starting upgrade

- [ ] **Task 4.1**: Create `src/claude_code_hooks_daemon/install/upgrade_compatibility.py`
  - [ ] Check if handlers in user config exist in target version
  - [ ] Use validator.py's handler discovery mechanism
  - [ ] Build compatibility report (compatible, incompatible, warnings)
  - [ ] Suggest required upgrade guides to read

- [ ] **Task 4.2**: Add pre-upgrade validation to `scripts/upgrade_version.sh`
  - [ ] Call compatibility check in Step 2 (Pre-upgrade checks, line 139)
  - [ ] Display compatibility report before proceeding
  - [ ] If incompatibilities found, list required upgrade guides
  - [ ] Require explicit --force flag to proceed with incompatibilities

- [ ] **Task 4.3**: Create user-friendly compatibility report format
  - [ ] ✅ Compatible handlers (no action needed)
  - [ ] ⚠️ Removed handlers (migration required)
  - [ ] 🔄 Renamed handlers (config update required)
  - [ ] 📚 Required reading: List upgrade guides to review

### Phase 5: Enforce Upgrade Guide Reading

**Goal**: Make upgrade script pause and require confirmation of reading docs

- [ ] **Task 5.1**: Update `scripts/upgrade_version.sh` Step 6 (Checkout, line 228)
  - [ ] BEFORE checkout, detect version jump (current → target)
  - [ ] List all intermediate versions being skipped
  - [ ] For each version, check if UPGRADES/ guide exists
  - [ ] Display required reading list with file paths

- [ ] **Task 5.2**: Add interactive confirmation prompt
  - [ ] Show list: "You are upgrading v2.10.1 → v2.13.0 (skipping v2.11.0, v2.12.0)"
  - [ ] Show guides: "Required reading: UPGRADES/v2/v2.10-to-v2.11/..., UPGRADES/v2/v2.11-to-v2.12/..."
  - [ ] Prompt: "Have you read all upgrade guides? (yes/no/show)"
  - [ ] "show" option: Display each guide using $PAGER (less)
  - [ ] Block upgrade until user confirms reading

- [ ] **Task 5.3**: Add --skip-reading-confirmation flag
  - [ ] For automated/CI environments
  - [ ] Document that this is dangerous
  - [ ] Log warning if used

- [ ] **Task 5.4**: Log upgrade guide reading in upgrade log
  - [ ] Record which guides were shown
  - [ ] Record user confirmation or --skip-reading-confirmation
  - [ ] Include in rollback info for debugging

### Phase 6: Update Release Notes Format

**Goal**: Add prominent BREAKING CHANGES section to all future releases

- [ ] **Task 6.1**: Create `CLAUDE/UPGRADES/upgrade-template/BREAKING-CHANGES-TEMPLATE.md`
  - [ ] Template for breaking changes section
  - [ ] Format: Problem → Solution → Migration Steps
  - [ ] Examples from v2.11.0 and v2.12.0

- [ ] **Task 6.2**: Update release agent to generate BREAKING CHANGES section
  - [ ] Scan CHANGELOG for Removed/Changed entries during changelog generation
  - [ ] Extract migration notes from CHANGELOG entries
  - [ ] Generate BREAKING CHANGES section at top of release notes
  - [ ] Link to upgrade guide if one exists

- [ ] **Task 6.3**: Retroactively update v2.11.0 and v2.12.0 release notes
  - [ ] Add BREAKING CHANGES section to `RELEASES/v2.11.0.md`
  - [ ] Add BREAKING CHANGES section to `RELEASES/v2.12.0.md`
  - [ ] Link to newly created upgrade guides
  - [ ] Commit with message: "Docs: Add missing BREAKING CHANGES sections to v2.11/v2.12 release notes"

### Phase 7: Testing & Documentation

**Goal**: Ensure new process works end-to-end

- [ ] **Task 7.1**: Test upgrade path with breaking changes
  - [ ] Create test project at v2.10.1 with old handlers
  - [ ] Run upgrade to v2.13.0
  - [ ] Verify pre-upgrade validation shows warnings
  - [ ] Verify upgrade guide reading is enforced
  - [ ] Verify config migration suggestions shown
  - [ ] Verify post-upgrade validation passes after manual fixes

- [ ] **Task 7.2**: Test multi-version jump without breaking changes
  - [ ] Verify upgrade from v2.5.0 → v2.7.0 (if no breaking changes)
  - [ ] Verify guide reading is skipped when no guides exist
  - [ ] Verify upgrade proceeds smoothly

- [ ] **Task 7.3**: Update `CLAUDE/LLM-UPDATE.md`
  - [ ] Document new breaking changes detection
  - [ ] Document upgrade guide reading requirement
  - [ ] Document how to handle incompatibilities
  - [ ] Add examples of pre-upgrade validation output

- [ ] **Task 7.4**: Update `CONTRIBUTING.md`
  - [ ] Add section on creating upgrade guides
  - [ ] Reference BREAKING-CHANGES-TEMPLATE.md
  - [ ] Document when upgrade guides are required
  - [ ] Add to pre-release checklist

- [ ] **Task 7.5**: Run full QA suite
  - [ ] `./scripts/qa/llm_qa.py all`
  - [ ] All checks must pass
  - [ ] Fix any issues introduced

## Dependencies

**Depends on**: None
**Blocks**: Future releases (until breaking changes process is fixed)
**Related**:
- Plan 00047: User feedback resolution (similar upgrade issues)
- All future release plans

## Technical Decisions

### Decision 1: Store handler removal/rename mappings in code vs CHANGELOG parsing

**Context**: Need to detect when handlers were removed/renamed across versions

**Options Considered**:
1. **Parse CHANGELOG.md dynamically** - Extract removals/renames from changelog entries
   - Pros: Single source of truth, no duplication
   - Cons: Brittle parsing, format changes break detection

2. **Maintain database in Python code** - Dict mapping versions to changes
   - Pros: Reliable, typed, easy to query
   - Cons: Duplication, must remember to update

3. **Hybrid: CHANGELOG with structured markers** - Use `<!-- BREAKING: handler:validate_sitemap:removed -->` markers
   - Pros: Single source of truth, parseable
   - Cons: Requires discipline, existing changelog must be updated

**Decision**: Option 3 (Hybrid) - Add structured markers to CHANGELOG

**Rationale**:
- Keeps CHANGELOG as source of truth
- Markers are invisible to humans reading markdown
- Can be parsed reliably
- Existing entries can be updated retroactively
- Validates that breaking changes are documented in changelog

**Date**: 2026-02-17

### Decision 2: Interactive vs automatic config migration

**Context**: When removed handlers are detected, should we automatically fix config?

**Options Considered**:
1. **Automatic removal** - Remove obsolete handlers from config
   - Pros: Frictionless upgrade
   - Cons: Dangerous, might remove user customizations

2. **Interactive prompts** - Ask user for each handler
   - Pros: Safe, user control
   - Cons: Annoying for multiple changes

3. **Warning + manual** - Show warnings, require manual fixes
   - Pros: Safe, clear, user confirms understanding
   - Cons: Extra manual step

**Decision**: Option 3 (Warning + manual)

**Rationale**:
- Config changes are critical - users should confirm understanding
- Warnings are clear about what needs changing
- Manual fixes ensure users read migration docs
- Can add --auto-migrate flag in future if requested
- Aligns with "fail safe" philosophy

**Date**: 2026-02-17

### Decision 3: Upgrade guide generation - agent vs manual

**Context**: Should release agent automatically generate upgrade guides?

**Options Considered**:
1. **Manual creation** - Developer writes guide during release
   - Pros: High quality, context-aware
   - Cons: Easily forgotten, inconsistent

2. **Agent generates template** - Release agent creates skeleton, human fills in
   - Pros: Never forgotten, consistent structure
   - Cons: Still requires human effort

3. **Agent generates complete guide** - Full automation from CHANGELOG
   - Pros: Zero human effort
   - Cons: May miss context, quality concerns

**Decision**: Option 2 (Agent generates template)

**Rationale**:
- Ensures upgrade guide is never forgotten
- Template forces structured thinking about migration
- Human review ensures quality and context
- Release agent already has changelog context
- Can be enhanced to full generation later

**Date**: 2026-02-17

## Success Criteria

- [ ] Upgrade guides exist for v2.10→v2.11, v2.11→v2.12, v2.12→v2.13
- [ ] RELEASING.md mandates upgrade guide creation for breaking changes
- [ ] Release agent blocks release if breaking changes lack upgrade guide
- [ ] Upgrade script detects config incompatibilities before starting
- [ ] Upgrade script requires confirmation of reading relevant guides
- [ ] Config migration shows warnings for removed/renamed handlers
- [ ] BREAKING CHANGES section in v2.11.0 and v2.12.0 release notes
- [ ] Test upgrade from v2.10.1 → v2.13.0 shows all warnings
- [ ] Documentation updated (LLM-UPDATE.md, CONTRIBUTING.md)
- [ ] Full QA suite passes

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| CHANGELOG parsing breaks on format changes | High | Medium | Use structured HTML comments, add tests |
| Users skip reading guides with --force flag | Medium | High | Make --force very explicit, log usage |
| Upgrade guide template too rigid | Low | Medium | Make template flexible, document options |
| Retroactive changelog markers are incomplete | Medium | Low | Manual review of all v2.x releases |
| Pre-upgrade validation has false positives | High | Low | Test against all version combinations |

## Timeline

- Phase 1 (Historical docs): 2-3 hours
- Phase 2 (Release process): 1-2 hours
- Phase 3 (Config migration): 2-3 hours
- Phase 4 (Pre-upgrade validation): 1-2 hours
- Phase 5 (Enforce reading): 1-2 hours
- Phase 6 (Release notes format): 1 hour
- Phase 7 (Testing & docs): 2-3 hours

**Total Estimate**: 10-16 hours of focused work

**Target Completion**: 2026-02-18

## Notes & Updates

### 2026-02-17

**Plan Created**: Comprehensive solution to breaking changes lifecycle gap discovered when user upgraded v2.10.1 → v2.13.0 and encountered unknown handler errors without guidance.

**Key Insight**: This is not just a documentation problem - it's a systemic process problem that requires fixes at multiple levels:
1. Release process (mandate documentation)
2. Upgrade guides (fill gaps, create templates)
3. Config migration (smart detection)
4. Pre-flight validation (warn before breaking)
5. Guide enforcement (require reading)

**Success Definition**: Next user who upgrades v2.10.1 → v2.15.0 (in the future) will:
1. See pre-upgrade warnings about incompatible handlers
2. Be shown list of required upgrade guides
3. Be forced to confirm reading guides before proceeding
4. Get clear migration instructions for each handler
5. Have working config after following instructions

This plan ensures we "close the loop" from release → upgrade → migration.
