# Plan 00067: Fix Upgrade Early-Exit Skips Skill/Slash-Command Deployment

**Status**: Complete (2026-02-22)

## Context

`upgrade_version.sh` lines 159-171 have an early-exit for when the daemon is already at the target version. It only restarts the daemon and exits, bypassing:
- Step 8: Redeploy hook scripts
- Step 9: Redeploy settings.json
- Step 11: .gitignore
- Step 12: Redeploy slash commands
- Step 13: Redeploy skills  ← root cause of missing skills

Skills were added in Plan 00061 (Feb 17 2026). Projects already on v2.16.0 when skills landed can't get them deployed because re-running upgrade exits early.

## Fix

**File:** `scripts/upgrade_version.sh` lines 159-171

Replace the minimal early-exit body with the full idempotent deployment sequence. These steps are all safe to re-run:

```bash
if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]; then
    print_success "Already at version $TARGET_VERSION"
    print_info "Running idempotent deployment steps to ensure files are current..."

    deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

    if [ -f "$SETTINGS_JSON_SOURCE" ]; then
        cp "$SETTINGS_JSON_SOURCE" "$PROJECT_ROOT/.claude/settings.json"
    fi

    setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || true

    deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

    "$VENV_PYTHON" -c "
from pathlib import Path
from claude_code_hooks_daemon.install.skills import deploy_skills
deploy_skills(Path('$DAEMON_DIR'), Path('$PROJECT_ROOT'))
print('✓ Skills redeployed')
"

    restart_daemon_verified "$VENV_PYTHON" || true
    run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false" || true

    print_success "Upgrade verification complete"
    exit 0
fi
```

Skip Steps 3 (snapshot), 4 (stop daemon), 5 (config preservation), 6 (git checkout), 7 (venv recreate) — those are only needed when actually changing code.

## Verification

1. Run `./scripts/qa/run_all.sh` (no Python changes so only shell check matters)
2. Manually test: simulate "already at version" by running upgrade with current version — confirm `.claude/skills/hooks-daemon/` is populated
3. Daemon restart verification per CLAUDE.md requirements

## Files to change

- `scripts/upgrade_version.sh` — lines 159-171 only
