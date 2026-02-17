# Release Process - Publishing New Versions

## Overview

This document describes how to publish a new release of the Claude Code Hooks Daemon using the automated `/release` skill.

**Target Audience:** Repository maintainers publishing new versions

**Prerequisites:**
- Write access to GitHub repository
- gh CLI authenticated (`gh auth status`)
- Clean git state (all changes committed)
- All QA checks passing

## Quick Release

```bash
# Let agent auto-detect version bump
/release

# Or specify version explicitly
/release 2.2.0

# Or specify bump type
/release patch
/release minor
/release major
```

## Process Details

The `/release` skill orchestrates the complete release workflow through a multi-stage process:

**Orchestration Architecture:**
- **Stage 1**: Release Agent (Sonnet) prepares files
- **Stage 2**: Opus Agent reviews for accuracy
- **Stage 3**: Main Claude runs QA verification (BLOCKING GATE)
- **Stage 4**: Main Claude checks breaking changes (BLOCKING GATE)
- **Stage 5**: Main Claude runs acceptance tests (BLOCKING GATE)
- **Stage 6**: Main Claude commits, tags, and publishes

**Important:** Agents cannot spawn nested agents. Main Claude orchestrates by invoking agents sequentially.

## 🚨 CRITICAL: BLOCKING GATES

**The following steps are MANDATORY and BLOCKING. Release CANNOT proceed if these fail:**

1. **QA Verification Gate** (Step 7: after Opus review, before commit)
2. **Breaking Changes Check** (Step 6.5: after QA passes, before acceptance tests)
3. **Acceptance Testing Gate** (Step 8: after breaking changes check, before commit)

**If ANY gate fails, the release is ABORTED. No exceptions.**

### 1. Pre-Release Validation (Automated)

**CRITICAL: ALL checks must pass. ANY failure = IMMEDIATE ABORT. NO auto-fixing.**

The release agent will:
- ✅ Verify clean git state (no uncommitted changes, no untracked files in src/)
- ✅ Run ALL QA checks: Format (Black), Lint (Ruff), Type Check (MyPy), Tests (Pytest with 95% coverage), Security (Bandit)
- ✅ Check version consistency across files (pyproject.toml, version.py, README.md, CLAUDE.md)
- ✅ Confirm no existing tag for target version
- ✅ Validate GitHub CLI authentication (`gh auth status`)

**If any check fails:**
- Process ABORTS immediately
- Clear error message displayed
- User must manually fix issues
- User re-runs `/release` after fixing

**NO attempts to:**
- Auto-fix QA issues (formatting, linting, tests, security)
- Auto-commit or stash uncommitted changes
- Skip or bypass validation checks
- Continue despite failures

### 2. Version Detection (Auto or Manual)

**Automatic Detection:**
Analyzes commits since last tag using semantic versioning rules:

- **PATCH (x.y.Z)** - Bug fixes, docs, refactoring
  - Keywords: "fix:", "bug:", "Fix ", "docs:", "refactor:"
  - Example: "Fix daemon startup race condition"

- **MINOR (x.Y.0)** - New features, backwards-compatible
  - Keywords: "feat:", "Add ", "Implement ", "feature:"
  - Example: "Add TDD enforcement handler"

- **MAJOR (X.0.0)** - Breaking changes, incompatible API
  - Keywords: "BREAKING", "breaking change", "incompatible"
  - Example: "BREAKING: Change handler API signature"

**Manual Override:**
If you specify a version explicitly, auto-detection is skipped.

**Agent Proposal:**
The agent will propose a version bump with justification:
```
Proposed version bump: MINOR (2.1.0 → 2.2.0)

Reasoning:
- 4 new features added (3 handlers, 1 config option)
- 2 bug fixes (non-critical)
- No breaking changes detected

Accept proposal? (yes/no/specify version)
```

### 3. Version Update (Automated)

Updates version string in:
1. `pyproject.toml` (line 7)
2. `src/claude_code_hooks_daemon/version.py`
3. `README.md` (badge on line 3)
4. `CLAUDE.md` ("Current Version" section)
5. Any version-specific upgrade docs

All updates use exact string replacement - no manual editing required.

### 4. Changelog Generation (Automated)

Generates `CHANGELOG.md` entry following [Keep a Changelog](https://keepachangelog.com/) format:

**Format:**
```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features, handlers, capabilities

### Changed
- Modifications to existing functionality
- **BREAKING**: Breaking changes (if any)

### Fixed
- Bug fixes
- **SECURITY**: Security patches (if any)

### Removed
- Deprecated features removed
```

**Categorization:**
- Parses commit messages since last tag
- Groups by conventional commit prefixes
- Filters out test/internal commits
- Highlights security and breaking changes

**Example Output:**
```markdown
## [2.2.0] - 2025-01-27

### Added
- TDD enforcement handler for pytest workflow
- Container environment detection (YOLO mode)
- Upgrade documentation system

### Changed
- Improved installer with backup and recovery
- Updated LLM-INSTALL.md for clarity

### Fixed
- Fix daemon startup race condition (#23)
- Fix hook response JSON schema validation (#24)

### Security
- **SECURITY**: Fix command injection in sed blocker (#25)
```

### 5. Release Notes Creation (Automated)

Creates comprehensive release notes in `RELEASES/vX.Y.Z.md`:

**Structure:**
- Release summary and highlights
- Full changelog (from CHANGELOG.md)
- Upgrade instructions (if breaking changes)
- Installation commands for new users
- Upgrade commands for existing users
- Test statistics and coverage
- Contributor list
- GitHub comparison link

**Example:** See `RELEASES/v2.1.0.md` (if exists) for reference format.

### 6. Opus Review (Orchestrated by Main Claude)

**Critical Quality Gate: DOCUMENTATION REVIEW ONLY**

After the Release Agent completes, **main Claude** (not the agent) invokes an ad-hoc Opus 4.5 agent to review **release documentation ONLY**.

**Note:** Agents cannot spawn nested agents. The /release skill orchestrates this multi-stage process through main Claude.

**Review Scope (Documentation Only):**
- ✅ All version numbers consistent across files
- ✅ Changelog entries accurate and categorized correctly (Added/Changed/Fixed/Removed)
- ✅ Release notes comprehensive and grammatically correct
- ✅ Technical descriptions accurate
- ✅ No missing critical changes in changelog
- ✅ Security/breaking changes properly marked
- ✅ Upgrade instructions clear (if needed)

**What Opus Does NOT Review:**
- ❌ Code quality (already validated by QA checks)
- ❌ Test failures (already validated by pytest)
- ❌ Type errors (already validated by mypy)
- ❌ Lint violations (already validated by ruff)
- ❌ Security issues (already validated by bandit)
- ❌ Git state (already validated pre-release)

**Outcome:**
- **Approved**: Main Claude proceeds to **QA Verification Gate** (Step 7)
- **Issues Found**: Main Claude re-invokes Release Agent to fix **documentation issues only** (typos, missing entries, etc.)
- Process repeats until Opus approves documentation with 100% confidence

You'll see output like:
```
📋 Release Agent Complete - Files prepared for review
⏳ Invoking Opus agent for documentation validation...
✅ Opus Review: APPROVED (100% confidence)
   "All version numbers consistent, changelog accurate,
    release notes comprehensive. Ready for release."
```

Or if documentation issues found:
```
⚠️  Opus Review: REJECTED
   Documentation issues:
   - Typo in release notes: "performace" → "performance"
   - Changelog missing entry for handler addition

   Re-invoking Release Agent to fix documentation...
```

### 7. QA Verification Gate (Main Claude Executes) - 🚨 BLOCKING

**CRITICAL BLOCKING GATE: Main Claude must manually verify QA passes.**

After Opus approves documentation, **main Claude MUST run full QA suite manually**:

```bash
# MANDATORY: Run complete QA suite
./scripts/qa/run_all.sh
```

**Expected Output:**
```
========================================
QA Summary
========================================
  Magic Values        : ✅ PASSED
  Format Check        : ✅ PASSED
  Linter              : ✅ PASSED
  Type Check          : ✅ PASSED
  Tests               : ✅ PASSED
  Security Check      : ✅ PASSED

Overall Status: ✅ ALL CHECKS PASSED
```

**If ANY check fails:**
- ❌ **ABORT RELEASE IMMEDIATELY**
- Display failure details to user
- User must fix issues manually
- User re-runs `/release` from beginning

**Why This Gate Exists:**
- Agent's pre-release QA check (Step 1) may be stale by the time files are prepared
- Documentation changes could introduce issues
- This is the final verification before irreversible git operations

**Main Claude proceeds to Breaking Changes Check (Step 6.5) ONLY if all QA checks pass.**

### 6.5. Breaking Changes Check (Main Claude Executes) - 🚨 BLOCKING

**CRITICAL BLOCKING GATE: Main Claude must verify upgrade guides exist for breaking changes.**

After QA passes, **main Claude MUST check for breaking changes and verify upgrade documentation exists**.

**Why This Gate Exists:**
- v2.11 and v2.12 shipped with breaking changes but no upgrade documentation
- Users had no migration path when handlers were removed or renamed
- This gate prevents releasing breaking changes without upgrade guides

**STEP 6.5.1: Scan CHANGELOG.md for Breaking Change Indicators**

Breaking changes are detected by scanning the changelog entry for this release:

```bash
# View the changelog entry for this release
# (Located at top of CHANGELOG.md after Step 4: Changelog Generation)
```

**Breaking Change Indicators:**
1. **"Removed" section** with any entries
   - Handler removals
   - Deprecated feature removals
   - API removals

2. **"Changed" section** with "BREAKING" keyword
   - Handler renames
   - Config format changes
   - API signature changes

3. **Keywords anywhere in changelog:**
   - "BREAKING"
   - "breaking change"
   - "incompatible"
   - "renamed" (for handlers/config)

**Examples from v2.11 and v2.12:**

v2.11 (CHANGELOG.md lines 200-204):
```markdown
### Removed
- **Project-Specific Hangover Handlers**: Cleaned up two handlers...
  - Removed `validate_sitemap` handler (PostToolUse)
  - Removed `remind_validator` handler (SubagentStop)
```

v2.12 (CHANGELOG.md lines 72-79):
```markdown
### Added
- **LintOnEditHandler with Strategy Pattern**: New PostToolUse:Edit handler...
  (Note: This actually RENAMED validate_eslint_on_write → lint_on_edit,
   which is a breaking change but wasn't marked clearly)
```

**STEP 6.5.2: Check for Upgrade Guide (If Breaking Changes Found)**

If ANY breaking change indicators detected, verify upgrade guide exists:

```bash
# Determine version from release
VERSION="X.Y.Z"  # e.g., "2.12.0"

# Extract major version
MAJOR_VERSION="${VERSION%%.*}"  # e.g., "2"

# Calculate previous version (assumes patch/minor bump)
# For v2.12.0, previous is v2.11.0
PREV_VERSION="X.Y.0"  # Determine from git tags

# Check for upgrade guide
UPGRADE_PATH="CLAUDE/UPGRADES/v${MAJOR_VERSION}/v${PREV_VERSION}-to-v${VERSION}"

if [ ! -d "$UPGRADE_PATH" ]; then
  echo "❌ BREAKING CHANGES DETECTED - NO UPGRADE GUIDE"
  exit 1
fi

# Verify required files exist
ls -la "$UPGRADE_PATH/"
# Expected files:
# - README.md (or vX.Y-to-vX.Z.md)
# - config-before.yaml (if config changes)
# - config-after.yaml (if config changes)
# - migration-script.sh (optional)
# - verification.sh (optional)
```

**Expected Upgrade Guide Structure:**

Based on template at `CLAUDE/UPGRADES/upgrade-template/`:

```
CLAUDE/UPGRADES/v2/v2.11-to-v2.12/
├── README.md (or v2.11-to-v2.12.md)  # Main upgrade guide
├── config-before.yaml                # Config before upgrade (if applicable)
├── config-after.yaml                 # Config after upgrade (if applicable)
├── migration-script.sh               # Automated migration (optional)
└── verification.sh                   # Post-upgrade verification (optional)
```

**Upgrade Guide MUST Include:**

From template at `CLAUDE/UPGRADES/upgrade-template/README.md`:

1. **Summary** - One paragraph describing changes
2. **Version Compatibility** - Source/target versions, breaking changes flag
3. **Pre-Upgrade Checklist** - Backup steps, verification commands
4. **Changes Overview** - Detailed breakdown:
   - New/modified/removed handlers
   - Configuration changes
   - Migration steps
5. **Step-by-Step Upgrade Instructions** - Complete upgrade workflow
6. **Verification Steps** - How to verify upgrade succeeded
7. **Rollback Instructions** - How to revert if issues found

**STEP 6.5.3: Verify Upgrade Guide Links in Release Notes**

If breaking changes exist, release notes MUST reference upgrade guide:

```bash
# Check RELEASES/vX.Y.Z.md for upgrade guide link
grep -i "upgrade guide" RELEASES/vX.Y.Z.md
grep -i "breaking" RELEASES/vX.Y.Z.md

# Expected format in release notes:
# ⚠️ BREAKING CHANGES
#
# This release contains breaking changes. See the upgrade guide for migration instructions:
# [Upgrade Guide: vX.Y → vX.Z](../../CLAUDE/UPGRADES/v2/vX.Y-to-vX.Z/)
```

**If upgrade guide link missing**, add BREAKING CHANGES section to release notes:

```markdown
## ⚠️ BREAKING CHANGES

This release contains breaking changes. **Read the upgrade guide before upgrading.**

**Breaking Changes:**
- [List breaking changes from changelog]

**Upgrade Guide:** [vX.Y → vX.Z](../../CLAUDE/UPGRADES/v2/vX.Y-to-vX.Z/)

**Migration Steps:**
1. Read upgrade guide completely
2. Backup your configuration
3. Follow upgrade instructions
4. Run verification script
```

**STEP 6.5.4: Decision Matrix**

| Breaking Changes Detected? | Upgrade Guide Exists? | Action |
|---------------------------|----------------------|--------|
| ✅ Yes | ✅ Yes | Proceed to Step 8 (Acceptance Testing) |
| ✅ Yes | ❌ No | **ABORT RELEASE** - Create upgrade guide first |
| ❌ No | N/A | Proceed to Step 8 (Acceptance Testing) |

**✅ SUCCESS CRITERIA (Breaking Changes Present):**
- Upgrade guide directory exists at correct path
- Upgrade guide contains all required sections
- Release notes reference upgrade guide with clear warning
- Migration steps documented for all breaking changes

**✅ SUCCESS CRITERIA (No Breaking Changes):**
- No "Removed" section in changelog
- No "BREAKING" keywords in changelog
- No handler renames or config format changes

**❌ FAILURE CRITERIA (Any of these = ABORT):**
- Breaking changes detected but no upgrade guide
- Upgrade guide exists but missing required sections
- Release notes don't reference upgrade guide
- Migration steps unclear or incomplete

**If Check Fails:**

```
❌ BREAKING CHANGES CHECK FAILED

Breaking changes detected in changelog:
- Removed: validate_sitemap handler
- Removed: remind_validator handler

Expected upgrade guide location:
  CLAUDE/UPGRADES/v2/v2.10-to-v2.11/

Upgrade guide does NOT exist.

ACTION REQUIRED:
1. Create upgrade guide using template:
   cp -r CLAUDE/UPGRADES/upgrade-template/ CLAUDE/UPGRADES/v2/v2.10-to-v2.11/
2. Fill in upgrade guide following template instructions
3. Document migration steps for all breaking changes
4. Add BREAKING CHANGES section to release notes
5. Re-run /release from beginning

DO NOT PROCEED WITH RELEASE.
```

**Creating Upgrade Guide:**

```bash
# Use template
PREV_VERSION="2.11"
NEW_VERSION="2.12"
MAJOR_VERSION="2"

UPGRADE_DIR="CLAUDE/UPGRADES/v${MAJOR_VERSION}/v${PREV_VERSION}-to-v${NEW_VERSION}"

# Copy template
cp -r CLAUDE/UPGRADES/upgrade-template/ "$UPGRADE_DIR/"

# Edit files
# 1. Update README.md with actual changes from CHANGELOG.md
# 2. Create config-before.yaml (current config snapshot)
# 3. Create config-after.yaml (new config format)
# 4. Write migration-script.sh (optional automated migration)
# 5. Write verification.sh (optional post-upgrade checks)

# Commit upgrade guide
git add "$UPGRADE_DIR/"
git commit -m "Add upgrade guide: v${PREV_VERSION} → v${NEW_VERSION}"
```

**VERIFICATION CHECKPOINT:**

Before proceeding to Step 8, confirm:
1. [ ] Scanned CHANGELOG.md for breaking change indicators
2. [ ] If breaking changes found: Upgrade guide exists at correct path
3. [ ] If breaking changes found: Upgrade guide contains all required sections
4. [ ] If breaking changes found: Release notes reference upgrade guide
5. [ ] If breaking changes found: Migration steps documented
6. [ ] If no breaking changes: Confirmed no indicators in changelog

**If you cannot check ALL applicable boxes above, you MUST NOT proceed.**

**Main Claude proceeds to Acceptance Testing Gate (Step 8) ONLY if breaking changes check passes.**

### 8. Acceptance Testing Gate (Main Claude Executes) - 🚨 BLOCKING

**CRITICAL BLOCKING GATE: Main Claude must execute acceptance tests in the MAIN THREAD.**

After QA passes, **main Claude MUST run acceptance tests via real Claude Code tool calls**.

**🚫 SUB-AGENT TESTING IS FORBIDDEN**

Sub-agent acceptance testing strategies (parallel Haiku batches) are **permanently retired** as of v2.10.0:
- Sub-agents run out of context on large test suites
- Sub-agents cannot use Write/Edit tools (PreToolUse:Write tests always fail)
- Lifecycle events only fire in the main session
- Advisory system-reminder messages are only visible to the main session
- The v2.9.0 incident proved async agents create race conditions with release gates

**The ONLY valid acceptance test is a real tool call in the main thread.**

**STEP 8.1: Restart Daemon & Verify Load**

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: RUNNING
```

**This verifies:** All handlers load successfully (including SessionEnd, PreCompact, Stop, SubagentStop, Status, Notification, PermissionRequest handlers that cannot be triggered on demand).

**STEP 8.2: Verify OBSERVABLE Handlers**

Check that lifecycle handlers are active by looking at **existing system-reminders** in your current session:

- [ ] **SessionStart**: Look for "SessionStart hook system active" in system-reminders
- [ ] **UserPromptSubmit**: Look for "UserPromptSubmit hook system active" in system-reminders
- [ ] **PostToolUse**: Look for "PostToolUse hook system active" in system-reminders (appears after every tool call)

**Time: 30 seconds** - just verify these messages are visible in your context.

**STEP 8.3: Generate Playbook for EXECUTABLE Tests**

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md
```

**STEP 8.4: Execute EXECUTABLE Tests Sequentially in Main Thread**

**Execute BLOCKING and ADVISORY tests only** (~89 tests total):

- **BLOCKING tests** (~65 tests): PreToolUse handlers that deny dangerous commands
  - Use Bash/Write/Edit tool with the test command
  - Verify the hook blocks it (error output contains expected patterns)

- **ADVISORY tests** (~24 tests): PreToolUse/PostToolUse handlers that provide context
  - Use Bash/Write/Edit tool with the test command
  - Verify system-reminder shows advisory context

**Skip CONTEXT tests** for untriggerable lifecycle events (SessionEnd, PreCompact, Stop, SubagentStop, Status, Notification, PermissionRequest). These handlers are verified by:
- Daemon loading successfully (Step 8.1)
- Unit tests passing (QA suite in Step 7)
- Cannot be triggered on demand for manual testing

Mark PASS/FAIL for each executable test. Document any unexpected behaviour.

**Test execution is sequential, one at a time, in order. No parallel execution.**

**STEP 8.5: Evaluate Results**

**✅ SUCCESS CRITERIA**:
- All EXECUTABLE blocking handlers correctly deny dangerous commands (~65 tests)
- All EXECUTABLE advisory handlers show context in system-reminders (~24 tests)
- OBSERVABLE lifecycle handlers visible in system-reminders (SessionStart, UserPromptSubmit, PostToolUse)
- VERIFIED_BY_LOAD handlers loaded successfully (daemon restart succeeded)
- Failed count = 0

**❌ FAILURE CRITERIA** (any of these = ABORT):
- Any blocking handler fails to block
- Any advisory handler fails to show context
- Any observable handler not visible in system-reminders
- Daemon crashes during testing
- Any unexpected behaviour

**FAIL-FAST Cycle (if ANY test fails):**
1. **STOP testing immediately**
2. Investigate root cause
3. Fix bug using TDD (write failing test, implement fix, verify)
4. Run FULL QA: `./scripts/qa/run_all.sh` (must pass 100%)
5. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
6. **RESTART acceptance testing FROM STEP 8.1** (restart daemon verification)
7. Continue until ALL tests pass with ZERO code changes

**NO SHORTCUTS ALLOWED:**
- ⛔ Cannot skip acceptance testing
- ⛔ Cannot delegate to sub-agents (MUST be main thread)
- ⛔ Cannot ignore failures
- ⛔ Cannot proceed with errors
- ⛔ Must use real tool calls (not socket injection or mocks)

**VERIFICATION CHECKPOINT:**

Before proceeding to Step 9, confirm:
1. [ ] Daemon is running (Step 8.1)
2. [ ] OBSERVABLE handlers confirmed (SessionStart, UserPromptSubmit, PostToolUse visible in system-reminders)
3. [ ] EXECUTABLE blocking tests executed and passed (~65 tests)
4. [ ] EXECUTABLE advisory tests executed and passed (~24 tests)
5. [ ] VERIFIED_BY_LOAD handlers loaded (daemon started successfully + unit tests passed)
6. [ ] Failed = 0
7. [ ] Total executable tests: ~89 (blocking + advisory)
8. [ ] No handler bugs found

**If you cannot check ALL boxes above, you MUST NOT proceed.**

**Why This Gate Exists:**
- Unit tests don't catch integration issues with real Claude Code hook events
- Handlers might pass unit tests but fail in actual usage
- Real-world testing is the final safety check before release
- **CORRECTNESS over SPEED** - A delayed release is better than a broken release
- Only main-thread tool calls test the FULL hook pipeline (bash script -> socket -> daemon -> handler -> response)

**Test Categories Explained:**
- **EXECUTABLE**: PreToolUse blocking/advisory handlers - must be tested by running commands
- **OBSERVABLE**: Lifecycle handlers visible in system-reminders during normal session usage
- **VERIFIED_BY_LOAD**: Lifecycle handlers that cannot be triggered on demand (SessionEnd, PreCompact, Stop, etc.) - verified by daemon loading successfully + unit tests passing

**Time Investment:**
- **Daemon restart**: 30 seconds
- **Observable checks**: 30 seconds (just look at system-reminders)
- **Executable tests**: 20-30 minutes (~89 tests)
- **Total**: 20-30 minutes (not including issue investigation)
- **Issue investigation**: Variable (hours if bugs found)

**Main Claude proceeds to Commit & Push (Step 9) ONLY if acceptance tests pass.**

### 9. Commit & Push (Main Claude Executes)

Once QA and acceptance tests pass, **main Claude** (not the Release Agent) commits and pushes:

```bash
# Commits all version files, changelog, release notes
git add pyproject.toml version.py README.md CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md
git commit -m "Release vX.Y.Z: [Title]"
git push origin main
```

**Commit Message Format:**
```
Release vX.Y.Z: [Release Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### 10. Tag & GitHub Release (Main Claude Executes)

**Main Claude** creates annotated git tag and GitHub release:

```bash
# Annotated tag with full release notes
git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

# GitHub release via gh CLI
gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest
```

**GitHub Release Features:**
- ✅ Full release notes attached
- ✅ Marked as "Latest Release"
- ✅ Auto-generated tarball/zip
- ✅ Comparison link to previous version

### 11. Post-Release Verification (Main Claude Executes)

**Main Claude** verifies:
- ✅ Tag exists locally and on GitHub
- ✅ GitHub release is published
- ✅ Release marked as "Latest"
- ✅ README badge renders correctly (GitHub caches clear)
- ✅ Installation from tag works

**Output:**
```
✅ Release v2.2.0 Complete!

📦 Version: 2.2.0 (MINOR release)
🏷️  Tag: v2.2.0
📝 Changelog: CHANGELOG.md (lines 8-24)
📋 Release Notes: RELEASES/v2.2.0.md
🔗 GitHub Release: https://github.com/.../releases/tag/v2.2.0

Installation command for users:
git clone -b v2.2.0 https://github.com/.../claude-code-hooks-daemon.git

Next steps:
1. Review release at GitHub
2. Update external documentation (if applicable)
3. Announce release (if applicable)
```

## Error Handling & Rollback

### Common Errors

**1. Dirty Git State**
```
❌ Error: Uncommitted changes detected
   Run: git status

   Commit all changes before releasing.
```
**Fix:** Commit or stash changes, then retry.

**2. QA Failures**
```
❌ Error: QA checks failed
   Failed: Tests (3 failing), Lint (12 violations)

   Fix issues and retry.
```
**Fix:** Run `./scripts/qa/run_all.sh`, fix issues, commit, retry.

**3. Tag Already Exists**
```
❌ Error: Tag v2.2.0 already exists
   This version has already been released.

   Choose a different version or delete the tag.
```
**Fix:** Use different version or `git tag -d v2.2.0; git push origin :refs/tags/v2.2.0`

**4. Opus Rejects Release (Documentation Issues)**
```
⚠️  Opus Review: REJECTED
   Documentation issues found:
   - Changelog entry missing security fix #25
   - Version number inconsistent in CLAUDE.md
   - Typo in release notes: "performace" → "performance"

   Fixing documentation and re-submitting...
```
**Fix:** Agent fixes **documentation issues only** and re-submits. Opus does NOT review code or QA issues.

**Note**: If Opus repeatedly rejects, manually review changelog and release notes for accuracy.

### Rollback Strategy

**Before Commit:**
```bash
# Simple restore
git restore .
```

**After Commit (Not Pushed):**
```bash
# Reset last commit (keeps changes)
git reset HEAD~1
```

**After Push (Use with Caution):**
```bash
# Create immediate patch release to fix issues
# NEVER force-push tags - creates downstream problems
```

**If Tag Created:**
```bash
# Delete local tag
git tag -d vX.Y.Z

# Delete remote tag
git push origin :refs/tags/vX.Y.Z

# Delete GitHub release
gh release delete vX.Y.Z --yes
```

## Manual Release (Bypass Skill)

If you need to release manually without the skill:

```bash
# 1. Update versions
# Edit: pyproject.toml, version.py, README.md, CLAUDE.md

# 2. Update CHANGELOG.md
# Add entry following Keep a Changelog format

# 3. Create release notes
# Create RELEASES/vX.Y.Z.md

# 4. Run QA
./scripts/qa/run_all.sh

# 5. Commit
git add .
git commit -m "Release vX.Y.Z: [Title]"
git push

# 6. Tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z

# 7. GitHub release
gh release create vX.Y.Z \
  --title "vX.Y.Z - [Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest
```

## Best Practices

### When to Release

**PATCH (x.y.Z):**
- Urgent bug fixes
- Security patches
- Documentation updates
- No new features

**MINOR (x.Y.0):**
- New handlers
- New features
- Configuration options
- Backwards-compatible changes

**MAJOR (X.0.0):**
- Breaking API changes
- Incompatible configuration changes
- Minimum Python version bumps
- Removed deprecated features

### Release Cadence

No fixed schedule - release when ready:
- **Critical bugs/security**: Immediate patch release
- **Features ready**: Minor release when stable
- **Breaking changes**: Plan ahead, communicate in advance

### Pre-Release Checklist

Before running `/release`:
- [ ] All features tested manually
- [ ] **Acceptance tests completed** (see Acceptance Testing section below)
- [ ] All tests passing locally
- [ ] No known critical bugs
- [ ] Breaking changes documented
- [ ] Upgrade path tested (if breaking changes)
- [ ] External docs updated (if applicable)

### Acceptance Testing (CRITICAL - CORRECTNESS OVER SPEED)

**MANDATORY before every release:** Execute the full acceptance testing playbook to validate real-world handler behavior.

**Location:** Generate fresh from code: `generate-playbook > /tmp/playbook.md`
**Instructions:** `CLAUDE/AcceptanceTests/GENERATING.md`

**Purpose:** Catch integration issues that unit tests miss by testing handlers in actual Claude Code sessions with real hook events.

**Process:**

1. **Generate Fresh Playbook** - Generate ephemeral playbook from code:
   ```bash
   python -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md
   ```
   Review to identify:
   - Tests for new handlers added since last release
   - Tests that need updating for handler changes
   - Missing coverage for new features
   - Outdated test expectations

2. **Update Playbook** - Before executing tests:
   - Add tests for any new handlers (use same format as existing tests)
   - Update test expectations for modified handlers
   - Remove tests for deprecated handlers
   - Update safe command patterns if needed
   - Ensure all 15+ critical handlers are covered

3. **Execute Tests Carefully** - Work through each test:
   - Execute EVERY test in the playbook (do not skip)
   - Mark PASS/FAIL based on actual observed behavior
   - Document unexpected behavior in notes
   - If ANY test fails, STOP and investigate
   - Take time to verify advisory handlers provide helpful context

4. **Document Results** - Fill in Results Summary:
   - Total PASS/FAIL/SKIP counts
   - Test date and daemon version
   - Issues found section with details
   - Handlers working correctly section

5. **Fix Issues Before Release** (FAIL-FAST Cycle):
   - ANY failing test = DO NOT RELEASE
   - Investigate root cause of failures
   - Fix handler bugs using TDD (write failing test, implement fix, verify test passes)
   - **CRITICAL: If ANY code changes made:**
     1. Run FULL QA suite: `./scripts/qa/run_all.sh` (must pass 100%)
     2. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
     3. **Restart acceptance testing FROM TEST 1.1** (not from where you left off)
     4. Continue until ALL tests pass with ZERO code changes
   - **Why restart from beginning?** Code changes can introduce regressions in previously passing handlers
   - Update playbook if test expectations were wrong (documentation fixes don't require restart)

6. **Update Playbook for Next Release**:
   - Commit playbook changes alongside other release files
   - Include playbook updates in release notes if significant

**Time Investment:**
- Initial playbook review: 10-15 minutes
- Test execution: 20-30 minutes for all 15 tests
- Issue investigation: Variable (could be hours if bugs found)
- Total: Plan 45-60 minutes minimum

**Remember:** Releases prioritize CORRECTNESS over SPEED. A delayed release is better than a broken release.

**Red Flags That Require Investigation:**
- Blocking handlers allowing dangerous commands through
- Advisory handlers not providing expected context
- Handlers triggering on wrong patterns (false positives)
- Handlers not triggering on correct patterns (false negatives)
- Unclear or confusing error messages from handlers

**Example Acceptance Test Failure Workflow:**
```
Test 1.1 FAILED: echo "git reset --hard HEAD" was NOT blocked

Investigation:
1. Check handler is enabled in config
2. Restart daemon to load latest code
3. Test again - still fails
4. Check handler matches() logic - found bug in regex pattern
5. Fix handler, add regression test
6. Re-run acceptance test - now passes
7. Update changelog with bug fix
8. Continue with release process
```

### Post-Release

After successful release:
- [ ] Test installation from new tag
- [ ] Verify GitHub release page
- [ ] Update external references (if any)
- [ ] Monitor for issues (GitHub issues, user reports)
- [ ] Respond to installation questions

## Troubleshooting

### Skill Not Found

```bash
# Verify skill exists
ls -la .claude/skills/release/

# If missing, skill may need to be registered
# Check .claude/settings.json for skill configuration
```

### Agent Hangs

If agent appears stuck:
- Check if waiting for Opus review (can take 1-2 minutes)
- Check for prompts requiring user input
- Cancel with Ctrl+C if truly hung

### GitHub API Errors

```
Error: gh CLI not authenticated
```
**Fix:**
```bash
gh auth login
# Follow prompts to authenticate
```

```
Error: API rate limit exceeded
```
**Fix:** Wait 1 hour or authenticate with higher rate limit token.

## Related Documentation

- `/release` skill specification: `.claude/skills/release/skill.md`
- Release agent: `.claude/agents/release-agent.md`
- Contributing: `/CONTRIBUTING.md`
- QA Pipeline: `/CLAUDE/development/QA.md`

## Version History

This release process was introduced in v2.2.0 (2025-01-27).

Previous releases were manual and may not follow this exact process.
