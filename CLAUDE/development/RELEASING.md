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

## 🚨 Review Early, Never Drop Findings (Plan 00157)

The Code Review Gate (Step 10) and CLAUDE.md Guidance Audit (Step 11) currently
run **after** the QA (Step 8) and just **before** the Acceptance gate (Step 12).
That ordering has a cost: any fix applied to a review finding forces a full
FAIL-FAST restart of the QA + acceptance gates (code changes can regress earlier
tests). So **blocking** findings are expensive to fix in place, and there is
pressure to defer **non-blocking** findings — which risks losing review value as
silent tech debt.

Two non-negotiable rules close that gap:

1. **Prefer reviewing early.** When practical, run the code review + guidance
   audit against the diff *before* the QA/acceptance gates, so findings can be
   fixed and re-verified in one pass rather than triggering a downstream
   FAIL-FAST re-run.
2. **Never drop a finding.** Every review finding is either (a) fixed before the
   release ships, or (b) captured as a tracked MUST-FIX item in a follow-up plan
   (`CLAUDE/Plan/NNNNN-*`) with file:line, severity, and remediation, and fixed
   **immediately after** the release to close the loop. A review whose findings
   evaporate into scrollback is wasted work.

## 🚨 Absolute Paths Only (NON-NEGOTIABLE)

**Every command in the release flow MUST use absolute paths. NEVER `cd` into a subdirectory.**

The Bash tool's working directory **persists between calls**. A single `cd` (e.g. into `untracked/release-artifacts/` for a checksum loop) silently breaks every later relative-path command — `git tag -F RELEASES/vX.Y.Z.md`, `git push origin vX.Y.Z`, and `gh release create ... untracked/release-artifacts/*.sh` all resolve against the wrong cwd and fail with `could not open ...`, `src refspec does not match any`, or `no matches found`. This shipped a half-broken release attempt in v3.17.0 (main pushed, tag + GitHub release silently skipped) before it was caught.

Rules:

- Use `/workspace/...` absolute paths for ALL file arguments: `git tag -a vX.Y.Z -F /workspace/RELEASES/vX.Y.Z.md`, `gh release create ... /workspace/untracked/release-artifacts/upgrade.sh`, etc.
- If a step needs a different directory, prefer `git -C /workspace ...` or absolute paths over `cd`. If you must `cd`, immediately `cd /workspace` afterwards in the SAME command, and verify `pwd` before the next git/gh step.
- After tag + release creation, VERIFY with ground-truth checks (`git tag -l vX.Y.Z`, `git ls-remote --tags origin vX.Y.Z`, `gh release view vX.Y.Z`) — non-zero exit or empty result = the step failed; do not trust scrollback.

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

Updates version in: `pyproject.toml`, `version.py`, `README.md` (badge), `CLAUDE.md`, and `.claude/ccy/claude-supervise.py` (the standalone supervisor's hardcoded `__version__`, kept in lockstep — enforced by `tests/unit/supervise/test_compaction_gap_repro.py::TestSupervisorVersionMatchesDaemon`, which FAILS the QA gate if the supervisor version drifts from `version.py`).

Also updates README.md stats: test count badge+body, handler count, event type count from `.claude/HOOKS-DAEMON.md`.

**Re-lock `uv.lock` after the `pyproject.toml` version bump** (self-install mode tracks `uv.lock`): run `uv lock`. The dependency QA check runs `uv lock --check` and will FAIL the Step 8 gate with a lockfile-out-of-date error until the lock is regenerated. Stage `uv.lock` with the release commit.

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

### Move UNRELEASED truth-changes

Truth-changes (Plan 00118) record statements that **were true** about working in a project but became false this release (a `was → now` doc-reconciliation list consumed by `upgrade.md` and `check-truth-changes`). Any staged in `UNRELEASED/truth-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged truth-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/truth-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/truth-changes/
done
```

Verify only `README.md` remains under `UNRELEASED/truth-changes/`:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/truth-changes/
# Expected: README.md  (nothing else)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/truth-changes/` when moving to the next step.

### Move UNRELEASED config-changes

Config-changes (Plan 00133) is the per-version manifest of `added` / `renamed` / `removed` / `changed` config keys, consumed by `upgrade.md` and `check-config-migrations` to surface new + recommended options on upgrade. Any staged in `UNRELEASED/config-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged config-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/config-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/config-changes/
done
```

Verify only `README.md` remains under `UNRELEASED/config-changes/`:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/config-changes/
# Expected: README.md  (nothing else)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/config-changes/` when moving to the next step.

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
- **Did this release change a documented truth?** (a workflow, command, or convention a project's own docs are likely to assert) — if so, a `truth-changes/v{X.Y.Z}.yaml` entry exists (`was → now`, or `now: ~` to retire it) and `UNRELEASED/truth-changes/` contains only `README.md`
- **Did this release add an opt-in feature or flip a default?** (a feature that would otherwise ship dormant in client projects) — if so, a `config-changes/v{X.Y.Z}.yaml` entry exists with `recommended: true` (and `recommended_value:` for a default flip) so the upgrade advisory actively promotes enabling it, and `UNRELEASED/config-changes/` contains only `README.md`

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

**Step 12.0** (H-1 deterministic install/diagnostic gates — Plan 00104 Phase 9
Task 9.6 + Plan 00105 Phase 1): Run BOTH deterministic acceptance gates that
exercise the production install path and the production diagnostic scripts
end-to-end against a fresh fixture project. Together they catch:

- The v3.9.x regression class — `write-venv-metadata` writing the system
  interpreter as `python_path`, `daemon-cli.sh` / `health-check.sh` crashing
  with `ModuleNotFoundError`, skill `upgrade.sh` self-bootstrap silently
  falling back on network failure.
- The v3.10.0 SEV-1 class — `print_info` writing to stdout corrupting every
  `VAR=$(ensure_venv ...)` capture, breaking every upgrade in the field.
- Any future bug in `install_version.sh` → `ensure_venv` → `verify_venv` →
  `write-venv-metadata` → daemon-start that produces a non-running daemon.

```bash
$PYTHON -m pytest tests/acceptance/test_diagnostic_scripts.py tests/acceptance/test_install_sh_end_to_end.py tests/acceptance/test_tool_use_error_recovery.py tests/acceptance/test_stop_hook_hard_block.py tests/acceptance/test_skill_install_python_discovery.py -v
# Expected: tests/acceptance/test_diagnostic_scripts.py — 12 passed
#           tests/acceptance/test_install_sh_end_to_end.py — 2 passed
#           tests/acceptance/test_tool_use_error_recovery.py — 2 passed
#           tests/acceptance/test_stop_hook_hard_block.py — 3 passed
#           tests/acceptance/test_skill_install_python_discovery.py — 4 passed
#           combined: 23 passed, 0 failed
```

ANY failure in any file = ABORT release. The 2026-05-01 field report
(Issues #1, #4, #6) escaped because the v3.9.0 acceptance suite never invoked
the diagnostic scripts — only hook dispatch. The v3.10.0 SEV-1 escaped
because the v3.10.0 H-1 gate synthesised state via `write-venv-metadata`
directly instead of running the production `ensure_venv` capture chain. Both
gaps are closed by adding `test_install_sh_end_to_end.py` here. The Plan
00101 silent-stop recurrence (Edit-on-unread-file → tool_use_error → no
recovery) is closed by adding `test_tool_use_error_recovery.py` — exercises
the `auto_continue_stop` Branch 2.5 directly against the live daemon socket.
The Plan 00101 Phase 9 suggestion-level-downgrade regression class
(v2.1.114 silently demoting JSON-stdout `decision=block` to
`level: suggestion, preventedContinuation: false`) is closed by adding
`test_stop_hook_hard_block.py` — invokes the production bash wrappers
`.claude/hooks/stop` and `.claude/hooks/subagent-stop` as subprocesses
and asserts the exit-2 + stderr contract that v2.1.114 honours for hard
re-entry. The test skips cleanly when no daemon is running locally; under
H-1 the daemon is always started before this step, so a skip there is
itself an abort condition. The Plan 00110 host-a field-report regression
class (host has `python3` → 3.9 alongside `python3.13` / `python3.14`, but
pre-Plan-00110 install.sh aborted with a hardcoded `python3.11` suggestion
that the host did not have) is closed by adding
`test_skill_install_python_discovery.py` — invokes the production
`src/.../skills/hooks-daemon/scripts/install.sh` against synthesised PATH
layouts and asserts (a) the host-a scenario auto-selects `python3.14`
without operator help, and (b) the failure diagnostic NAMES the observed
`python3.9 (3.9.21)` interpreter instead of a hardcoded suggestion that
may not exist on the host.

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

The release bundle MUST include `bootstrap-checksums.txt` alongside ALL FOUR
self-bootstrapping skill scripts: `upgrade.sh`, `daemon-cli.sh`,
`health-check.sh`, and `init-handlers.sh`. Each script's self-bootstrap stanza
(Plan 00104 Task 5.1 Decision 3.C + Plan 00105 Phase 4 Decision 3.B)
downloads the manifest, looks up its own basename, sha256-verifies its own
body, and aborts the run if either is missing or inconsistent. Skipping any
of these four artifacts ships a release that every existing installation
refuses to run for that script — every diagnostic invocation aborts loudly
with `Error: bootstrap-checksums.txt has no entry for <basename>`.

**Note on `upgrade.sh` (Plan 00109)**: As of v3.15.0 the skill-pushed
`upgrade.sh` is a thin shim that fetches `scripts/upgrade.sh` from
`main` HEAD and execs it — it no longer carries a self-bootstrap stanza
and clients never run the published `upgrade.sh` artifact. The artifact
is still bundled here for cross-symmetry with the three sibling scripts
that DO still self-bootstrap against the manifest. Plan 00109 Decision 4
captures the rationale: removing `upgrade.sh` from the manifest would
require touching this loop and the manifest builder, with no upside
until the sibling-script thinning plan lands. Once the siblings are
thinned too, all four artifacts can be dropped together.

```bash
# Build the bootstrap manifest. List every artifact every self-bootstrap
# stanza may verify against — all four skill scripts.
mkdir -p untracked/release-artifacts
SKILL_SCRIPTS_DIR="src/claude_code_hooks_daemon/skills/hooks-daemon/scripts"
for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh; do
    cp "$SKILL_SCRIPTS_DIR/$script" "untracked/release-artifacts/$script"
done
scripts/release/build_bootstrap_checksums.sh \
   untracked/release-artifacts/bootstrap-checksums.txt \
   untracked/release-artifacts/upgrade.sh \
   untracked/release-artifacts/daemon-cli.sh \
   untracked/release-artifacts/health-check.sh \
   untracked/release-artifacts/init-handlers.sh

git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file RELEASES/vX.Y.Z.md \
  --latest \
  untracked/release-artifacts/upgrade.sh \
  untracked/release-artifacts/daemon-cli.sh \
  untracked/release-artifacts/health-check.sh \
  untracked/release-artifacts/init-handlers.sh \
  untracked/release-artifacts/bootstrap-checksums.txt
```

**Verification before continuing**:

```bash
# Every artifact must be reachable from the latest-release URL each
# self-bootstrap stanza uses, and every script's published sha must match
# its manifest entry. ABORT release if any curl fails or any sha mismatches.
BASE="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/latest/download"
curl -fsSL -o /tmp/_check.txt "$BASE/bootstrap-checksums.txt"
for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh; do
    curl -fsSL -o "/tmp/_check_$script" "$BASE/$script"
    PUBLISHED_SHA="$(sha256sum "/tmp/_check_$script" | awk '{print $1}')"
    MANIFEST_SHA="$(awk -v name="$script" '$2 == name {print $1; exit}' /tmp/_check.txt)"
    if [ -z "$MANIFEST_SHA" ]; then
        echo "ABORT: manifest has no entry for $script"; exit 1
    fi
    if [ "$PUBLISHED_SHA" != "$MANIFEST_SHA" ]; then
        echo "ABORT: published $script sha ($PUBLISHED_SHA) != manifest ($MANIFEST_SHA)"; exit 1
    fi
done
# All four matched: release is internally consistent.
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
