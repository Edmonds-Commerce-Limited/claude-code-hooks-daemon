#!/usr/bin/env bash
# /release skill - Automated release management orchestration

set -euo pipefail

VERSION="${1:-auto}"

cat <<PROMPT
# Release Orchestration for Version: ${VERSION}

Execute the release management process in stages using agent orchestration.

**CRITICAL:** Agents cannot spawn nested agents. You (main Claude) will orchestrate this workflow by invoking agents sequentially.

## Stage 1: Release Preparation & Execution

Use the Task tool to spawn the Release Agent (Sonnet 4.5):

**Agent Spec:** .claude/agents/release-agent.md
**Target Version:** ${VERSION}

**Task for Release Agent:**
\`\`\`
Execute release preparation and file updates for version ${VERSION}.

Follow the Release Agent specification (.claude/agents/release-agent.md) for:

1. Pre-Release Validation (ABORT on ANY failure)
   - Verify clean git state (no uncommitted changes)
   - Run ALL QA checks: Format, Lint, Type Check, Tests, Security
   - Verify version consistency across all files
   - Check GitHub CLI authentication
   - CRITICAL: Do NOT auto-fix issues. User must fix and retry.

2. Version Detection
   - If version="${VERSION}" is not "auto", use it
   - Otherwise auto-detect from commits (semantic versioning)
   - Present proposal to user and get confirmation

3. Version Updates
   - pyproject.toml (line 7)
   - src/claude_code_hooks_daemon/version.py
   - README.md (badge line 3)
   - CLAUDE.md
   - CLAUDE/CLAUDE.md

4. Changelog Generation
   - Parse commits since last tag
   - Categorize (Added/Changed/Fixed/Removed)
   - Update CHANGELOG.md with Keep a Changelog format

5. Release Notes Creation
   - Create RELEASES/vX.Y.Z.md
   - Include summary, highlights, full changelog
   - Add installation/upgrade instructions

**DO NOT:**
- Do not commit changes yet
- Do not spawn nested agents
- Do not push to git

**Output Required:**
- List all files modified
- Show version number determined
- Display changelog entry preview
- Display release notes preview
- Confirm ready for review

Stop and return results. Next stages (code review, acceptance tests, then Opus review) will be handled by main Claude.
\`\`\`

## Stage 1.5: Code Review Gate (You Handle This) - 🚨 BLOCKING

After Stage 1 completes, YOU (main Claude) MUST review the actual code changes before proceeding.

\`\`\`bash
LAST_TAG=\$(git describe --tags --abbrev=0)
git log --oneline "\${LAST_TAG}..HEAD"
git diff "\${LAST_TAG}..HEAD" -- src/
\`\`\`

**Review checklist:**
- [ ] No obvious bugs in handler \`matches()\` / \`handle()\` logic
- [ ] No security anti-patterns (shell injection, hardcoded secrets, unvalidated input)
- [ ] Handler priority ranges correct (10-20 safety, 25-35 quality, 36-55 workflow)
- [ ] Tests exist alongside every handler change
- [ ] No magic strings/numbers (named constants used)
- [ ] SOLID principles — no \`if/elif\` chains on language/type names
- [ ] No debug code, workarounds, or leftover TODOs

**If code looks correct**: Proceed to Stage 2 (Acceptance Testing).
**If issues found**: ABORT, fix issues, re-run \`/release\`.

## Stage 2: Acceptance Test Gate (You Handle This) - 🚨 BLOCKING

**CRITICAL BLOCKING GATE - MANDATORY - NO SHORTCUTS ALLOWED**

After Stage 1.5 (code review passed), YOU (main Claude) MUST determine acceptance testing scope based on bump type.

**STEP 2.0: Determine Acceptance Testing Scope**

\`\`\`bash
LAST_TAG=\$(git describe --tags --abbrev=0)
HANDLER_CHANGES=\$(git diff "\${LAST_TAG}..HEAD" --name-only -- src/claude_code_hooks_daemon/handlers/)
echo "Handler changes: \${HANDLER_CHANGES:-none}"
\`\`\`

| Bump Type | Handler Changes? | Action |
|-----------|-----------------|--------|
| MAJOR | Any | Full acceptance test suite (Steps 2.1+) |
| MINOR | Any | Full acceptance test suite (Steps 2.1+) |
| PATCH | Yes | Targeted tests for changed handlers only |
| PATCH | No | Skip — document reason in release notes, go to Stage 3 |

**PATCH + no handler changes**: Add to release notes:
\`"PATCH release — no handler changes, acceptance testing not required"\`
Then skip to Stage 3 (Opus Review).

**PATCH + handler changes**: Run \`generate-playbook\`, execute only tests for changed handlers, document results. Then proceed to Stage 3.

**MAJOR/MINOR — continue with full suite below:**

**STEP 2.1: Invoke Acceptance Test Skill**

Use the Skill tool to invoke the acceptance-test skill:

\`\`\`
Skill tool:
- skill: "acceptance-test"
- args: "all"
\`\`\`

This is MANDATORY. You MUST invoke the skill, not just mention it or suggest it to the user.

**What this does**:
- Restarts daemon with latest code
- Generates complete test playbook from ALL handler definitions (no filtering)
- Groups tests into batches (3-5 tests each)
- Spawns parallel Haiku agents to execute ALL batches concurrently
- Executes EVERY test (blocking, advisory, context types)
- Reports comprehensive pass/fail/skip results

**STEP 2.2: Verify Results**

Check the output summary:

**✅ SUCCESS CRITERIA** (all must be true):
- \`failed: 0\` (zero failures)
- \`errors: 0\` (zero errors)
- \`skipped: N\` (lifecycle events only - this is normal)
- Message: "All tests passed! Handlers working correctly."

**❌ FAILURE CRITERIA** (any of these = ABORT):
- \`failed: > 0\` (any test failures)
- \`errors: > 0\` (any test errors)
- No output (skill failed to run)
- Daemon not running

**STEP 2.3: Decision Point**

**If ALL tests passed (failed=0, errors=0)**:
- ✅ Proceed to Stage 3 (Opus Review)
- Document total test count in release notes

**If ANY test failed (failed>0 OR errors>0)**:
- ❌ **ABORT RELEASE IMMEDIATELY**
- ❌ **DO NOT PROCEED TO OPUS REVIEW**
- ❌ **DO NOT SKIP THIS GATE**
- Enter FAIL-FAST cycle:
  1. Review failed test details from output
  2. Investigate root cause
  3. Fix handler bug using TDD
  4. Run full QA: \`./scripts/qa/llm_qa.py all\`
  5. Restart daemon
  6. **Re-run \`/acceptance-test all\` from scratch**
  7. Repeat until passed=100%, failed=0, errors=0

**NO SHORTCUTS**:
- ⛔ Cannot skip acceptance testing
- ⛔ Cannot use partial test filters (must use \`all\`)
- ⛔ Cannot ignore failures
- ⛔ Cannot proceed with errors
- ⛔ Cannot use manual testing as substitute for automated

**VERIFICATION CHECKPOINT**:

Before proceeding to Stage 3, you MUST confirm:

1. [ ] Ran \`/acceptance-test all\` (not filtered subset)
2. [ ] Reviewed complete results output
3. [ ] Verified failed=0, errors=0
4. [ ] Total test count documented: ___ tests
5. [ ] No handler bugs found

**If you cannot check ALL boxes above, you MUST NOT proceed.**

**Time Investment**: 4-6 minutes for full automated suite. This is NON-NEGOTIABLE.

**Reference:** \`CLAUDE/development/RELEASING.md\` "Acceptance Testing Gate" section

## Stage 3: Opus Review (You Handle This)

After the Release Agent completes, YOU (main Claude) will:

1. Review the Release Agent's output
2. Use Task tool to spawn an ad-hoc Opus 4.5 agent for final review:

**Task for Opus Agent:**
\`\`\`
model: opus
description: Release documentation validation (NOT code review)

CRITICAL: Review DOCUMENTATION ONLY. Do NOT review code, QA, tests, or security.
All QA checks (tests, lint, types, security) ALREADY PASSED in validation stage.

Review the following release DOCUMENTATION for version X.Y.Z:

Files to review:
- pyproject.toml (version line)
- src/claude_code_hooks_daemon/version.py
- README.md (badge)
- CLAUDE.md (version section)
- CHANGELOG.md (new entry) - CRITICAL: verify accuracy
- RELEASES/vX.Y.Z.md - CRITICAL: verify completeness

Documentation verification checklist:
- [ ] All version numbers consistent (X.Y.Z)
- [ ] Changelog categorization correct (Added/Changed/Fixed/Removed)
- [ ] Release notes comprehensive and accurate
- [ ] No grammatical errors or typos
- [ ] Technical descriptions accurate
- [ ] No missing critical changes in changelog
- [ ] Security/breaking changes properly marked
- [ ] Upgrade instructions clear (if breaking changes)

Do NOT check:
- Code quality (already validated by QA)
- Test coverage (already validated by pytest)
- Type safety (already validated by mypy)
- Security vulnerabilities (already validated by bandit)

Respond with JSON:
{
  "approved": true/false,
  "confidence": "percentage",
  "issues": ["documentation issue 1", "documentation issue 2"] or [],
  "summary": "brief documentation validation summary"
}
\`\`\`

3. If Opus rejects: Invoke Release Agent again to fix DOCUMENTATION issues only
4. If Opus approves: Proceed to Stage 4

## Stage 4: Finalization (You Handle This)

After Opus approval, YOU (main Claude) will:

1. Commit changes:
\`\`\`bash
git add pyproject.toml src/claude_code_hooks_daemon/version.py README.md CLAUDE.md CLAUDE/CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md

git commit -m "Release vX.Y.Z: [Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main
\`\`\`

2. Create tag and GitHub release:
\`\`\`bash
git tag -a vX.Y.Z -m "\$(cat RELEASES/vX.Y.Z.md)"
git push origin vX.Y.Z

gh release create vX.Y.Z \\
  --title "vX.Y.Z - [Title]" \\
  --notes-file RELEASES/vX.Y.Z.md \\
  --latest
\`\`\`

3. Verify:
\`\`\`bash
git tag -l vX.Y.Z
gh release view vX.Y.Z
\`\`\`

4. Display success summary:
\`\`\`
✅ Release vX.Y.Z Complete!

📦 Version: X.Y.Z (MAJOR/MINOR/PATCH release)
🏷️  Tag: vX.Y.Z
📝 Changelog: CHANGELOG.md
📋 Release Notes: RELEASES/vX.Y.Z.md
🔗 GitHub Release: https://github.com/.../releases/tag/vX.Y.Z

Installation command:
git clone -b vX.Y.Z https://github.com/.../hooks-daemon.git
\`\`\`

---

**Error Handling:**
- If Stage 1 fails: Abort, show error
- If Stage 2 fails: Fix handler bugs, re-run acceptance tests
- If Stage 3 rejects: Re-run Stage 1 with documentation fixes
- If Stage 4 fails: Provide rollback instructions

**Documentation:** CLAUDE/development/RELEASING.md

Begin Stage 1 now by invoking the Release Agent.
PROMPT
