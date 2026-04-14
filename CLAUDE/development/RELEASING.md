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
1.  Pre-Release Validation (Agent)
2.  Version Detection
3.  Version Update (Agent)
4.  Changelog Generation (Agent)
5.  Release Notes Creation (Agent)
6.  Move UNRELEASED Post-Upgrade Tasks   <- BLOCKING
7.  Opus Documentation Review
8.  QA Verification Gate                 <- BLOCKING
9.  Breaking Changes Check               <- BLOCKING
10. Code Review Gate                     <- BLOCKING
11. CLAUDE.md Guidance Audit             <- BLOCKING
12. Acceptance Testing Gate              <- BLOCKING
13. Commit & Push
14. Tag & GitHub Release
15. Post-Release Verification
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

## Step 6: Move UNRELEASED Post-Upgrade Tasks (BLOCKING)

**Context**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` accumulates task files written during the release cycle (audits of prior-version bugs, config-migration guidance, workflow-change notifications, etc.). At release time these MUST be moved into the versioned upgrade guide so upgrading users see them.

**See**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md` for the convention and schema.

### What to check

```bash
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
```

| State                           | Action                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Only `README.md` present        | Nothing to move. Delete `post-upgrade-tasks/` from the versioned upgrade guide if one was scaffolded. |
| `NN-*.md` task files present    | Move them (steps below). Do NOT leave them in `UNRELEASED/`.                                          |
| Versioned upgrade guide missing | **ABORT** — create it from `CLAUDE/UPGRADES/upgrade-template/` first (see Step 9).                    |

### How to move

Target: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/`.

```bash
TARGET="CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks"
mkdir -p "$TARGET"

# Copy the per-release index README (if not already present)
cp CLAUDE/UPGRADES/upgrade-template/post-upgrade-tasks/README.md "$TARGET/README.md"

# Move each task file — use git mv so history follows
git mv CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md "$TARGET/"
```

### Populate the per-release task index

Edit `$TARGET/README.md`:

1. Update the heading: `# Post-Upgrade Tasks — vPREV → vNEW`
2. Replace the placeholder task-index table with one row per moved task, ordered by filename. Each row: `| file | type | severity | applies-to | one-line summary |`.
3. Delete the `00-EXAMPLE-task.md` reference — that file only belongs in the template.

### Verify

```bash
# UNRELEASED should contain only README.md
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
# Expected: README.md  (nothing else)

# Versioned guide should list every moved task
cat CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/README.md
# Expected: task index populated, no placeholder rows, no 00-EXAMPLE reference
```

### Reference from release notes

If any moved tasks have `Severity: critical` or `recommended`, `RELEASES/vX.Y.Z.md` MUST reference the post-upgrade-tasks directory so upgrading users know to read it:

```markdown
## Post-Upgrade Tasks

After upgrading, review `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/` — it contains [N] task(s) that may require action in your project (e.g. auditing files damaged by prior-version bugs, adapting to changed defaults).
```

**ABORT condition**: any `NN-*.md` file remains in `UNRELEASED/post-upgrade-tasks/` when moving to the next step.

---

## Step 7: Opus Documentation Review

Opus reviews **documentation only** (not code/QA):

- Version numbers consistent across files
- README.md stats updated
- Changelog accurate and categorized
- Release notes comprehensive
- Security/breaking changes marked
- Upgrade instructions clear
- `UNRELEASED/post-upgrade-tasks/` contains only `README.md` (all tasks moved in Step 6)
- Moved tasks have populated the versioned guide's `post-upgrade-tasks/README.md` task index
- Release notes reference post-upgrade tasks if any are `critical` or `recommended`

Approved -> proceed. Issues found -> agent fixes docs, re-submit until approved.

---

## Step 8: QA Verification Gate (BLOCKING)

Main Claude runs: `./scripts/qa/run_all.sh`

All 10 checks must pass. ANY failure = ABORT.

---

## Step 9: Breaking Changes Check (BLOCKING)

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

## Step 10: Code Review Gate (BLOCKING)

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

## Step 11: CLAUDE.md Guidance Audit (BLOCKING)

Launch sub-agent to analyse `get_claude_md()` completeness across all handlers.

**Sub-agent prompt**: Analyse `/workspace/src/claude_code_hooks_daemon/handlers/` — for each handler, compare `matches()`/`handle()` logic against `get_claude_md()` return value. Report: MISSING GUIDANCE (blocking/advisory handlers returning None), INACCURATE GUIDANCE (content doesn't match logic), ACCEPTABLE NONES (hello_world, status, lifecycle). Focus on PreToolUse blocking handlers first.

Fix any missing/inaccurate guidance. If changes made: run QA, restart daemon, update changelog.

---

## Step 12: Acceptance Testing Gate (BLOCKING)

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

**Step 12.1**: Restart daemon, verify RUNNING.

**Step 12.2**: Verify OBSERVABLE handlers in system-reminders (SessionStart, UserPromptSubmit, PostToolUse).

**Step 12.3**: Generate playbook: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md`

**Step 12.4**: Execute tests sequentially in main thread:

- **BLOCKING tests** (~65): Bash/Write/Edit with dangerous commands, verify hook denies
- **ADVISORY tests** (~24): Verify system-reminder shows context
- **Skip**: Untriggerable lifecycle events (verified by daemon load + unit tests)

**Step 12.5**: All tests must pass. Failed = 0.

### FAIL-FAST Cycle

1. STOP testing immediately
2. Fix bug with TDD
3. Run full QA: `./scripts/qa/run_all.sh`
4. Restart daemon
5. **RESTART ALL tests from Step 12.1** (code changes can regress earlier tests)
6. Repeat until zero failures

---

## Step 13: Commit & Push

```bash
git add pyproject.toml version.py README.md CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md \
  CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/ \
  CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
git commit -m "Release vX.Y.Z: [Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
git push origin main
```

## Step 14: Tag & GitHub Release

```bash
git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest
```

## Step 15: Post-Release Verification

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
# 4. Move UNRELEASED/post-upgrade-tasks/NN-*.md into the versioned upgrade guide
#    and populate its post-upgrade-tasks/README.md task index
# 5. Run QA: ./scripts/qa/run_all.sh
# 6. Commit and push
# 7. Tag: git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z
# 8. gh release create vX.Y.Z --title "vX.Y.Z - [Title]" --notes-file RELEASES/vX.Y.Z.md --latest
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
