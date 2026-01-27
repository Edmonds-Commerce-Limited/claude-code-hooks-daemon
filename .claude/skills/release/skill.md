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

1. **Validates** environment (clean git, QA passing, gh authenticated)
2. **Determines** version bump (auto or manual)
3. **Updates** version across all files
4. **Generates** CHANGELOG.md entry from commits
5. **Creates** release notes (RELEASES/vX.Y.Z.md)
6. **Submits** to Opus agent for final review
7. **Commits** and pushes changes
8. **Tags** release and creates GitHub release
9. **Verifies** release published successfully

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

**Opus Rejects:**
```
⚠️  Opus found issues (auto-fixing and resubmitting)
```

**Tag Exists:**
```
❌ Tag v2.2.0 already exists
Fix: Use different version
```

## Requirements

- Clean git state (no uncommitted changes)
- All QA passing (tests, lint, types, coverage)
- GitHub CLI authenticated (`gh auth status`)
- Write access to repository

## Documentation

Full process details: `CLAUDE/development/RELEASING.md`

## Version

Introduced in: v2.2.0
