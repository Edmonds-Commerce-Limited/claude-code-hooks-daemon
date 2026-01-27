#!/usr/bin/env bash
# /release skill - Automated release management

set -euo pipefail

VERSION="${1:-auto}"

cat <<'PROMPT'
Execute the release management process using the Release Agent specification.

**Release Agent:** .claude/agents/release-agent.md
**Documentation:** CLAUDE/development/RELEASING.md

**Target Version:** ${VERSION}

**Instructions:**

1. Follow the Release Agent specification exactly
2. Validate all prerequisites before starting
3. Use Opus agent for final review (mandatory)
4. Provide progress updates after each major step
5. Stop immediately on any error with clear message
6. Display final summary with links on success

**Process Steps:**

1. Pre-Release Validation
   - Check git state (must be clean)
   - Run QA checks (all must pass)
   - Verify version consistency
   - Check GitHub CLI auth

2. Version Detection
   - If version="${VERSION}" and it's not "auto", use it
   - Otherwise auto-detect from commits
   - Present proposal and get user confirmation

3. Version Updates
   - pyproject.toml
   - src/claude_code_hooks_daemon/version.py
   - README.md
   - CLAUDE.md
   - CLAUDE/CLAUDE.md

4. Changelog Generation
   - Parse commits since last tag
   - Categorize by type (Added/Changed/Fixed/Removed)
   - Update CHANGELOG.md

5. Release Notes
   - Create RELEASES/vX.Y.Z.md
   - Include summary, highlights, full changelog
   - Add installation/upgrade instructions

6. Opus Review
   - Submit all changes to Opus agent
   - Must receive 100% approval
   - Fix issues and resubmit if rejected

7. Commit & Push
   - Commit all version files
   - Push to main

8. Tag & Release
   - Create annotated git tag
   - Push tag
   - Create GitHub release with gh CLI

9. Verification
   - Confirm tag exists
   - Verify GitHub release published
   - Test installation from tag

10. Report
    - Display success message
    - Show release URL
    - Provide installation command

**Error Handling:**
- Abort on dirty git state
- Abort on QA failures
- Retry Opus review up to 3 times
- Provide rollback instructions if needed

Begin release process now.
PROMPT
