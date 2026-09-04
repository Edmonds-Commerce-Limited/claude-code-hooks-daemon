# Claude Code Hooks Daemon - LLM Update Guide

> **v3.7.0+ venv layout change**: From v3.7.0, the venv is **fingerprint-keyed** — `untracked/venv-{slug}-py{MM}-{fingerprint}/` (the `{slug}` component arrived in v3.19.1; canonical layout doc: the "Venv layout" section in [SELF_INSTALL.md](SELF_INSTALL.md)) instead of the legacy `untracked/venv/`. This lets the same project directory work in two different Python envs (e.g. YOLO container + desktop host) without corruption. The upgrader auto-provisions the fingerprint-keyed venv and, when upgrade verification succeeds, auto-deletes the legacy `untracked/venv/`. If you had a bespoke venv location or the auto-cleanup was skipped, run `.claude/hooks-daemon/bin/hooks-daemon prune-venvs --legacy --dry-run` after upgrading to see what's left. Commands below that reference `untracked/venv/` are representative — the actual path after v3.7.0 is resolved dynamically by `scripts/venv-include.bash`.

## CRITICAL: Determine Your Location First

**Before doing ANYTHING, determine where you are.** Working directory confusion is the #1 cause of upgrade failures.

### Quick Location Check

```bash
# Run from wherever you are - the script auto-detects
# Option 1: If you can find the script
.claude/hooks-daemon/scripts/detect_location.sh 2>/dev/null || \
  scripts/detect_location.sh 2>/dev/null || \
  echo "Could not find detect_location.sh - see manual check below"
```

### Manual Location Check

```bash
# Check: Am I at the project root?
ls .claude/hooks-daemon.yaml 2>/dev/null && echo "YES: You are at the project root" || echo "NO"

# Check: Am I inside .claude/hooks-daemon/?
ls src/claude_code_hooks_daemon/version.py 2>/dev/null && echo "YES: You are inside hooks-daemon dir" || echo "NO"

# If inside hooks-daemon, go to project root:
cd ../..
```

### Where You Should Be

**All upgrade commands should be run from the PROJECT ROOT** (the directory containing `.claude/`).

| If you see this...                     | You are at...       | Action                   |
| -------------------------------------- | ------------------- | ------------------------ |
| `.claude/hooks-daemon.yaml` exists     | Project root        | Correct - proceed        |
| `src/claude_code_hooks_daemon/` exists | Inside hooks-daemon | Run `cd ../..` first     |
| Neither exists                         | Wrong directory     | Navigate to project root |

---

## CRITICAL REQUIREMENTS

1. **CONTEXT WINDOW CHECK**: You MUST have at least **50,000 tokens** remaining. If below 50k, STOP and ask user to start fresh session.

2. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch, use: `"Return complete document verbatim without summarization, truncation, or modification"`.

3. **GIT CLEAN STATE**: Working directory MUST be clean. Run `git status` - if not clean, commit/push first.

4. **RESTART CLAUDE CODE after upgrade**: After upgrading, the user MUST restart their Claude Code session (exit and re-enter) to load new hook event types and settings. This is required for ALL minor/major upgrades and recommended for patch upgrades. Daemon restart alone is NOT sufficient for new event types.

---

## Prerequisites

**Python 3.11+ is required.** The daemon uses modern Python features that are not available in older versions.

```bash
# Check your Python version
python3 --version  # Must be 3.11+

# If too old, the upgrade script will search for python3.11/3.12/3.13 automatically
# You can also specify explicitly:
python3.12 --version
```

If no suitable Python is found, install Python 3.11+ before proceeding.

---

## Architecture Overview

The upgrade system uses a **two-layer architecture**:

- **Layer 1** (`scripts/upgrade.sh`): Minimal curl-fetched script (~130 lines). Requires `--project-root PATH` to specify the project directory. Fetches tags, checks out target version first (checkout-first strategy), then delegates to Layer 2 via `exec`.
- **Layer 2** (`scripts/upgrade_version.sh`): Version-specific orchestrator implementing **"Upgrade = Clean Reinstall + Config Preservation"**. Sources a shared modular library (`scripts/install/*.sh`) for all operations.

**Key principle**: Upgrade produces the same clean state as a fresh install, while preserving only user config customizations via a diff/merge/validate pipeline.

### Config Preservation Pipeline

During upgrade, user customizations are preserved automatically:

1. **Backup**: Current config saved to timestamped backup file
2. **Snapshot**: Full state snapshot saved (hooks, config, settings.json) for rollback
3. **Extract**: Diff between old default config and user config identifies customizations
4. **Checkout**: New version code checked out (clean reinstall of code)
5. **Merge**: User customizations merged into new default config
6. **Validate**: Merged config validated for structural correctness
7. **Report**: Any incompatibilities reported to the user

If any step fails, the upgrade rolls back to the snapshot automatically.

---

## RECOMMENDED: Fetch, Review, and Run (Safest Method)

**CRITICAL: Fetch the upgrade script, review it, then run it** - This avoids curl pipe shell patterns that our own security handlers block.

The upgrade script itself handles all git operations (fetch, checkout, pull, etc.). You just need to download it, make sure you're comfortable with what it does, then run it.

### Standard Upgrade Process

```bash
# Download the latest upgrade script
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh

# Review the script to ensure you're comfortable with it
less /tmp/upgrade.sh

# Run it with --project-root pointing to your project directory (REQUIRED)
bash /tmp/upgrade.sh --project-root /path/to/your/project

# Clean up
rm /tmp/upgrade.sh
```

This works for **any version** (including pre-v2.5.0 installations) and is the safest method since you can inspect what the script will do before running it. The `--project-root` argument is required and must point to the directory containing your `.claude/` folder. The script handles all the git fetch/checkout/pull operations.

### Upgrade to Specific Version

```bash
# Fetch and run with version argument
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh
bash /tmp/upgrade.sh --project-root /path/to/your/project v2.9.0
rm /tmp/upgrade.sh
```

### What the Script Does (Two-Layer Flow)

**Layer 1** (the curl-fetched script):

- Uses `--project-root PATH` (required) to locate the project
- Fetches latest tags from remote
- Determines target version (latest tag or specified argument)
- Checks out target version first (checkout-first strategy)
- Delegates to Layer 2 via `exec`

**Layer 2** (version-specific orchestrator):

- Creates state snapshot for rollback (hooks, config, Claude Code `settings.json`)
- Backs up user config and `settings.json` (Claude Code settings are preserved across upgrades)
- Extracts user customizations (diff against old defaults)
- Stops the daemon safely
- Checks out target version code
- Recreates virtual environment (clean venv)
- Deploys hook scripts and slash commands
- Merges user customizations into new default config
- Validates merged config
- Reports any incompatibilities
- Starts daemon and verifies running
- Cleans up old snapshots (keeps 5 most recent)
- Rolls back automatically on any failure

### Why Fetch from GitHub?

**Never use the local upgrade script** (`.claude/hooks-daemon/scripts/upgrade.sh`) because:

1. **Bug fixes** - Your local script might have bugs fixed in newer versions
2. **New features** - Latest script may handle new migration scenarios
3. **Better safety** - Improved rollback and error handling
4. **Bootstrap solution** - Works for all versions, even pre-v2.5.0
5. **Consistency** - Everyone uses the same upgrade logic

This is the same pattern used by `rustup`, `nvm`, `homebrew`, and other modern tooling.

---

## Manual Update (4 Steps)

**All commands below assume you are at the PROJECT ROOT.**

### 1. Verify Prerequisites and Current Version

```bash
# Must show clean working directory
git status --short

# Check current daemon version
cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py

# Backup current config
cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
```

### 2. Fetch and Checkout Latest Version

```bash
cd .claude/hooks-daemon

# Fetch all tags
git fetch --tags

# List available versions
git tag -l | sort -V | tail -10

# Get latest stable tag
LATEST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1) 2>/dev/null || echo "main")
echo "Latest version: $LATEST_TAG"

# Checkout latest version
git checkout "$LATEST_TAG"

# Verify new version
cat src/claude_code_hooks_daemon/version.py

# Return to project root
cd ../..
```

### 3. Update Dependencies and Restart Daemon

```bash
# Rebuild the venv and reinstall the package for the checked-out version.
# Args: PROJECT_ROOT, DAEMON_DIR, TARGET_VERSION (all absolute).
bash .claude/hooks-daemon/scripts/upgrade_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon" "$TARGET_VERSION"

# Restart daemon
.claude/hooks-daemon/bin/hooks-daemon restart || \
  echo "Daemon not running - will start on first hook call"
```

### 4. Verify Update

```bash

# Verify daemon works
.claude/hooks-daemon/bin/hooks-daemon status

# Test hooks still work
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' | \
  .claude/hooks/pre-tool-use
# Expected: {} (empty = allow)

# Test destructive git still blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' | \
  .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
```

**RESTART CLAUDE CODE**: After upgrading, tell the user to restart their Claude Code session (exit and re-enter). New hook event types and settings changes only take effect after a session restart.

---

## Step 5: Discover and Enable New Handlers (CRITICAL)

**After every update, you MUST check for new handlers and enable them.** New versions frequently add safety, quality, and workflow handlers. Leaving them disabled means you lose the main benefit of upgrading.

### Method 1: Discover All Available Handlers (Programmatic)

This discovers ALL handlers by scanning the codebase (source of truth):

```bash
# Every handler the daemon ships, with its default enabled state and priority.
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout

# Every handler the RUNNING daemon actually loaded, by event type.
.claude/hooks-daemon/bin/hooks-daemon handlers
```

### Method 2: Get Full Default Config Template

```bash
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout
```

`--stdout` prints the template and writes nothing, so it is safe on an existing
install — no `--force`, and your current config is untouched.

### Method 3: Compare with Current Config

To find handlers you're missing:

```bash
# Compare YOUR config against the shipped defaults. Anything under
# "added_handlers" exists upstream but is absent from your config.
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout > /tmp/default-config.yaml
.claude/hooks-daemon/bin/hooks-daemon config-diff .claude/hooks-daemon.yaml /tmp/default-config.yaml
```

### Method 4: Version-Specific Config Migration Advisory (Recommended)

The most targeted approach — tells you exactly which new config options are available for your specific upgrade path:

```bash
cd .claude/hooks-daemon

# Replace with your actual versions
PREVIOUS_VERSION="2.8.0"
NEW_VERSION="2.15.2"

.claude/hooks-daemon/bin/hooks-daemon check-config-migrations \
  --from "$PREVIOUS_VERSION" \
  --to "$NEW_VERSION" \
  --config ../.claude/hooks-daemon.yaml
```

**Output interpretation:**

- **Exit code 0**: Config is up to date — no new options to review
- **Exit code 1**: New options available — review and add what's relevant
- Options under **🆕 Recommended — enable these** are dormant features (new
  opt-in protections, or a flipped default) the daemon actively recommends
  turning on. The line shows the recommended value and your current value; set
  the key in your config to adopt it. If a recommendation carries a migration
  **Note**, perform that migration first.
- Options under **💡 New Options Available** are informational — adopt if useful.

Example output:

```
Config Migration Advisory: v2.8.0 → v2.15.2

💡 New Options Available (since v2.8.0):

  v2.9.0: daemon.project_languages
    Optional list of active project languages used to filter strategy-based handlers.
    Example:
      daemon:
        project_languages:
          - Python
          - JavaScript/TypeScript

  v2.13.0: daemon.enforce_single_daemon_process
    Prevents multiple daemon instances. Auto-enabled in container environments.
    Example:
      daemon:
        enforce_single_daemon_process: true

  ... (more options)

Run with --help for all options.
```

**Why this is better than Methods 1-3:**

- Version-aware: only shows options NEW since your previous version (not ones you already have)
- Filters out already-configured options automatically
- Includes descriptions and examples from the version manifests
- Machine-readable: exit code 0/1 for scripting

### Step N (MANDATORY): Run the config-optimisation review

**Run it in the session that ran the upgrade, before reporting the upgrade
done — not "at some point" and not in a hand-back list.** New handlers arrive
in a mix of states: some ship enabled (opt-out), others are opt-in and stay
inert until someone turns them on. An upgrade that ends without a
configuration review is an upgrade where nobody established which is which —
so this step is not optional and not something to reconstruct by hand.

Run the config-optimisation step (`Skill` tool: `skill=hooks-daemon`,
`args=optimise`) — this IS the formalised "review new handlers and enable what's relevant" step (Plan 00308).
It profiles the project, compares the config against
`CLAUDE/UPGRADES/config-changes/` manifests newer than the last recorded
review, and produces a scored, per-handler enable/skip recommendation list
with ready-to-apply config snippets. It only applies changes on your explicit
confirmation ("apply all" / "apply N,M" / "skip"), then restarts and verifies
the daemon, and records the run so the `config_optimisation_reminder`
SessionStart advisory does not re-nag next session.

`/hooks-daemon upgrade` invokes this automatically at the end of a successful
upgrade (pass `--skip-config-optimisation` to opt out and run it yourself
later) — running it manually here is for the documented curl+script upgrade
path, which does not.

A well-configured installation has **30+ handlers enabled**; the review's
report shows the current count against that baseline.

### Understanding Handler Tags

Handlers are tagged by language, function, and specificity. Use tags to filter:

**Language Tags**: `python`, `php`, `typescript`, `javascript`, `go`
**Function Tags**: `safety`, `tdd`, `qa-enforcement`, `workflow`, `advisory`, `validation`
**Specificity Tags**: `ec-specific`, `project-specific`

---

## Post-Update: Handler Status Report (MANDATORY)

**You MUST run this after every upgrade to verify your handler configuration is complete.**

```bash
cd .claude/hooks-daemon
.claude/hooks-daemon/bin/hooks-daemon handlers
```

Review the output and check:

- **Enabled count** — should be **30+ handlers** for a well-configured installation
- **New handlers** — any new handlers from the upgrade should be enabled; the
  config-optimisation review above (`/hooks-daemon optimise`) is what decides which ones
  and applies
  them, not a manual read of this list
- **Disabled handlers** — if any safety or code quality handlers are disabled, the review
  flags them too

---

## Post-Update: Update Project CLAUDE.md

After upgrading, verify the `### Hooks Daemon` section in the project's root `CLAUDE.md` is present and current.

### Check

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#claude-md-check-snippet -->

```bash
grep -n "### Hooks Daemon" CLAUDE.md 2>/dev/null || echo "MISSING - add section"
```

<!-- /ssot-quote -->

### Update if Missing or Outdated

If the section is missing, add it. If it exists but references old paths or commands, update it in place. The canonical template lives in
[LLM-INSTALL.md](LLM-INSTALL.md); quoted here for convenience:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#claude-md-section-template -->

```markdown
### Hooks Daemon

This project uses [claude-code-hooks-daemon](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon) for automated safety and workflow enforcement.

After editing `.claude/hooks-daemon.yaml` — restart the daemon using the `hooks-daemon` skill:

- **Restart**: use the `hooks-daemon` skill with args `restart`
- **Health check**: use the `hooks-daemon` skill with args `health`

> **Important**: `/hooks-daemon` is a **skill** (slash command), not a bash command.
> Invoke it using the Skill tool, e.g. `Skill(skill="hooks-daemon", args="restart")`.
> Do NOT attempt to run `/hooks-daemon` as a bash command — it will fail.

**Key files**:
- `.claude/hooks-daemon.yaml` — handler configuration (enable/disable handlers)
- `.claude/project-handlers/` — project-specific custom handlers (if any)

**Documentation**: `.claude/hooks-daemon/CLAUDE/LLM-INSTALL.md`
```

<!-- /ssot-quote -->

Keep the section terse — 10 lines maximum. Do not duplicate if already present; update in place.

### Also: Check Config Header

Verify `.claude/hooks-daemon.yaml` has the restart-reminder header:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#config-header-check-snippet -->

```bash
grep -q "AFTER EDITING THIS FILE" .claude/hooks-daemon.yaml && echo "OK" || echo "Header missing"
```

<!-- /ssot-quote -->

If missing, prepend this comment block to the top of `.claude/hooks-daemon.yaml`:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#config-header-template -->

```yaml
# Claude Code Hooks Daemon - Handler Configuration
#
# AFTER EDITING THIS FILE: restart the daemon for changes to take effect.
#   User: type /hooks-daemon restart
#   Claude: use Skill tool with skill="hooks-daemon" args="restart"
#
# Verify it is running:
#   User: type /hooks-daemon health
#   Claude: use Skill tool with skill="hooks-daemon" args="health"
#
# Full handler reference: .claude/hooks-daemon/CLAUDE/HANDLER_DEVELOPMENT.md

```

<!-- /ssot-quote -->

---

## Post-Update: Planning Workflow Check (Optional)

After updating, check if you want to adopt or sync with the daemon's planning workflow system.

### Check Current Planning Setup

```bash
ls -la CLAUDE/PlanWorkflow.md 2>/dev/null
ls -la CLAUDE/Plan/ 2>/dev/null
```

### Scenarios

**Scenario 1: No Planning Docs Yet** - See "Post-Installation: Planning Workflow Adoption" in LLM-INSTALL.md.

**Scenario 2: Already Using Planning System** - Check for updates:

```bash
diff CLAUDE/PlanWorkflow.md .claude/hooks-daemon/CLAUDE/PlanWorkflow.md || echo "Docs differ"
```

**Scenario 3: Different Planning Approach** - Keep planning handlers disabled.

---

## Version-Specific Documentation

### RELEASES Directory

**Location**: `RELEASES/` (in daemon repository)

Contains detailed release notes for each version. Use for understanding what changed between versions.

```bash
cd .claude/hooks-daemon
cat RELEASES/v2.2.0.md
```

### UPGRADES Directory

**Location**: `CLAUDE/UPGRADES/` (in daemon repository)

Contains LLM-optimized migration guides with step-by-step instructions, config examples, and verification scripts.

```
CLAUDE/UPGRADES/
├── README.md                     # Upgrade system documentation
├── UNRELEASED/                   # Staging for the NEXT release (post-upgrade tasks etc.)
├── upgrade-template/             # Template for new upgrade guides
├── v1/                           # Upgrades FROM v1.x versions
└── v2/                           # Upgrades FROM v2.x versions
    └── v2.0-to-v2.1/
        ├── v2.0-to-v2.1.md       # Main upgrade guide
        ├── config-before.yaml    # Config before upgrade
        ├── config-after.yaml     # Config after upgrade
        ├── config-additions.yaml # New config to add
        ├── verification.sh       # Verification script
        ├── examples/             # Expected outputs
        └── post-upgrade-tasks/   # OPTIONAL: tasks for the LLM to handle AFTER upgrade
```

---

## Upgrade Path Determination

When upgrading across multiple versions, follow sequential upgrade path:

### 1. Determine Current and Target Versions

```bash
cd .claude/hooks-daemon

CURRENT=$(cat src/claude_code_hooks_daemon/version.py | grep "__version__" | cut -d'"' -f2)
echo "Current: $CURRENT"

git fetch --tags
LATEST=$(git describe --tags $(git rev-list --tags --max-count=1))
echo "Latest: $LATEST"
```

### 2. Find Available Upgrade Guides

```bash
cd .claude/hooks-daemon
ls -la CLAUDE/UPGRADES/v*/
```

### 3. Follow Sequential Upgrades

**Example**: Upgrading from v2.0 to v2.2

1. Read `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/v2.0-to-v2.1.md`
2. Apply v2.0 to v2.1 upgrade steps
3. Read `CLAUDE/UPGRADES/v2/v2.1-to-v2.2/v2.1-to-v2.2.md` (if exists)
4. Apply v2.1 to v2.2 upgrade steps
5. Verify with `verification.sh` at each step
6. **Process post-upgrade tasks** (if `post-upgrade-tasks/` exists in any traversed upgrade guide) — see next section.

**If no upgrade guide exists**: Check `RELEASES/vX.Y.Z.md` for that version's upgrade instructions section.

### Post-Upgrade Tasks (MANDATORY after upgrade completes)

After every successful upgrade, check each traversed upgrade guide for a `post-upgrade-tasks/` directory. These are advisory instructions the upgrading LLM (or human) is expected to read and act on — they cover audits for damage from prior versions, config-value reviews, workflow changes, and similar work that a clean code upgrade alone does not handle.

**Workflow**:

1. For each upgrade in the path (`v2.0-to-v2.1`, `v2.1-to-v2.2`, …):
   ```bash
   ls .claude/hooks-daemon/CLAUDE/UPGRADES/v*/v*-to-v*/post-upgrade-tasks/ 2>/dev/null
   ```
2. If a `post-upgrade-tasks/` directory exists, open its `README.md` for the task index.
3. For each task:
   - Read the header block (Type, Severity, Applies to, Idempotent).
   - **Skip** if `Applies to` does not cover the project's prior version.
   - Otherwise, follow the `## How to detect`, `## How to handle`, and `## How to confirm` sections. Adapt sample commands to the project; do not run them blindly.
4. Report a summary to the user grouped by severity:
   - `critical` — block the user's next step until acknowledged.
   - `recommended` — surface clearly; user can defer.
   - `optional` — mention briefly.

**Why this matters**: A successful code upgrade does not undo damage already done by a buggy prior version, nor does it migrate stale config, nor does it adapt the user's workflow to changed handler behaviour. Skipping post-upgrade tasks leaves known issues unaddressed.

Schema and full convention: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`.

---

## Upgrade Types

### Patch Upgrades (v2.2.0 -> v2.2.1)

- Bug fixes only, no config changes, no breaking changes
- Just update code and restart daemon

```bash
git -C .claude/hooks-daemon fetch --tags
bash .claude/hooks-daemon/scripts/upgrade_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon" v2.2.1
.claude/hooks-daemon/bin/hooks-daemon restart
```

### Minor Upgrades (v2.1.0 -> v2.2.0)

- New features/handlers, may have config additions (backward compatible)
- Check UPGRADES guide for new config options

### Major Upgrades (v2.x -> v3.0)

- Breaking changes likely, config structure may change
- MUST follow UPGRADES guide step-by-step

---

## Rollback Instructions

### Automatic Rollback (via Layer 2 Upgrade Script)

The Layer 2 upgrade orchestrator (`scripts/upgrade_version.sh`) creates state snapshots before any changes. If the upgrade fails at any step, it automatically restores the snapshot.

Snapshots are stored at:

```
.claude/hooks-daemon/untracked/upgrade-snapshots/{timestamp}/
├── manifest.json       # Metadata: version, timestamp, files list
└── files/
    ├── hooks/          # All hook forwarder scripts
    ├── hooks-daemon.yaml
    ├── settings.json
    └── init.sh
```

The 5 most recent snapshots are retained; older ones are automatically cleaned up.

### Manual Rollback (from Snapshot)

If you need to manually restore from a snapshot:

```bash
DAEMON_DIR=.claude/hooks-daemon

# List available snapshots
ls -la "$DAEMON_DIR/untracked/upgrade-snapshots/"

# Pick the most recent
SNAPSHOT=$(ls -d "$DAEMON_DIR/untracked/upgrade-snapshots/"* | sort -r | head -1)
echo "Restoring from: $SNAPSHOT"

# Stop daemon
"$DAEMON_DIR/bin/hooks-daemon" stop 2>/dev/null || true

# Restore config
cp "$SNAPSHOT/files/hooks-daemon.yaml" .claude/hooks-daemon.yaml

# Restore settings
cp "$SNAPSHOT/files/settings.json" .claude/settings.json 2>/dev/null || true

# Restore hooks
cp "$SNAPSHOT/files/hooks/"* .claude/hooks/ 2>/dev/null || true

# Check manifest for original version
cat "$SNAPSHOT/manifest.json"

# Reinstall the original version (from manifest) — rebuilds the venv too
bash "$DAEMON_DIR/scripts/upgrade_version.sh" \
  "$PWD" "$DAEMON_DIR" <version-from-manifest>

# Restart
"$DAEMON_DIR/bin/hooks-daemon" restart
```

### Quick Rollback (Config Only)

```bash
# Stop daemon
.claude/hooks-daemon/bin/hooks-daemon stop 2>/dev/null || true

# Restore config backup
cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml

# Find previous version tag
git -C .claude/hooks-daemon tag -l | sort -V

# Reinstall the previous version (rebuilds the venv too)
bash .claude/hooks-daemon/scripts/upgrade_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon" vX.Y.Z

# Verify rollback
cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py
```

### If Rollback Fails

```bash
# Nuclear option - reinstall from scratch
cd .claude
rm -rf hooks-daemon

# Follow fresh install instructions
# See: LLM-INSTALL.md
```

---

## Config Migration

### Automatic (via Layer 2 Upgrade)

The Layer 2 upgrade script handles config migration automatically using the config preservation pipeline:

1. Backs up current config
2. Extracts your customizations (diff against old defaults)
3. Merges customizations into new version's defaults
4. Validates the merged result
5. Reports any incompatibilities

You only need to act if incompatibilities are reported.

### Manual Config Migration

After updating code, compare your config with the new template:

```bash
cd .claude/hooks-daemon

# Generate new default config
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout > /tmp/new_default_config.yaml

# Diff against your config
diff ../hooks-daemon.yaml /tmp/new_default_config.yaml
```

### Config Preservation CLI

The daemon includes CLI commands for config operations:

```bash

# Diff: find customizations between old default and user config
.claude/hooks-daemon/bin/hooks-daemon config-diff \
  --old-default /tmp/old_default.yaml \
  --user-config .claude/hooks-daemon.yaml

# Merge: apply customizations to new default
.claude/hooks-daemon/bin/hooks-daemon config-merge \
  --new-default /tmp/new_default.yaml \
  --custom-diff /tmp/custom_diff.yaml

# Validate: check config structure (config_path is POSITIONAL, no --config flag)
.claude/hooks-daemon/bin/hooks-daemon config-validate .claude/hooks-daemon.yaml

# Migration advisory: see new options for your upgrade path
.claude/hooks-daemon/bin/hooks-daemon check-config-migrations \
  --from PREVIOUS_VERSION \
  --to NEW_VERSION \
  --config .claude/hooks-daemon.yaml
# Exit code 0 = up to date, 1 = new options available
```

---

## Verification Steps

### Quick Verification

```bash
cd .claude/hooks-daemon

# 1. Version check — the notes header names the INSTALLED version
.claude/hooks-daemon/bin/hooks-daemon release-notes

# 2. Daemon status
.claude/hooks-daemon/bin/hooks-daemon status

# 3. Hook test
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash ../../.claude/hooks/pre-tool-use
```

### Full Verification (for major upgrades)

```bash
cd .claude/hooks-daemon

# Run tests (optional - for thorough verification)
./scripts/qa/run_tests.sh

# Check all QA passes
./scripts/qa/llm_qa.py all
```

---

## Troubleshooting

**All commands below are run from the PROJECT ROOT** (not from inside `.claude/hooks-daemon/`).

### "PROTECTION NOT ACTIVE" Error During Upgrade

**This is expected during upgrade.** When the daemon is stopped for code checkout, hook forwarders will report this error. It does NOT mean your system is broken. Continue with the upgrade steps. The daemon will be restarted as part of the upgrade process.

### Update Fails to Pull

```bash
git -C .claude/hooks-daemon status
git -C .claude/hooks-daemon stash
git -C .claude/hooks-daemon fetch --tags
git -C .claude/hooks-daemon checkout "$LATEST_TAG"
git -C .claude/hooks-daemon stash pop
```

### Daemon Won't Start After Update

```bash

# Check the install is importable and the daemon is serving
.claude/hooks-daemon/bin/hooks-daemon health

# If it reports a broken install, repair it (rebuilds the venv in place)
.claude/hooks-daemon/bin/hooks-daemon repair

# Check daemon logs
.claude/hooks-daemon/bin/hooks-daemon logs
```

### Hooks Don't Work After Update

```bash

# 1. Restart daemon (sufficient for most updates)
.claude/hooks-daemon/bin/hooks-daemon restart

# 2. Check hook forwarders exist
ls -la .claude/hooks/

# 3. Test hook directly
echo '{"tool_name":"Bash","tool_input":{"command":"test"}}' | bash .claude/hooks/pre-tool-use
```

If hooks still fail: Restart Claude Code session (only needed if new event types were added).

### Config Validation Errors

```bash
python3 -c "
import yaml
try:
    yaml.safe_load(open('.claude/hooks-daemon.yaml'))
    print('YAML syntax OK')
except Exception as e:
    print(f'YAML error: {e}')
"
```

### Socket Path Too Long (AF_UNIX Limit)

If your project path is very deep (>60 characters), the Unix socket path may exceed the 108-byte kernel limit.

**Symptoms**: Daemon fails to start with "AF_UNIX path too long" or similar socket error.

**Automatic fix**: The daemon automatically falls back to shorter paths:

1. `$XDG_RUNTIME_DIR/hooks-daemon-{hash}.sock` (preferred)
2. `/run/user/{uid}/hooks-daemon-{hash}.sock` (Linux)
3. `/tmp/hooks-daemon-{hash}.sock` (last resort)

**Manual override**: Set environment variable:

```bash
export CLAUDE_HOOKS_SOCKET_PATH=/tmp/my-project-daemon.sock
```

### Broken Install Recovery

If your installation is in a broken state (missing venv, corrupt config, nested install artifacts):

```bash
# Download latest upgrade script
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh

# Run with explicit project root - it will clean up and rebuild
bash /tmp/upgrade.sh --project-root /path/to/your/project
rm /tmp/upgrade.sh
```

The upgrade script actively cleans up nested install artifacts and rebuilds the venv from scratch.

### Upgrade Aborts on an Old Client (Stuck-Client Recovery)

Clients more than ~2 versions behind can hit a bootstrap/packaging abort _before_ the real
deploy runs. As of v3.16.0+ the canonical `scripts/upgrade.sh` is backward-tolerant and
self-documenting, but if you are running an **older** client shim the escape hatches below
break the deadlock. Try them in order.

**Symptoms** (all occur before the Layer 2 deploy):

- `Unknown option: --already-bootstrapped` — a pre-v3.15 skill shim passes a flag an older
  fetched script rejected. (The canonical script now accepts-and-ignores it.)
- `Canonical python discovery helper missing` — the curl-to-`/tmp` flow ran a script whose
  installed daemon predates `python_discovery.sh`. (The canonical script now fetches its
  own helper.)

**Recovery, in order:**

```bash
# 1. Run the canonical Layer-1 script straight from main — it bypasses the old skill shim
#    entirely, tolerates legacy flags, and fetches its own helpers:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh
bash /tmp/upgrade.sh --project-root /path/to/your/project

# 2. If Python discovery still fails, point it at a known-good interpreter (3.11+):
HOOKS_DAEMON_PYTHON=/usr/bin/python3 bash /tmp/upgrade.sh --project-root /path/to/your/project

# 3. To pull the canonical script from a specific ref instead of main:
HOOKS_DAEMON_UPGRADE_REF=v3.16.0 bash /tmp/upgrade.sh --project-root /path/to/your/project

# 4. Last resort — skip the self-bootstrap verification of the local skill shim (only if
#    1-3 are unavailable and you trust the on-disk script):
HOOKS_DAEMON_SKIP_BOOTSTRAP=1 bash "$PROJECT_ROOT/.claude/skills/hooks-daemon/scripts/upgrade.sh" --project-root "$PROJECT_ROOT"

rm -f /tmp/upgrade.sh
```

Once any path succeeds it installs the current backward-tolerant shim, so the next upgrade
self-heals — you should not need these hatches again.

### `.claude/` Directory Inside Daemon Repo (Not a Nested Install)

The daemon repository contains a `.claude/` directory with project-level handler templates and example configurations. This is **intentional** and is NOT a nested installation. The nested installation detector specifically checks for `.claude/hooks-daemon/.claude/hooks-daemon` (double-nested), not `.claude/hooks-daemon/.claude/`.

If you see `.claude/` inside `.claude/hooks-daemon/`, this is normal and expected.

### Plugin Config Breaking Change (v2.8.0+)

Plugins now require an explicit `event_type` field. If you have custom plugins, update their config:

**Before:**

```yaml
plugins:
  my_plugin:
    module: my_module
```

**After:**

```yaml
plugins:
  my_plugin:
    event_type: pre_tool_use  # Required since v2.8.0
    module: my_module
```

### Venv Broken After Update

```bash

# Try repair command
.claude/hooks-daemon/bin/hooks-daemon repair

# If repair fails, let the installer rebuild the venv from scratch.
# NEVER hand-build one — `python3 -m venv untracked/venv` creates the retired
# pre-v3.7.0 layout, which resolve_venv.sh refuses (every wrapper call exits 5).
CURRENT_TAG="$(git -C .claude/hooks-daemon describe --tags --abbrev=0)"
bash .claude/hooks-daemon/scripts/upgrade_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon" "$CURRENT_TAG"

# Inspect what venvs exist and which one is active
.claude/hooks-daemon/bin/hooks-daemon list-venvs
```

---

## CLI Reference

**All commands from project root** (no `cd` needed):

```bash

.claude/hooks-daemon/bin/hooks-daemon start
.claude/hooks-daemon/bin/hooks-daemon stop
.claude/hooks-daemon/bin/hooks-daemon status
.claude/hooks-daemon/bin/hooks-daemon restart
.claude/hooks-daemon/bin/hooks-daemon logs
.claude/hooks-daemon/bin/hooks-daemon repair   # Fix broken venv
```

---

## Checking for Updates

**From project root:**

```bash
git -C .claude/hooks-daemon fetch --tags
CURRENT=$(python3 -c "
with open('.claude/hooks-daemon/src/claude_code_hooks_daemon/version.py') as f:
    for line in f:
        if '__version__' in line: print(line.split('\"')[1]); break
")
LATEST=$(git -C .claude/hooks-daemon describe --tags $(git -C .claude/hooks-daemon rev-list --tags --max-count=1) 2>/dev/null)
echo "Current: $CURRENT"
echo "Latest: $LATEST"
if [ "$CURRENT" != "${LATEST#v}" ]; then
  echo "Update available!"
else
  echo "Already at latest version"
fi
```

---

## Feedback & Issue Reporting

**IMPORTANT**: During the upgrade process, keep detailed notes of everything that happens. Create a feedback file that the user can optionally share with the project maintainers.

### Create Feedback File

After the upgrade completes (whether successful or not), create a detailed feedback file:

```bash
# Create feedback file at project root
cat > upgrade-feedback-$(date +%Y%m%d).md << 'FEEDBACK'
# Upgrade Feedback Report

## Environment
- **Date**: $(date +%Y-%m-%d)
- **From Version**: [previous version]
- **To Version**: [target version]
- **OS**: [operating system and version]
- **Python Version**: [python3 --version output]
- **Default Python**: [which python3 output]
- **Project Path Length**: [character count of project root path]

## Upgrade Method
- [ ] Automated (upgrade.sh)
- [ ] Manual (step-by-step)

## Results
- **Overall**: SUCCESS / PARTIAL / FAILED
- **Duration**: [how long it took]

## Step-by-Step Log
[Document each step: what command was run, what output was received, any errors or warnings]

1. **Pre-flight checks**: ...
2. **Daemon stop**: ...
3. **Git checkout**: ...
4. **Venv creation**: ...
5. **Config migration**: ...
6. **Daemon start**: ...
7. **Verification**: ...

## Issues Encountered
[List any problems, workarounds, or unexpected behavior]

1. **Issue**: [description]
   **Severity**: Critical / Major / Minor / Cosmetic
   **Workaround**: [what you did to get past it]
   **Suggestion**: [how it could be improved]

## Documentation Gaps
[Note any missing, unclear, or incorrect documentation]

1. [description of gap]

## Suggestions
[Any improvements to the upgrade process]

1. [suggestion]

## Config Changes
[Note any config format changes that required manual intervention]

## Warnings & Anomalies
[Any warnings logged, unexpected behavior, or things that seemed wrong but didn't break anything]
FEEDBACK
```

### What to Document

During the upgrade, actively note:

- **Every command** you run and its output (especially errors/warnings)
- **Every decision point** where you had to choose between options
- **Documentation inconsistencies** where docs said one thing but reality was different
- **Missing prerequisites** that weren't mentioned in docs
- **Confusing error messages** that didn't help you diagnose the issue
- **Workarounds** you had to apply that shouldn't be necessary
- **Time spent** on each step (helps identify bottlenecks)
- **Path/permission issues** especially on different OS configurations

### Sharing Feedback

The feedback file can be shared with project maintainers to improve the upgrade process:

1. Open an issue at the project's GitHub repository
2. Attach or paste the feedback file content
3. Maintainers use this real-world data to fix upgrade issues

**Every piece of feedback makes the next upgrade smoother for everyone.**

---

## Support

If you encounter update issues:

**Check daemon logs**:

```bash
.claude/hooks-daemon/bin/hooks-daemon logs
```

**Run the debug script**:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#debug-report-snippet -->

```bash
# Generate the full diagnostic report (attach it to any bug report)
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

<!-- /ssot-quote -->

**Report the issue**:

- GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
- Include: current version, target version, error output, daemon logs

---

**Update Date:** `date +%Y-%m-%d`
