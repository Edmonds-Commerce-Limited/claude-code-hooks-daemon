# v2.12 → v2.13 Upgrade Resources

## ✅ NO BREAKING CHANGES

This upgrade is **fully backwards-compatible**. Your v2.12.0 configuration will work without modifications.

## Files in This Directory

### Main Upgrade Guide
- **v2.12-to-v2.13.md** - Complete upgrade instructions and feature overview

### Configuration Examples
- **config-before.yaml** - Example v2.12.0 configuration
- **config-after.yaml** - Same configuration (showing no changes needed) + optional new features

### Verification
- **verification.sh** - Automated verification script to confirm upgrade success

## Quick Upgrade

```bash
# Navigate to installation
cd .claude/hooks-daemon/

# Pull v2.13.0
git fetch --tags
git checkout v2.13.0

# Reinstall
untracked/venv/bin/pip install -e .

# Restart daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart

# Verify upgrade (optional)
bash CLAUDE/UPGRADES/v2/v2.12-to-v2.13/verification.sh
```

## What's New in v2.13.0

### New Features
1. **ReleaseBlockerHandler** - Project-level Stop handler prevents AI from skipping acceptance tests
2. **Single Daemon Enforcement** - Auto-enabled in containers to prevent daemon conflicts
3. **PHP QA Fix** - 8 missing suppression patterns now blocked (security fix)
4. **Acceptance Testing** - Streamlined from 127+ to 89 achievable tests
5. **Plan Execution** - Clear model capability guidance for AI orchestration

### Configuration Changes
**None required!** Optional features:
- `daemon.enforce_single_daemon_process` (auto-enabled in containers)
- Project handlers auto-discovery (enabled by default)

## Verification

Run the automated verification script:

```bash
# Basic checks (30 seconds)
bash verification.sh

# Full checks including test suite (2-3 minutes)
bash verification.sh --full
```

Expected output:
```
==========================================
v2.12 → v2.13 Upgrade Verification
==========================================

Checking version... ✓ PASS (v2.13.0)
Validating configuration... ✓ PASS (valid YAML)
Testing daemon startup... ✓ PASS (daemon operational)
Verifying core handlers... ✓ PASS (handlers import successfully)
Checking new v2.13 features... ✓ PASS (single daemon enforcement available)
Verifying project handlers... ✓ PASS (ReleaseBlockerHandler found)

==========================================
✓ All Verification Checks Passed
==========================================
```

## Support

If you encounter issues:

1. **Check the main upgrade guide**: `v2.12-to-v2.13.md`
2. **Review daemon logs**: `cat .claude/hooks-daemon/untracked/daemon.log`
3. **Run verification script**: `bash verification.sh`
4. **Check full release notes**: `/workspace/RELEASES/v2.13.0.md`
5. **Report issues**: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

## Related Documentation

- **Full Release Notes**: [RELEASES/v2.13.0.md](/workspace/RELEASES/v2.13.0.md)
- **Upgrade System**: [CLAUDE/UPGRADES/v2/README.md](/workspace/CLAUDE/UPGRADES/v2/README.md)
- **Changelog**: [CHANGELOG.md](/workspace/CHANGELOG.md)
- **Installation Guide**: [CLAUDE/LLM-INSTALL.md](/workspace/CLAUDE/LLM-INSTALL.md)
- **Update Guide**: [CLAUDE/LLM-UPDATE.md](/workspace/CLAUDE/LLM-UPDATE.md)

---

**Remember**: This is a safe, backwards-compatible upgrade. Just pull the code and restart - no configuration changes needed!
