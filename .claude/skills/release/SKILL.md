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
6. **Submits** to Opus agent for documentation review
7. **Commits** and pushes changes
8. **Tags** release and creates GitHub release
9. **Verifies** release published successfully

**CRITICAL**: Release process ABORTS immediately on ANY validation failure. NO auto-fixing of QA issues or git state.

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
Opus Review ←→ Fix Issues (if needed)
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

## Documentation

Full process details: `CLAUDE/development/RELEASING.md`

## Version

Introduced in: v2.2.0
