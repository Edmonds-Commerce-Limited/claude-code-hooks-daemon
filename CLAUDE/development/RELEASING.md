# Release Process

**ALWAYS use `/release` skill. NEVER manually tag, edit CHANGELOG.md, or edit RELEASES/\*.md.**

## Prerequisites

- Clean git state, all QA passing
- `gh auth status` authenticated
- Write access to GitHub repository

## Quick Release

```bash
/release          # auto-detect bump
/release 2.2.0   # explicit version
/release patch    # bump type
```

## Pipeline Overview

```
1. Pre-Release Validation (Agent)
2. Version Detection
3. Version Update (Agent)
4. Changelog Generation (Agent)
5. Release Notes Creation (Agent)
6. Opus Documentation Review
7. QA Verification Gate          <- BLOCKING
8. Breaking Changes Check        <- BLOCKING
9. Code Review Gate              <- BLOCKING
10. CLAUDE.md Guidance Audit     <- BLOCKING
11. Acceptance Testing Gate      <- BLOCKING
12. Commit & Push
13. Tag & GitHub Release
14. Post-Release Verification
```

**ANY blocking gate failure = ABORT release immediately. No exceptions.**

Agents cannot spawn nested agents. Main Claude orchestrates by invoking agents sequentially.

---

## Steps 1-5: Agent-Automated

### 1. Pre-Release Validation

Agent verifies: clean git state, all QA passes, version consistency across files (pyproject.toml, version.py, README.md, CLAUDE.md), no existing tag, gh CLI authenticated.

**ANY failure = IMMEDIATE ABORT. NO auto-fixing.**

### 2. Version Detection

Auto-detects from commits since last tag:

- **PATCH**: fix/bug/docs/refactor keywords
- **MINOR**: feat/Add/Implement keywords
- **MAJOR**: BREAKING/incompatible keywords

Agent proposes bump with justification. Manual override accepted.

### 3. Version Update

Updates version in: `pyproject.toml`, `version.py`, `README.md` (badge), `CLAUDE.md`.

Also updates README.md stats: test count badge+body, handler count, event type count from `.claude/HOOKS-DAEMON.md`.

### 4. Changelog Generation

[Keep a Changelog](https://keepachangelog.com/) format with Added/Changed/Fixed/Removed sections. Parses commits since last tag, groups by prefix, highlights BREAKING and SECURITY.

### 5. Release Notes

Creates `RELEASES/vX.Y.Z.md` with: summary, changelog, upgrade instructions (if breaking), install/upgrade commands, test stats, contributor list, comparison link.

---

## Step 6: Opus Documentation Review

Opus reviews **documentation only** (not code/QA):

- Version numbers consistent across files
- README.md stats updated
- Changelog accurate and categorized
- Release notes comprehensive
- Security/breaking changes marked
- Upgrade instructions clear

Approved -> proceed. Issues found -> agent fixes docs, re-submit until approved.

---

## Step 7: QA Verification Gate (BLOCKING)

Main Claude runs: `./scripts/qa/run_all.sh`

All 10 checks must pass. ANY failure = ABORT.

---

## Step 8: Breaking Changes Check (BLOCKING)

**Context**: v2.11 and v2.12 shipped breaking changes without upgrade docs.

### Detection

Scan the new CHANGELOG.md entry for:

1. Any entries in "Removed" section
2. "BREAKING" keyword in "Changed" section
3. Keywords: "BREAKING", "breaking change", "incompatible", "renamed"
4. New `@abstractmethod` on `Handler` base class in `core/handler.py`
   - If found: `_ABSTRACT_METHOD_VERSIONS` in `project_loader.py` must include it
   - Upgrade guide must document: method name, version, stub to add, detection via `validate-project-handlers`

### Decision

| Breaking Changes? | Upgrade Guide Exists? | Action                         |
| ----------------- | --------------------- | ------------------------------ |
| Yes               | Yes                   | Proceed                        |
| Yes               | No                    | **ABORT** - create guide first |
| No                | N/A                   | Proceed                        |

### Upgrade Guide Requirements

Location: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/`

Template: `CLAUDE/UPGRADES/upgrade-template/`

Must include: summary, version compatibility, pre-upgrade checklist, changes overview, step-by-step instructions, verification steps, rollback instructions.

Release notes MUST reference upgrade guide with BREAKING CHANGES section.

---

## Step 9: Code Review Gate (BLOCKING)

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
git log --oneline "${LAST_TAG}..HEAD"
git diff "${LAST_TAG}..HEAD" -- src/
```

Review checklist:

- No bugs in `matches()`/`handle()` logic
- No security anti-patterns
- Priority ranges correct (10-20 safety, 25-35 quality, 36-55 workflow, 100+ logging)
- Tests exist for every handler change
- Named constants (no magic values), SOLID principles
- No debug code, workarounds, or leftover TODOs

Issues found = ABORT, fix, re-run `/release`.

---

## Step 10: CLAUDE.md Guidance Audit (BLOCKING)

Launch sub-agent to analyse `get_claude_md()` completeness across all handlers.

**Sub-agent prompt**: Analyse `/workspace/src/claude_code_hooks_daemon/handlers/` — for each handler, compare `matches()`/`handle()` logic against `get_claude_md()` return value. Report: MISSING GUIDANCE (blocking/advisory handlers returning None), INACCURATE GUIDANCE (content doesn't match logic), ACCEPTABLE NONES (hello_world, status, lifecycle). Focus on PreToolUse blocking handlers first.

Fix any missing/inaccurate guidance. If changes made: run QA, restart daemon, update changelog.

---

## Step 11: Acceptance Testing Gate (BLOCKING)

**Main thread ONLY. Sub-agent testing is FORBIDDEN** (v2.9.0 incident: async agents create race conditions; sub-agents can't use Write/Edit tools; lifecycle events only fire in main session).

### Scope

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
HANDLER_CHANGES=$(git diff "${LAST_TAG}..HEAD" --name-only -- src/claude_code_hooks_daemon/handlers/)
```

| Bump        | Handler Changes? | Action                              |
| ----------- | ---------------- | ----------------------------------- |
| MAJOR/MINOR | Any              | Full suite                          |
| PATCH       | Yes              | Targeted tests for changed handlers |
| PATCH       | No               | Skip — document in release notes    |

### Execution

**Step 11.1**: Restart daemon, verify RUNNING.

**Step 11.2**: Verify OBSERVABLE handlers in system-reminders (SessionStart, UserPromptSubmit, PostToolUse).

**Step 11.3**: Generate playbook: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md`

**Step 11.4**: Execute tests sequentially in main thread:

- **BLOCKING tests** (~65): Bash/Write/Edit with dangerous commands, verify hook denies
- **ADVISORY tests** (~24): Verify system-reminder shows context
- **Skip**: Untriggerable lifecycle events (verified by daemon load + unit tests)

**Step 11.5**: All tests must pass. Failed = 0.

### FAIL-FAST Cycle

1. STOP testing immediately
2. Fix bug with TDD
3. Run full QA: `./scripts/qa/run_all.sh`
4. Restart daemon
5. **RESTART ALL tests from Step 11.1** (code changes can regress earlier tests)
6. Repeat until zero failures

---

## Step 12: Commit & Push

```bash
git add pyproject.toml version.py README.md CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md
git commit -m "Release vX.Y.Z: [Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
git push origin main
```

## Step 13: Tag & GitHub Release

```bash
git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest
```

## Step 14: Post-Release Verification

```bash
git tag -l vX.Y.Z
gh release view vX.Y.Z --json tagName,isDraft,isPrerelease,url \
  --jq '{tag: .tagName, draft: .isDraft, prerelease: .isPrerelease, url: .url}'
# Expected: draft=false, prerelease=false
```

---

## Rollback

| State                    | Action                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| Before commit            | `git restore .`                                                                            |
| After commit, not pushed | `git reset HEAD~1`                                                                         |
| After push               | Create immediate patch release (NEVER force-push tags)                                     |
| Tag created              | `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z && gh release delete vX.Y.Z --yes` |

## Manual Release (Bypass Skill)

```bash
# 1. Edit versions: pyproject.toml, version.py, README.md, CLAUDE.md
# 2. Update CHANGELOG.md (Keep a Changelog format)
# 3. Create RELEASES/vX.Y.Z.md
# 4. Run QA: ./scripts/qa/run_all.sh
# 5. Commit and push
# 6. Tag: git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z
# 7. gh release create vX.Y.Z --title "vX.Y.Z - [Title]" --notes-file RELEASES/vX.Y.Z.md --latest
```

## Semver Guidelines

| Level | When                                                                |
| ----- | ------------------------------------------------------------------- |
| PATCH | Bug fixes, security patches, docs                                   |
| MINOR | New handlers/features, config options, backwards-compatible         |
| MAJOR | Breaking API/config changes, removed features, Python version bumps |

No fixed schedule. Critical bugs = immediate patch. Features = minor when stable. Breaking = plan ahead.

## Related

- Skill spec: `.claude/skills/release/skill.md`
- Release agent: `.claude/agents/release-agent.md`
- QA pipeline: `CLAUDE/development/QA.md`
- Acceptance tests: `CLAUDE/AcceptanceTests/GENERATING.md`
