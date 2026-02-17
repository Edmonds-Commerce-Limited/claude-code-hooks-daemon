---
name: release
description: Automated release management - version updates, changelog generation, git tagging, and GitHub release creation
argument-hint: "[major|minor|patch|X.Y.Z]"
---

# /release - Automated Release Management Skill

## Description

Automate the complete release process: version updates, changelog generation, Opus review, git tagging, and GitHub release creation.

## Usage

```bash
# Auto-detect version bump from commits
/release

# Specify version explicitly
/release 2.2.0

# Specify bump type
/release patch   # x.y.Z
/release minor   # x.Y.0
/release major   # X.0.0
```

## Parameters

- **version** (optional): Target version (e.g., "2.2.0") or bump type ("major", "minor", "patch")
  - If omitted: Auto-detect from commit history

## What It Does

1. **Validates** environment (ABORT if any failure):
   - Clean git state (no uncommitted changes)
   - All QA checks passing (format, lint, types, tests, security)
   - GitHub CLI authenticated
   - No existing tag for target version
2. **Determines** version bump (auto or manual)
3. **Updates** version across all files
4. **Generates** CHANGELOG.md entry from commits
5. **Creates** release notes (RELEASES/vX.Y.Z.md)
6. **Detects** breaking changes automatically and generates upgrade guide templates
7. **Submits** to Opus agent for documentation review
8. **🚨 UPGRADE GUIDE GATE** - Verify upgrade guide complete if breaking changes (BLOCKING)
9. **🚨 QA VERIFICATION GATE** - Main Claude runs `./scripts/qa/run_all.sh` (BLOCKING)
10. **🚨 ACCEPTANCE TESTING GATE** - Main Claude executes full acceptance test playbook (BLOCKING)
11. **Commits** and pushes changes (only after gates pass)
12. **Tags** release and creates GitHub release
13. **Verifies** release published successfully

**CRITICAL**: Release process ABORTS immediately on ANY validation failure or if blocking gates fail. NO auto-fixing of QA issues or git state.

## Agent

Uses the specialized Release Agent (`.claude/agents/release-agent.md`):
- Model: Sonnet 4.5 (main workflow)
- Review: Opus 4.5 (final validation)
- Tools: Bash, Read, Edit, Write, Grep, Glob, Task

## Process Flow

```
User runs /release
    ↓
Validate Environment
    ↓
Detect/Confirm Version
    ↓
Update Version Files
    ↓
Generate Changelog
    ↓
Create Release Notes
    ↓
Detect Breaking Changes (automatic)
    ↓
Generate Upgrade Guide Template (if breaking changes)
    ↓
Opus Review ←→ Fix Issues (if needed)
    ↓
🚨 UPGRADE GUIDE GATE (BLOCKING)
    Main Claude verifies guide complete if breaking changes
    ABORT if missing or incomplete
    ↓
🚨 QA VERIFICATION GATE (BLOCKING)
    Main Claude runs: ./scripts/qa/run_all.sh
    ABORT if any check fails
    ↓
🚨 ACCEPTANCE TESTING GATE (BLOCKING)
    Main Claude executes full playbook
    ABORT if any test fails
    ↓
Commit & Push
    ↓
Create Tag & GitHub Release
    ↓
Verify & Report
```

## Output

On success:
```
✅ Release v2.2.0 Complete!

📦 Version: 2.2.0 (MINOR release)
🏷️  Tag: v2.2.0
📝 Changelog: CHANGELOG.md
📋 Release Notes: RELEASES/v2.2.0.md
🔗 GitHub Release: https://github.com/.../releases/tag/v2.2.0

Installation command:
git clone -b v2.2.0 https://github.com/.../hooks-daemon.git
```

## Error Handling

Common errors with fixes:

**Dirty Git State:**
```
❌ Uncommitted changes detected
Fix: Commit or stash changes, then retry
```

**QA Failures:**
```
❌ Tests failing: 3 failed, 1165 passed
Fix: Run ./scripts/qa/run_all.sh, fix issues, retry
```

**Opus Rejects (Documentation Issues Only):**
```
⚠️  Opus found documentation issues:
   - Typo in release notes
   - Missing changelog entry

   Fixing documentation and re-submitting...
```
**Note**: Opus ONLY reviews release documentation (changelog/release notes), NOT code or QA issues.

**Upgrade Guide Incomplete (Step 6.5 Gate Failure):**
```
❌ Breaking changes detected but upgrade guide incomplete

Breaking changes found:
- Handler removed: validate_sitemap
- Handler renamed: git_blocker → destructive_git

Upgrade guide: CLAUDE/UPGRADES/v2/v2.11-to-v2.12/v2.11-to-v2.12.md

Issues:
- Missing deprecation reason for validate_sitemap removal
- Missing migration examples for git_blocker rename
- Verification steps need customization

Fix: Complete upgrade guide (remove auto-generated warning), then retry
```

**Tag Exists:**
```
❌ Tag v2.2.0 already exists
Fix: Use different version
```

## Requirements

**ALL requirements are MANDATORY. Release ABORTS if any fail:**

- **Clean git state**: No uncommitted changes, no untracked files in src/
- **All QA passing**: Format, Lint, Type Check, Tests (95% coverage), Security (Bandit)
- **GitHub CLI authenticated**: `gh auth status` must succeed
- **Write access**: Repository push permissions required

**NO auto-fixing**: User must manually resolve all issues before retry.

## Orchestration Details

This skill orchestrates a multi-stage release process through main Claude. The release agent cannot spawn nested agents, so main Claude manages the workflow.

### Stage 1: Release Agent Preparation

Main Claude invokes the Release Agent (`.claude/agents/release-agent.md`) to:
- Validate environment (git state, QA, GitHub CLI)
- Detect/confirm version bump
- Update version files
- Generate CHANGELOG.md entry
- Create release notes
- **Detect breaking changes automatically**
- **Generate upgrade guide templates (if breaking changes)**
- Prepare summary for Opus review

### Stage 2: Opus Documentation Review

Main Claude invokes ad-hoc Opus 4.5 agent to review:
- Version consistency across files
- CHANGELOG.md accuracy and format
- Release notes quality
- Breaking changes flagged correctly
- Upgrade guide existence (if breaking changes)

Opus does NOT review code or QA issues - only documentation.

### Stage 3: Upgrade Guide Verification (Step 6.5 - BLOCKING GATE)

**CRITICAL**: This gate is MANDATORY if breaking changes detected.

Main Claude executes:

1. **Check Breaking Changes Flag**:
   - Review Release Agent output for breaking changes
   - If breaking changes detected, proceed to verification
   - If no breaking changes, skip to Step 7 (QA Gate)

2. **Verify Upgrade Guide Exists**:
   ```bash
   # Determine version jump from Release Agent output
   OLD_VERSION="2.11"  # From last tag
   NEW_VERSION="2.12"  # From target version
   MAJOR="2"

   UPGRADE_DIR="CLAUDE/UPGRADES/v${MAJOR}/v${OLD_VERSION}-to-v${NEW_VERSION}"

   if [ ! -d "$UPGRADE_DIR" ]; then
       echo "❌ ABORT: Breaking changes detected but upgrade guide missing"
       echo "Expected: $UPGRADE_DIR"
       exit 1
   fi
   ```

3. **Verify Guide Completeness**:
   ```bash
   GUIDE_FILE="${UPGRADE_DIR}/v${OLD_VERSION}-to-v${NEW_VERSION}.md"

   # Check for auto-generated warning (indicates incomplete)
   if grep -q "AUTO-GENERATED UPGRADE GUIDE - HUMAN REVIEW REQUIRED" "$GUIDE_FILE"; then
       echo "❌ ABORT: Upgrade guide needs human review"
       echo ""
       echo "Guide location: $GUIDE_FILE"
       echo ""
       echo "Complete these sections:"
       grep -A 5 "HUMAN REVIEW REQUIRED" "$GUIDE_FILE"
       echo ""
       echo "Remove the warning comment after completing review."
       exit 1
   fi
   ```

4. **Verify Required Sections Populated**:
   ```bash
   # Check for placeholder text that needs filling
   if grep -q "NEEDS HUMAN REVIEW" "$GUIDE_FILE"; then
       echo "❌ ABORT: Upgrade guide has incomplete sections"
       echo ""
       grep -n "NEEDS HUMAN REVIEW" "$GUIDE_FILE"
       echo ""
       echo "Complete all sections marked 'NEEDS HUMAN REVIEW'"
       exit 1
   fi
   ```

5. **Verify Supporting Files Exist**:
   ```bash
   if [ ! -f "${UPGRADE_DIR}/config-before.yaml" ]; then
       echo "⚠️  Warning: config-before.yaml missing"
   fi

   if [ ! -f "${UPGRADE_DIR}/config-after.yaml" ]; then
       echo "⚠️  Warning: config-after.yaml missing"
   fi
   ```

**If Step 6.5 FAILS**:
- ABORT release immediately
- Display clear error message with guide location
- List incomplete sections
- User must complete guide manually
- User re-runs `/release` after completion

**If Step 6.5 PASSES**:
- Proceed to Step 7 (QA Verification Gate)

### Stage 4: QA Verification Gate (Step 7 - BLOCKING GATE)

Main Claude runs full QA suite manually - see RELEASING.md Step 7.

### Stage 5: Acceptance Testing Gate (Step 8 - BLOCKING GATE)

Main Claude executes acceptance tests in main thread - see RELEASING.md Step 8.

### Stage 6: Finalization (Steps 9-11)

Main Claude commits, tags, and publishes - see RELEASING.md Steps 9-11.

## Documentation

**📖 SINGLE SOURCE OF TRUTH:** @CLAUDE/development/RELEASING.md

This skill implements the process defined in the release documentation. For complete details on:
- Pre-release validation steps
- Breaking changes detection and upgrade guide generation (Step 6)
- Upgrade guide verification gate (Step 6.5)
- Acceptance testing requirements and FAIL-FAST cycle (Step 8)
- Version detection rules
- Changelog generation format
- Post-release procedures

**See the release documentation above.** The documentation is the authoritative source - this skill follows it.

## Version

Introduced in: v2.2.0
