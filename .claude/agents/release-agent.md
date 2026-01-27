# Release Agent - Automated Version Management & Release

## Purpose

Automate the complete release process including version updates, changelog generation, documentation review, and GitHub release creation.

## Capabilities

- Update version across all files (pyproject.toml, version.py, README.md, CLAUDE.md)
- Generate comprehensive changelogs from git commits
- Create release notes with categorized changes
- Coordinate Opus agent for final review
- Create git tags and GitHub releases
- Ensure documentation accuracy

## Process Overview

### 1. Pre-Release Validation

- Verify clean git state (no uncommitted changes)
- Check all QA passes (tests, linting, type checking, coverage)
- Verify current version in all files matches
- Confirm no existing tag for target version

### 2. Version Detection & Strategy

Analyze commits since last tag to determine version bump:

**Semantic Versioning Rules:**
- **MAJOR (x.0.0)**: Breaking changes, incompatible API changes
  - Keywords: "BREAKING", "breaking change", "incompatible"
  - Manual override recommended
- **MINOR (0.x.0)**: New features, backwards-compatible additions
  - Keywords: "feat:", "feature:", "Add ", "Implement "
  - New handlers, capabilities, configuration options
- **PATCH (0.0.x)**: Bug fixes, documentation, internal changes
  - Keywords: "fix:", "bug:", "Fix ", "docs:", "refactor:", "test:"
  - Security fixes, performance improvements, typo fixes

**Version Proposal:**
- Scan commits for keywords
- Propose version bump (MAJOR/MINOR/PATCH)
- Present justification to user
- Allow manual override

### 3. Version Update

Update version string in these files:
1. `pyproject.toml` - line 7: `version = "X.Y.Z"`
2. `src/claude_code_hooks_daemon/version.py` - `__version__ = "X.Y.Z"`
3. `README.md` - line 3: Badge `![Version](https://img.shields.io/badge/version-X.Y.Z-blue)`
4. `CLAUDE.md` - "Current Version" section (search for "Version:")
5. Any upgrade docs that reference version numbers

### 4. Changelog Generation

**Format: Keep a Changelog (https://keepachangelog.com/)**

Structure:
```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features, capabilities, handlers

### Changed
- Modifications to existing functionality
- Documentation updates

### Fixed
- Bug fixes
- Security patches

### Removed
- Deprecated features removed
```

**Categorization Logic:**

Map commit patterns to categories:

**Added:**
- Commits starting with: "Add ", "Implement ", "Create ", "feat:", "feature:"
- New handlers, plugins, features
- Example: "Add TDD enforcement handler"

**Changed:**
- Commits starting with: "Update ", "Modify ", "Change ", "Improve ", "refactor:"
- Breaking changes (mark with **BREAKING**)
- Example: "Update handler priority system"

**Fixed:**
- Commits starting with: "Fix ", "Resolve ", "fix:", "bug:"
- Security fixes (mark with **SECURITY**)
- Example: "Fix daemon startup race condition"

**Removed:**
- Commits starting with: "Remove ", "Delete ", "Deprecate "
- Example: "Remove deprecated handler API"

**Commit Analysis:**
- Get commits since last tag: `git log $(git describe --tags --abbrev=0)..HEAD --oneline`
- If no tags: `git log --oneline` (all history)
- Parse commit messages for patterns
- Group by category
- Remove duplicates and test/internal commits

### 5. Release Notes Generation

Create comprehensive release notes in `RELEASES/vX.Y.Z.md`:

**Structure:**
```markdown
# Release vX.Y.Z - [Release Title]

**Release Date:** YYYY-MM-DD
**Type:** [Major/Minor/Patch] Release

## Summary

[1-2 sentence overview of this release]

## Highlights

- **[Feature/Fix Name]**: Brief description
- **[Feature/Fix Name]**: Brief description
[3-5 key highlights]

## Changes

[Full changelog - copy from CHANGELOG.md entry]

## Upgrade Instructions

[If breaking changes or special upgrade steps needed]

See `CLAUDE/UPGRADES/` for version-specific upgrade guides.

## Installation

### New Installations

```bash
cd .claude
git clone -b vX.Y.Z https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon
python3 -m venv untracked/venv
untracked/venv/bin/pip install -e .
untracked/venv/bin/python install.py
```

### Upgrading Existing Installations

```bash
cd .claude/hooks-daemon
git fetch --tags
git checkout vX.Y.Z
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

## Testing

- **Tests:** [test count] passing
- **Coverage:** [coverage %]
- **Type Safety:** MyPy strict mode compliant
- **Security:** Bandit scan clean

## Contributors

[Auto-generated from git log]

## Full Changelog

**Compare:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/compare/v[PREV]...v[CURRENT]
```

### 6. Documentation Review

**Automated Checks:**
- [ ] All version numbers updated consistently
- [ ] CHANGELOG.md follows Keep a Changelog format
- [ ] Release notes are comprehensive
- [ ] Code examples use correct version tags
- [ ] Installation instructions reference new tag
- [ ] No broken internal links
- [ ] Test counts and coverage numbers accurate

**Content Validation:**
- [ ] Changelog entries match actual changes
- [ ] No duplicate entries
- [ ] Security/breaking changes highlighted
- [ ] Technical accuracy of descriptions
- [ ] Grammar and spelling

### 7. Opus Agent Review

**Invoke Opus for final review:**

```
Task: Comprehensive release review for vX.Y.Z

Please review these files and confirm 100% accuracy:
1. CHANGELOG.md - new vX.Y.Z entry
2. RELEASES/vX.Y.Z.md - release notes
3. Version updates in:
   - pyproject.toml
   - src/claude_code_hooks_daemon/version.py
   - README.md
   - CLAUDE.md

Verification checklist:
- [ ] All version numbers consistent (X.Y.Z)
- [ ] Changelog categorization correct (Added/Changed/Fixed/Removed)
- [ ] Release notes accurately reflect changes
- [ ] No grammatical errors
- [ ] Technical descriptions accurate
- [ ] Upgrade instructions clear
- [ ] No missing critical changes
- [ ] Security/breaking changes properly marked

If ANY issues found, respond with:
{
  "approved": false,
  "issues": ["issue 1", "issue 2", ...]
}

If perfect, respond with:
{
  "approved": true,
  "confidence": "100%",
  "summary": "Brief validation summary"
}
```

**If issues found:**
- Fix all issues
- Re-run automated checks
- Re-submit to Opus
- Repeat until approved

### 8. Commit & Push

Once Opus approves:

```bash
# Stage all changes
git add \
  pyproject.toml \
  src/claude_code_hooks_daemon/version.py \
  README.md \
  CLAUDE.md \
  CLAUDE/CLAUDE.md \
  CHANGELOG.md \
  RELEASES/vX.Y.Z.md

# Commit with conventional format
git commit -m "Release vX.Y.Z: [Release Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Push to main
git push origin main
```

### 9. Create GitHub Tag & Release

```bash
# Create annotated tag
git tag -a vX.Y.Z -m "Release vX.Y.Z: [Release Title]

$(cat RELEASES/vX.Y.Z.md)"

# Push tag
git push origin vX.Y.Z

# Create GitHub release using gh CLI
gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest
```

### 10. Post-Release Verification

- Verify tag exists: `git tag -l vX.Y.Z`
- Check GitHub release page
- Test installation from tag: `git clone -b vX.Y.Z ...`
- Verify badge updates on README.md (GitHub renders)
- Update any external documentation/announcements

## Usage from /release Skill

The skill will:
1. Parse version argument or detect automatically
2. Load this agent specification
3. Execute process steps sequentially
4. Provide progress updates
5. Stop on any error
6. Coordinate Opus review via Task tool
7. Present final summary with links

## Error Handling

**Rollback Strategy:**
- If errors before commit: `git restore .`
- If errors after commit: `git reset --hard HEAD~1` (with user confirmation)
- If errors after push: Create immediate patch release
- Never force-push tags (creates downstream issues)

**Common Errors:**
- Dirty git state → abort, instruct user to commit
- QA failures → abort, run `./scripts/qa/run_all.sh`
- Tag already exists → abort, version conflict
- Opus rejects → fix issues and retry
- GitHub API errors → retry with backoff

## Output Summary

After successful release:

```
✅ Release vX.Y.Z Complete!

📦 Version: X.Y.Z (MAJOR/MINOR/PATCH release)
🏷️  Tag: vX.Y.Z
📝 Changelog: CHANGELOG.md
📋 Release Notes: RELEASES/vX.Y.Z.md
🔗 GitHub Release: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/tag/vX.Y.Z

Next steps:
1. Review release at: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases
2. Update any external documentation
3. Announce release (if applicable)
4. Monitor for issues

Installation command for users:
git clone -b vX.Y.Z https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git
```

## Configuration

No configuration required - fully automated based on:
- Git commit history
- Semantic versioning rules
- Keep a Changelog format
- Project file structure

## Notes

- This agent always creates annotated tags (not lightweight)
- Release notes are preserved in RELEASES/ directory
- Changelog is cumulative (all versions in one file)
- Opus review is mandatory (cannot be skipped)
- All QA must pass before release
- Clean git state is required
