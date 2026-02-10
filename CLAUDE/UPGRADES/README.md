# Claude Code Hooks Daemon - Upgrade System

## Overview

This directory contains LLM-optimized version migration guides that allow AI assistants (Claude, GPT, etc.) to autonomously upgrade projects from one version to another.

## Design Philosophy

**Directory-Based Structure**: Each upgrade lives in its own directory with:
- Main upgrade guide (markdown)
- Complete configuration examples (before/after/additions)
- Verification scripts
- Example outputs and test data

**Why This Works for LLMs**:
- No ambiguity - exact config files to reference
- Side-by-side before/after comparisons
- Executable verification steps
- Rich examples for validation
- All related files organized together

## Directory Structure

```
CLAUDE/UPGRADES/
├── README.md                           # This file
├── upgrade-template/                   # Template for future upgrades
│   ├── README.md                       # Main upgrade guide template
│   ├── config-before.yaml             # Example: config before
│   ├── config-after.yaml              # Example: config after
│   ├── config-additions.yaml          # Example: snippet to add
│   ├── verification.sh                # Example: verification script
│   └── examples/                       # Example outputs, test data
├── v1/                                 # v1.x.x upgrades
│   ├── v1.0-to-v1.1/
│   │   └── v1.0-to-v1.1.md            # Main guide
│   └── v1.10-to-v2.0/                 # Major version upgrade
│       ├── v1.10-to-v2.0.md
│       ├── config-additions.yaml
│       ├── config-before.yaml
│       ├── config-after.yaml
│       └── examples/
└── v2/                                 # v2.x.x upgrades
    └── v2.0-to-v2.1/
        ├── v2.0-to-v2.1.md
        ├── config-additions.yaml
        ├── config-before.yaml
        ├── config-after.yaml
        ├── verification.sh
        └── examples/
            ├── yolo-detection-output.json
            └── session-start-test.sh
```

**Version Organization Rules**:
- Upgrades are organized by their SOURCE version's major number
- Example: `v1.10-to-v2.0` lives in `v1/` directory (upgrading FROM v1.x)
- Example: `v2.0-to-v2.1` lives in `v2/` directory (upgrading FROM v2.x)
- This makes it easy to find all upgrades starting from a given major version

## How to Use This System

### For Humans

1. **Determine your current version**:
   ```bash
   cd .claude/hooks-daemon
   cat src/claude_code_hooks_daemon/version.py
   # Or: git describe --tags
   ```

2. **Find the right upgrade path**:
   ```bash
   # If you're at v2.0 and want latest (v2.2)
   cd CLAUDE/UPGRADES/v2/
   ls -1
   # Shows: v2.0-to-v2.1/, v2.1-to-v2.2/

   # Follow upgrades sequentially:
   # 1. Read v2.0-to-v2.1/v2.0-to-v2.1.md
   # 2. Apply upgrade following steps
   # 3. Read v2.1-to-v2.2/v2.1-to-v2.2.md
   # 4. Apply upgrade following steps
   ```

3. **Execute each upgrade**:
   - Read main guide (.md file)
   - Reference supporting files as needed
   - Run verification script
   - Validate against example outputs

### For LLMs

**User prompt**: "Upgrade my hooks-daemon to the latest version"

**Autonomous workflow**:

1. **Detect current version**:
   ```bash
   cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py
   ```

2. **List available upgrades**:
   ```bash
   ls -R CLAUDE/UPGRADES/v*/
   ```

3. **Determine upgrade path**:
   - Current: v2.0
   - Latest: v2.2
   - Path: v2.0 → v2.1 → v2.2

4. **Execute upgrades sequentially**:
   ```
   For each upgrade in path:
     - Read main guide: v2/v2.0-to-v2.1/v2.0-to-v2.1.md
     - Reference supporting files:
       * config-additions.yaml (exact YAML to add)
       * config-before.yaml (starting state)
       * config-after.yaml (ending state)
     - Execute steps from guide
     - Run verification: bash v2/v2.0-to-v2.1/verification.sh
     - Validate against examples/
     - Proceed to next upgrade
   ```

5. **Report completion or errors**

## Upgrade Guide Structure

Each upgrade directory contains:

### Main Guide (vX.Y-to-vX.Z.md)

Required sections:
- **Summary**: What changed and why to upgrade
- **Version Compatibility**: Minimum Claude Code version, rollback support
- **Pre-Upgrade Checklist**: Backup steps, prerequisites
- **Changes Overview**: New/modified/removed features
- **Step-by-Step Instructions**: Exact commands to run
- **Breaking Changes**: What breaks, why, and migration steps
- **Verification Steps**: How to confirm success
- **Rollback Instructions**: How to undo if needed
- **Known Issues**: Problems and workarounds

### Supporting Files

**config-before.yaml**:
- Complete configuration file before upgrade
- Represents typical vX.Y installation
- Use as reference for what's changing

**config-after.yaml**:
- Complete configuration file after upgrade
- Shows vX.Z configuration
- Demonstrates final target state

**config-additions.yaml**:
- ONLY the new configuration to add
- Stripped-down YAML snippet
- LLMs can merge this directly into existing config

**verification.sh**:
- Automated verification script
- Tests that upgrade succeeded
- Checks handler registration, daemon startup, hook execution

**examples/**:
- Example outputs (JSON, logs)
- Test scripts for new features
- Expected behavior demonstrations

## Creating a New Upgrade Guide

1. **Copy the template**:
   ```bash
   cp -r CLAUDE/UPGRADES/upgrade-template CLAUDE/UPGRADES/v2/v2.X-to-v2.Y
   ```

2. **Write main guide** (`v2.X-to-v2.Y.md`):
   - Follow template structure
   - Document all changes
   - Include exact commands
   - Test instructions on clean install

3. **Create supporting files**:
   ```bash
   # config-before.yaml - copy from previous version's config-after.yaml
   # config-after.yaml - new complete config
   # config-additions.yaml - diff the two, extract just additions
   ```

4. **Write verification script**:
   ```bash
   # verification.sh - test:
   # - Daemon starts
   # - New handlers are registered
   # - Hooks execute successfully
   # - New features work as expected
   ```

5. **Add examples**:
   ```bash
   # examples/ - include:
   # - Sample outputs from new features
   # - Test scripts demonstrating new functionality
   # - Expected behavior for validation
   ```

6. **Test the upgrade**:
   - Start with clean vX.X installation
   - Follow your guide step-by-step
   - Verify all steps work
   - Run verification script
   - Confirm examples match actual output

## Version Detection

### Programmatic Detection

```python
from claude_code_hooks_daemon.version import __version__
print(__version__)  # "2.0.0"
```

### Git-Based Detection

```bash
cd .claude/hooks-daemon
git describe --tags  # v2.0.0-3-gabcdef
```

### Config-Based Detection

Some features require specific config versions. Document in upgrade guides:

```yaml
version: "1.0"  # Config format version
```

## State Snapshot System

The Layer 2 upgrade orchestrator (`scripts/upgrade_version.sh`) creates full state snapshots before modifying any files. This enables automatic rollback on failure.

### Snapshot Structure

```
{daemon_dir}/untracked/upgrade-snapshots/{timestamp}/
├── manifest.json       # Metadata: version, timestamp, files list
└── files/
    ├── hooks/          # All hook forwarder scripts (.claude/hooks/*)
    ├── hooks-daemon.yaml  # User config
    ├── settings.json      # Hook registration
    └── init.sh            # Daemon lifecycle script
```

### Snapshot Lifecycle

1. **Created**: Before any upgrade modifications begin
2. **Used for rollback**: If any upgrade step fails, the EXIT trap restores from snapshot
3. **Retained**: 5 most recent snapshots kept; older ones cleaned up automatically
4. **Manual access**: Snapshots persist in `untracked/upgrade-snapshots/` for manual recovery

### Automatic Rollback

The Layer 2 upgrade script sets an EXIT trap that triggers on any non-zero exit. The rollback:
1. Restores all files from snapshot (hooks, config, settings.json)
2. Checks out the original git version
3. Restarts the daemon with restored state
4. Reports rollback status

### Manual Rollback from Snapshot

```bash
DAEMON_DIR=.claude/hooks-daemon

# List available snapshots
ls -la "$DAEMON_DIR/untracked/upgrade-snapshots/"

# Pick the most recent
SNAPSHOT=$(ls -d "$DAEMON_DIR/untracked/upgrade-snapshots/"* | sort -r | head -1)

# View snapshot metadata
cat "$SNAPSHOT/manifest.json"

# Stop daemon
"$DAEMON_DIR/untracked/venv/bin/python" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Restore files
cp "$SNAPSHOT/files/hooks-daemon.yaml" .claude/hooks-daemon.yaml
cp "$SNAPSHOT/files/settings.json" .claude/settings.json 2>/dev/null || true
cp "$SNAPSHOT/files/hooks/"* .claude/hooks/ 2>/dev/null || true

# Checkout original version (read from manifest.json)
cd "$DAEMON_DIR"
git checkout <version-from-manifest>
untracked/venv/bin/pip install -e .

# Restart
cd ../..
"$DAEMON_DIR/untracked/venv/bin/python" -m claude_code_hooks_daemon.daemon.cli restart
```

## Emergency Rollback (No Snapshots)

If upgrade fails and no snapshots are available (e.g., upgrading from a version before the snapshot system):

1. **Restore config backup**:
   ```bash
   cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml
   ```

2. **Revert daemon code**:
   ```bash
   cd .claude/hooks-daemon
   git checkout vX.Y  # Previous working version
   ```

3. **Reinstall dependencies**:
   ```bash
   untracked/venv/bin/pip install -e .
   ```

4. **Restart daemon**:
   ```bash
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
   ```

## Best Practices

### For Upgrade Guide Authors

1. **Be Explicit**: Never assume - spell out every step
2. **Test Thoroughly**: Run through upgrade on clean install
3. **Include Examples**: Show expected outputs, not just commands
4. **Document Edge Cases**: Mention what could go wrong
5. **Provide Rollback**: Always include undo instructions

### For LLMs Performing Upgrades

1. **Read Completely**: Parse entire guide before starting
2. **Check Prerequisites**: Verify all requirements met
3. **Follow Sequentially**: Don't skip or reorder steps
4. **Validate Each Step**: Check output matches examples
5. **Report Issues**: If step fails, explain what went wrong

### For Users

1. **Backup First**: Always backup config before upgrading
2. **Read Breaking Changes**: Check if your workflow is affected
3. **Test After Upgrade**: Run verification steps
4. **Report Bugs**: File issues if upgrade fails

## Upgrade Types

### Patch Upgrades (v2.0.0 → v2.0.1)
- Bug fixes only
- No config changes
- No breaking changes
- Usually just: `git pull && pip install -e .`

### Minor Upgrades (v2.0.0 → v2.1.0)
- New features
- New handlers
- Config additions (backward compatible)
- No breaking changes
- Example: Adding YOLO container detection handler

### Major Upgrades (v2.9.0 → v3.0.0)
- Breaking changes
- Handler API changes
- Config structure changes
- May require manual migration
- Detailed migration guide required

## FAQ

**Q: Can I skip versions?**
A: Not recommended. Follow sequential upgrade path for reliability.

**Q: What if I modified handlers?**
A: Check upgrade guide "Breaking Changes" section. You may need to update your custom handlers.

**Q: How do I find the latest version?**
A: Check GitHub releases or `ls -R CLAUDE/UPGRADES/` to see available upgrades.

**Q: Can LLMs create upgrade guides?**
A: Yes! Use the template and have an LLM document changes between versions.

**Q: What if verification fails?**
A: Follow rollback instructions, then file an issue with error details.

## Two-Layer Upgrade Architecture

The upgrade system uses a two-layer design:

- **Layer 1** (`scripts/upgrade.sh`): Minimal, stable script fetched via curl from GitHub. Detects project root, fetches tags, delegates to Layer 2 via `exec`. Falls back to legacy inline upgrade for older versions without Layer 2.
- **Layer 2** (`scripts/upgrade_version.sh`): Version-specific orchestrator that sources the shared modular library (`scripts/install/*.sh`). Implements "Upgrade = Clean Reinstall + Config Preservation" with automatic rollback.

The per-version upgrade guides in this directory complement the automated Layer 2 flow by documenting breaking changes, config migrations, and manual steps that require human/LLM decision-making.

## Future Enhancements

- Version compatibility matrix
- Templates for different upgrade types (minor, major, hotfix)

## Support

If you encounter upgrade issues:

1. Check daemon logs: `.claude/hooks-daemon/untracked/venv/daemon.log`
2. Review upgrade guide "Known Issues" section
3. Try rollback instructions
4. File issue: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

Include:
- Current version
- Target version
- Steps followed
- Error output
- Daemon logs
