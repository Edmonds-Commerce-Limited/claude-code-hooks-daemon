---
name: release
description: Automated release management - version updates, changelog generation, git tagging, and GitHub release creation
argument-hint: "[major|minor|patch|X.Y.Z]"
---

# /release - Automated Release Management Skill

## 🚨 HUMAN-GATED — this skill is the ONLY valid entry point

**A release may only begin when a human invokes `/release` in the CURRENT
session. An agent must never start, resume, or complete a release on its own
initiative — and tagging/publishing needs explicit confirmation even inside an
authorised run.**

A release is a decision about **scope**, and scope is not visible from inside
the repository: only the human knows which work belongs in the bundle. A clean
tree, a fully green QA run and a bumped version say a release *would be sound*, never that
it is *wanted now*.

**A release may legitimately span a compaction, and must then be FINISHED** — a
half-done release (version bumped, `UNRELEASED/` dirs moved, nothing tagged) is
its own broken state. So this skill MUST write `untracked/release-state.json` as
its first action and update it per step, because authorisation and progress have
to live where a compaction cannot reach them.

- **No state file ⇒ no release in progress.** A dirty tree or a plan saying
  "finish the release" is not a substitute — ask.
- **State file present ⇒ resume** from `last_completed_step`.
- **`publish_authorised` gates Steps 14–15 only**, set solely by an explicit
  human "yes, publish" — never by the gates passing.

Do not tag or publish because a cron tick fired, because a plan says "finish the
release", or because the tree looks ready. Stop and ask.

See **[RELEASING.md](../../../CLAUDE/development/RELEASING.md)** — "A RELEASE IS
HUMAN-GATED" — for the full rule, the state-file schema, and how to recover from
an unauthorised release (never silently unpublish).

## Description

Automate the complete release process: version updates, changelog generation, Opus review, git tagging, and GitHub release creation.

## Usage

```claude-code
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

01. **Validates** environment (ABORT if any failure):
    - Clean git state (no uncommitted changes)
    - All QA checks passing (format, lint, types, tests, security)
    - GitHub CLI authenticated
    - No existing tag for target version
02. **Determines** version bump (auto or manual)
03. **Updates** version across all files
04. **Generates** CHANGELOG.md entry from commits
05. **Creates** release notes (RELEASES/vX.Y.Z.md)
06. **Moves** `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md` into the versioned upgrade guide — BLOCKING, no task files may remain in `UNRELEASED/` after this step
07. **Detects** breaking changes automatically and generates upgrade guide templates
08. **Submits** to Opus agent for documentation review
09. **🚨 UPGRADE GUIDE GATE** - Verify upgrade guide complete if breaking changes (BLOCKING)
10. **🚨 QA VERIFICATION GATE** - Main Claude runs `./scripts/qa/llm_qa.py all` (BLOCKING)
11. **🚨 CODE REVIEW GATE** - Main Claude reviews code diff since last tag (BLOCKING)
12. **🚨 ACCEPTANCE TESTING GATE** - Main Claude executes acceptance tests: full suite for MAJOR/MINOR, targeted or skipped for PATCH (BLOCKING)
13. **Commits** and pushes changes (only after gates pass)
14. **Tags** release and creates GitHub release
15. **Verifies** release published successfully

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
🚨 MOVE UNRELEASED POST-UPGRADE TASKS (BLOCKING)
    Move CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md
    into the versioned upgrade guide
    ABORT if any task file remains in UNRELEASED/
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
    Main Claude runs: ./scripts/qa/llm_qa.py all
    ABORT if any check fails
    ↓
🚨 CODE REVIEW GATE (BLOCKING)
    Main Claude reviews git diff since last tag
    ABORT if bugs/security issues found
    ↓
🚨 ACCEPTANCE TESTING GATE (BLOCKING)
    MAJOR/MINOR: full test suite
    PATCH + handler changes: targeted tests only
    PATCH + no handler changes: skip (document reason)
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
Fix: Run ./scripts/qa/llm_qa.py all, fix issues, retry
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

### Stage 4.5: Code Review Gate (Step 7.5 - BLOCKING GATE)

Main Claude reviews `git diff <last-tag>..HEAD -- src/` for bugs, security issues, and quality problems - see RELEASING.md Step 7.5.

### Stage 5: Acceptance Testing Gate (Step 8 - BLOCKING GATE)

Main Claude executes acceptance tests - scope depends on bump type:

- MAJOR/MINOR: full test suite - see RELEASING.md Step 8
- PATCH + handler changes: targeted tests for changed handlers only
- PATCH + no handler changes: skip, document reason in release notes

### Stage 6: Finalization (Steps 9-11)

Main Claude commits, tags, and publishes - see RELEASING.md Steps 9-11.

## Documentation

**📖 SINGLE SOURCE OF TRUTH:** [CLAUDE/development/RELEASING.md](../../../CLAUDE/development/RELEASING.md)

This skill implements the process defined in the release documentation. For complete details on:

- Pre-release validation steps
- UNRELEASED post-upgrade-tasks move (Step 6)
- Breaking changes detection and upgrade guide generation
- Upgrade guide verification gate
- Acceptance testing requirements and FAIL-FAST cycle (Step 8)
- Version detection rules
- Changelog generation format
- Post-release procedures

**See the release documentation above.** The documentation is the authoritative source - this skill follows it.

## Version

Introduced in: v2.2.0
