#!/bin/bash
#
# upgrade_version.sh - Layer 2: Version-specific upgrade orchestrator
#
# This script is called by the Layer 1 upgrade.sh after determining the
# target version. It implements "Upgrade = Clean Reinstall + Config
# Preservation" using modular library functions from scripts/install/.
#
# CRITICAL: This script must NEVER run in self-install mode.
#
# Usage (called by Layer 1):
#   bash scripts/upgrade_version.sh "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"
#
# Arguments:
#   $1 - PROJECT_ROOT: Absolute path to the user's project root
#   $2 - DAEMON_DIR: Absolute path to the daemon installation directory
#   $3 - TARGET_VERSION: Git tag or ref to upgrade to (e.g., v2.6.0)
#
# Exit codes:
#   0 - Upgrade completed successfully
#   1 - Upgrade failed (rollback attempted)
#

set -euo pipefail

# Resolve script directory for sourcing library modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB_DIR="$SCRIPT_DIR/install"

# Source all library modules
# shellcheck source=install/output.sh
source "$INSTALL_LIB_DIR/output.sh"
# shellcheck source=install/mode_guard.sh
source "$INSTALL_LIB_DIR/mode_guard.sh"
# shellcheck source=install/prerequisites.sh
source "$INSTALL_LIB_DIR/prerequisites.sh"
# shellcheck source=install/project_detection.sh
source "$INSTALL_LIB_DIR/project_detection.sh"
# shellcheck source=install/venv.sh
source "$INSTALL_LIB_DIR/venv.sh"
# shellcheck source=install/python_fingerprint.sh
source "$INSTALL_LIB_DIR/python_fingerprint.sh"
# shellcheck source=install/venv_resolver.sh
source "$INSTALL_LIB_DIR/venv_resolver.sh"
# shellcheck source=install/hooks_deploy.sh
source "$INSTALL_LIB_DIR/hooks_deploy.sh"
# shellcheck source=install/gitignore.sh
source "$INSTALL_LIB_DIR/gitignore.sh"
# shellcheck source=install/slash_commands.sh
source "$INSTALL_LIB_DIR/slash_commands.sh"
# shellcheck source=install/validation.sh
source "$INSTALL_LIB_DIR/validation.sh"
# shellcheck source=install/daemon_control.sh
source "$INSTALL_LIB_DIR/daemon_control.sh"
# shellcheck source=install/rollback.sh
source "$INSTALL_LIB_DIR/rollback.sh"
# shellcheck source=install/config_preserve.sh
source "$INSTALL_LIB_DIR/config_preserve.sh"
# shellcheck source=install/upgrade_transition.sh
source "$INSTALL_LIB_DIR/upgrade_transition.sh"

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT="${1:-}"
DAEMON_DIR="${2:-}"
TARGET_VERSION="${3:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$DAEMON_DIR" ] || [ -z "$TARGET_VERSION" ]; then
    fail_fast "Usage: upgrade_version.sh <PROJECT_ROOT> <DAEMON_DIR> <TARGET_VERSION>"
fi

if [ ! -d "$PROJECT_ROOT" ]; then
    fail_fast "Project root does not exist: $PROJECT_ROOT"
fi

if [ ! -d "$DAEMON_DIR" ]; then
    fail_fast "Daemon directory does not exist: $DAEMON_DIR"
fi

# Derived paths
# v3.7.0+ venvs are fingerprint-keyed; v3.8.1 added a scan-fallback for the
# fingerprint-mismatch case (installer used python3.13, resolver's python3
# is 3.9). The shared helper implements the same precedence as
# src/.../skills/hooks-daemon/scripts/_resolve-venv.sh so install-time and
# skill-time resolvers always agree. ensure_venv rebuilds/refreshes below.
#
# Plan 00104 Task 5.2: tolerate the no-existing-venv case so set -e does
# not abort the upgrade on a fresh clone or v2.x-stamp project (no
# .daemon-metadata.json, no fingerprint venv yet). Step 7 (ensure_venv)
# bootstraps the new venv from $HOOKS_DAEMON_PYTHON / python3. Stderr is
# NOT silenced — any genuine failure from the canonical resolver
# (paths.py SSOT missing, daemon_dir invalid, paths.py crash) is surfaced
# to the operator. The downstream `[ -f "$VENV_PYTHON" ]` guards already
# gate the codepaths that require an existing interpreter.
VENV_PYTHON="$(resolve_existing_venv_python "$DAEMON_DIR")" || VENV_PYTHON=""
if [ -z "$VENV_PYTHON" ]; then
    print_info "No existing venv found — Step 7 will bootstrap a fresh one via ensure_venv."
fi

# Plan 00164 Phase 1: the TRUE "from" version for user-facing messaging is the
# EXISTING venv's `.daemon-version` stamp — the version the venv was actually
# built/verified against — read BEFORE ensure_venv rebuilds it. Layer 1 has
# already checked out the target tag, so the git ref / pyproject version can be
# AHEAD of what the venv was really built from (the reported "git at v3.40.0 but
# venv stamped v3.38.0" case). Empty when there is no existing stamped venv
# (fresh install / pre-stamp build) — the transition helpers treat empty as
# "installing".
INSTALLED_VERSION=""
if [ -n "$VENV_PYTHON" ]; then
    INSTALLED_VERSION="$(get_venv_version "$(dirname "$(dirname "$VENV_PYTHON")")")"
fi
EXAMPLE_CONFIG="$DAEMON_DIR/.claude/hooks-daemon.yaml.example"
SETTINGS_JSON_SOURCE="$DAEMON_DIR/.claude/settings.json"
TARGET_CONFIG="$PROJECT_ROOT/.claude/hooks-daemon.yaml"

# Rollback state
SNAPSHOT_ID=""
ROLLBACK_REF=""
UPGRADE_STARTED=false

# ============================================================
# Rollback trap
# ============================================================

# shellcheck disable=SC2317  # Invoked indirectly by EXIT trap
cleanup_on_failure() {
    local exit_code=$?
    if [ "$exit_code" -ne 0 ] && [ "$UPGRADE_STARTED" = true ]; then
        echo ""
        print_warning "Upgrade failed - attempting rollback..."

        # Restore from snapshot if available
        if [ -n "$SNAPSHOT_ID" ]; then
            if restore_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "$SNAPSHOT_ID" "normal"; then
                print_success "Rolled back to pre-upgrade state (snapshot: $SNAPSHOT_ID)"
            else
                print_error "Rollback failed. Manual intervention required."
                print_info "Snapshot ID: $SNAPSHOT_ID"
                print_info "Snapshots: $(get_snapshot_dir "$DAEMON_DIR")"
            fi
        elif [ -n "$ROLLBACK_REF" ]; then
            # Fallback: just checkout the old ref
            if git -C "$DAEMON_DIR" checkout "$ROLLBACK_REF" 2>/dev/null; then
                print_success "Rolled back git to: $ROLLBACK_REF"
            else
                print_error "Git rollback failed. Previous ref: $ROLLBACK_REF"
            fi
        fi

        # Try to restart daemon with old code
        if [ -f "$VENV_PYTHON" ]; then
            print_info "Attempting to restart daemon with previous version..."
            # Best-effort rollback — we're already inside cleanup_on_failure, so
            # we cannot abort the trap if restart also fails. `if` wrapper
            # preserves set -e safety while tolerating the failure.
            if restart_daemon_quick "$VENV_PYTHON" 2>/dev/null; then :; fi
        fi
    fi
}
trap cleanup_on_failure EXIT

# ============================================================
# Step 1: Safety checks
# ============================================================

print_header "Claude Code Hooks Daemon - Upgrade"

print_info "Project root: $PROJECT_ROOT"
print_info "Daemon directory: $DAEMON_DIR"
print_info "Target version: $TARGET_VERSION"

log_step "1" "Safety checks"

# CRITICAL: Abort if running in self-install mode
ensure_normal_mode_only "$DAEMON_DIR"

# Validate project structure
validate_project_structure "$PROJECT_ROOT" "true"

# Validate the daemon dir is the ROOT of its own git repository.
#
# `[ -d "$DAEMON_DIR/.git" ]` was safe but too narrow, and Layer 1
# (scripts/upgrade.sh) already replaced it for exactly this reason — the fix
# landed in one script and not its sibling. A git WORKTREE or SUBMODULE stores
# .git as a FILE and is a perfectly valid repository, so the directory test
# false-rejects both. That is not theoretical: it is why
# scripts/dummy-client-repo.sh, this project's own client-mode harness, could
# not exercise this script at all — leaving the Layer 2 upgrade path untested
# in client mode, which is precisely where field bugs come from.
#
# `rev-parse --show-prefix` prints the queried directory's path RELATIVE to its
# repo toplevel, so it is empty exactly AT the toplevel. It accepts clones,
# worktrees and submodules, and still rejects the dangerous shape: a plain
# .claude/hooks-daemon/ inside the user's own repo, where git walks UP and
# answers about the PARENT.
#
# Deliberately NOT a `--show-toplevel` string comparison: that mis-fires
# whenever symlinks make two spellings of the same path differ.
# Pinned by tests/integration/test_upgrade_sh_daemon_dir_detection.py.
DAEMON_DIR_PREFIX="$(git -C "$DAEMON_DIR" rev-parse --show-prefix 2>/dev/null)" \
    || fail_fast "Daemon directory is not a git repository: $DAEMON_DIR"
if [ -n "$DAEMON_DIR_PREFIX" ]; then
    fail_fast "Daemon directory is not the root of its own git repository: $DAEMON_DIR (it sits ${DAEMON_DIR_PREFIX%/} inside a repository rooted above it, so upgrading here would modify THAT repository). Reinstall the daemon into $DAEMON_DIR."
fi

# ============================================================
# Step 2: Pre-upgrade checks
# ============================================================

log_step "2" "Pre-upgrade checks"

# Get current version info
CURRENT_VERSION="unknown"
VERSION_FILE="$DAEMON_DIR/src/claude_code_hooks_daemon/version.py"
if [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    CURRENT_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# Get current git ref for rollback
ROLLBACK_REF=$(git -C "$DAEMON_DIR" describe --tags --exact-match 2>/dev/null || \
               git -C "$DAEMON_DIR" rev-parse --short HEAD 2>/dev/null || \
               echo "")

print_info "Current version: $CURRENT_VERSION"
print_info "Current git ref: ${ROLLBACK_REF:-unknown}"

# Idempotent deployment path.
#
# Plan 00164 Phase 1: Layer 1 (upgrade.sh) ALWAYS checks out the target tag
# before invoking this script, so `ROLLBACK_REF` (git describe --exact-match)
# always equals `$TARGET_VERSION` here — this branch is the effective single
# deployment path for every client upgrade. The message therefore must describe
# the TRUE transition of the actually-built venv (INSTALLED_VERSION, the venv
# stamp) → target, NOT the always-equal git ref. This is the fix for the
# misleading "Already at version X" that fired even on a genuine version jump.
if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]; then
    print_success "$(upgrade_transition_headline "$INSTALLED_VERSION" "$TARGET_VERSION")"
    print_info "Running idempotent deployment steps to ensure files are current..."

    # Plan 00099: ensure_venv uses a fingerprint-keyed venv path so concurrent
    # environments (container vs host, different Pythons) don't clobber each
    # other. Handles stale/missing stamps internally (recreate+restamp).
    VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$TARGET_VERSION" "${HOOKS_DAEMON_PYTHON:-python3}")
    if [ -z "$VENV_PATH" ]; then
        fail_fast "ensure_venv returned empty path"
    fi
    VENV_PYTHON="$VENV_PATH/bin/python"

    if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
        fail_fast "Virtual environment verification failed"
    fi

    # Plan 00099: clean up pre-v3.7.0 legacy venv on idempotent re-runs too.
    # The full upgrade path (Step 7) already does this, but multi-host projects
    # hit the fast path on every host after the first upgrade — so the legacy
    # venv lingered until manually removed. Match the slow-path cleanup exactly.
    LEGACY_VENV="$DAEMON_DIR/untracked/venv"
    if [ -d "$LEGACY_VENV" ] && [ "$VENV_PATH" != "$LEGACY_VENV" ]; then
        print_info "Removing legacy pre-v3.7.0 venv at $LEGACY_VENV"
        rm -rf "$LEGACY_VENV"
    fi

    deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal" "$VENV_PYTHON"

    if [ -f "$SETTINGS_JSON_SOURCE" ]; then
        cp "$SETTINGS_JSON_SOURCE" "$PROJECT_ROOT/.claude/settings.json"
    fi

    setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

    deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

    # Values reach Python as ARGV entries and are never spliced into the
    # generated source. A path containing a quote would otherwise close the
    # Python string literal and raise SyntaxError instead of deploying.
    "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" <<'REDEPLOY_SKILLS_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path(sys.argv[1])
project_root = Path(sys.argv[2])

try:
    deploy_skills(daemon_source, project_root)
    print("✓ Skills redeployed to .claude/skills/hooks-daemon/")
except Exception as e:
    print(f"✗ Skill redeployment failed: {e}")
    sys.exit(1)
REDEPLOY_SKILLS_PY

    # Plan 00136: deploy plan workflow (config-driven SSoT) on the idempotent
    # fast path too, so already-at-target re-runs also deliver mkplan.bash.
    if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_PLAN_WORKFLOW_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled

result = deploy_plan_workflow_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
FASTPATH_PLAN_WORKFLOW_PY
        print_success "Plan workflow deployment complete"
    else
        print_warning "Plan workflow deployment had issues (non-fatal)"
    fi

    # Plan 00334: refresh the daemon-owned core documents on the fast path too.
    # This is the path that carries an upstream correction to an install set up
    # long ago, so skipping it here would freeze every already-at-target client
    # on the documents they were first seeded with.
    if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_CORE_DOCS_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.core_docs import deploy_core_docs_if_enabled

result = deploy_core_docs_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
FASTPATH_CORE_DOCS_PY
        print_success "Core document deployment complete"
    else
        print_warning "Core document deployment had issues (non-fatal)"
    fi

    # Plan 00147/00148: refresh AND arm the ccy supervisor on the idempotent fast
    # path too, so already-at-target re-runs deliver the current claude-supervise.py
    # and ensure ccy.env exports CCY_CLAUDE_WRAPPER (an existing wrapper is kept).
    if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_CCY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import deploy_ccy_supervisor_if_enabled

result = deploy_ccy_supervisor_if_enabled(
    Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
)
for msg in result.messages:
    print(f"  -> {msg}")
if result.recommend_enable:
    print("  -> TIP: set ccy.deploy_supervisor: true in .claude/hooks-daemon.yaml to keep this on")
FASTPATH_CCY_PY
        print_success "ccy supervisor deployment complete"
    else
        print_warning "ccy supervisor deployment had issues (non-fatal)"
    fi

    # Plan 00290 Phase 5: relay binary provisioning on the idempotent fast
    # path too, so a re-run against the same target version still honours a
    # newly-set daemon.transport.relay_source. Null (the default) is a no-op.
    if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_VERSION" <<'FASTPATH_RELAY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config
from claude_code_hooks_daemon.install.relay_deploy import deploy_relay_if_configured

daemon_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
version_tag = sys.argv[3]

transport = load_transport_config(project_root)
result = deploy_relay_if_configured(daemon_dir, project_root, transport, version_tag=version_tag)
for msg in result.messages:
    print(f"  -> {msg}")
sys.exit(0 if (transport.relay_source is None or result.deployed) else 1)
FASTPATH_RELAY_PY
        print_success "Relay binary provisioning complete"
    else
        print_warning "Relay binary provisioning had issues (non-fatal; relay rung falls back to the legacy transport)"
    fi

    if ! restart_daemon_verified "$VENV_PYTHON"; then
        fail_fast "Daemon failed to start after idempotent upgrade"
    fi

    if ! run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"; then
        fail_fast "Post-install verification failed after idempotent upgrade"
    fi

    print_success "$(upgrade_transition_summary "$INSTALLED_VERSION" "$TARGET_VERSION")"
    exit 0
fi

# Run pre-upgrade safety checks if venv exists
if [ -f "$VENV_PYTHON" ]; then
    run_pre_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false" || true
fi

# Pre-upgrade compatibility check (validates BEFORE any changes)
#
# The checker writes its whole report to stderr, so nothing here captures its
# output — it streams straight to the operator. The previous shape captured it
# with `2>&1` into a variable that was only echoed on failure, and under
# `set -e` a non-zero exit from that command substitution killed the script
# before the echo ever ran: an incompatible config aborted the upgrade with no
# explanation at all, and the --force branch below was unreachable.
#
# Every value the checker needs arrives as an ARGV entry, never spliced into
# the generated Python source (a quote in any path or version string produced
# a SyntaxError, which the blanket `except Exception` then reported as a vague
# one-line warning).
#
# Exit codes from the embedded checker:
#   0                          - compatible, or nothing to check
#   COMPAT_INCOMPATIBLE_STATUS - incompatibilities found; honour --force
#   anything else              - the checker itself crashed. Its traceback is
#                                already on stderr; warn loudly and continue,
#                                preserving the long-standing contract that a
#                                broken check must not block an upgrade.
COMPAT_INCOMPATIBLE_STATUS=3
if [ -f "$TARGET_CONFIG" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Checking config compatibility with target version..."

    COMPAT_EXIT=0
    "$VENV_PYTHON" - "$DAEMON_DIR" "$TARGET_CONFIG" "$CURRENT_VERSION" "$TARGET_VERSION" \
        "$COMPAT_INCOMPATIBLE_STATUS" <<'COMPAT_CHECK_PY' || COMPAT_EXIT=$?
import sys
from pathlib import Path

import yaml

from claude_code_hooks_daemon.install.upgrade_compatibility import CompatibilityChecker

daemon_dir = Path(sys.argv[1])
target_config = Path(sys.argv[2])
current_version = sys.argv[3]
target_version = sys.argv[4]
incompatible_status = int(sys.argv[5])

changelog_path = daemon_dir / "CHANGELOG.md"
if not changelog_path.exists():
    print("WARNING: CHANGELOG.md not found, skipping compatibility check", file=sys.stderr)
    sys.exit(0)

with target_config.open() as handle:
    user_config = yaml.safe_load(handle)

checker = CompatibilityChecker(
    changelog_path=changelog_path,
    current_version=current_version,
    target_version=target_version,
)

report = checker.check_compatibility(user_config)

if report.is_compatible:
    print("✓ All handlers compatible with target version", file=sys.stderr)
    sys.exit(0)

print(checker.generate_user_friendly_report(report), file=sys.stderr)
print("", file=sys.stderr)
print("INCOMPATIBILITIES DETECTED", file=sys.stderr)
print("", file=sys.stderr)
print(
    f"Your config references handlers that are incompatible with {target_version}.",
    file=sys.stderr,
)
print("", file=sys.stderr)
print("OPTIONS:", file=sys.stderr)
print("  1. Fix config issues manually and re-run upgrade", file=sys.stderr)
print("  2. Use --force to proceed anyway (config will be updated automatically)", file=sys.stderr)
print("", file=sys.stderr)
sys.exit(incompatible_status)
COMPAT_CHECK_PY

    if [ "$COMPAT_EXIT" -eq "$COMPAT_INCOMPATIBLE_STATUS" ]; then
        # --force is accepted from either channel the old code honoured: the
        # script's own arguments, and the UPGRADE_FLAGS env var Layer 1 sets.
        if [[ "$*" == *"--force"* ]] || [[ "${UPGRADE_FLAGS:-}" == *"--force"* ]]; then
            print_warning "Proceeding despite incompatibilities (--force detected)"
        else
            fail_fast "Config compatibility check failed. Use --force to proceed anyway."
        fi
    elif [ "$COMPAT_EXIT" -ne 0 ]; then
        print_error "Config compatibility check crashed (exit $COMPAT_EXIT) - traceback above."
        print_warning "Continuing without a compatibility verdict; review $TARGET_CONFIG after the upgrade."
    fi
fi

# ============================================================
# Step 3: Create state snapshot
# ============================================================

log_step "3" "Creating state snapshot for rollback"

SNAPSHOT_ID=$(create_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "normal" 2>/dev/null | tail -1)

if [ -n "$SNAPSHOT_ID" ]; then
    print_success "Snapshot created: $SNAPSHOT_ID"
else
    print_warning "Could not create snapshot - upgrade will proceed without rollback capability"
fi

# Mark upgrade as started (enables rollback on failure)
UPGRADE_STARTED=true

# ============================================================
# Step 4: Stop daemon
# ============================================================

log_step "4" "Stopping daemon"
stop_daemon_safe "$VENV_PYTHON"
sleep 1

# ============================================================
# Step 5: Backup and extract config customizations
# ============================================================

log_step "5" "Preserving config customizations"

# Save the old example config before checkout (for diff baseline)
OLD_DEFAULT_CONFIG=""
if [ -f "$EXAMPLE_CONFIG" ]; then
    OLD_DEFAULT_CONFIG=$(mktemp /tmp/hooks_daemon_old_default_XXXXXX.yaml)
    cp "$EXAMPLE_CONFIG" "$OLD_DEFAULT_CONFIG"
    print_verbose "Saved old default config for diff baseline"
fi

# Backup current config
CONFIG_BACKUP=""
if [ -f "$TARGET_CONFIG" ]; then
    CONFIG_BACKUP=$(backup_config "$PROJECT_ROOT")
    print_verbose "Config backup: $CONFIG_BACKUP"
fi

# Breaking changes detection (compare old vs new default config)
if [ -f "$TARGET_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Analyzing config for breaking changes..."

    # Run config diff analyzer.
    #
    # Capture its STDOUT only: stdout is the JSON payload, stderr is
    # diagnostics. The previous `2>&1` folded the two together, so a single
    # warning line corrupted the JSON — and the `|| echo "{}"` fallback then
    # hid that corruption behind an empty result indistinguishable from a
    # clean "no breaking changes" run. Failures are now reported explicitly.
    DIFF_EXIT=0
    DIFF_RESULT=$("$SCRIPT_DIR/install/config_diff_analyzer.sh" \
        "$TARGET_CONFIG" "$OLD_DEFAULT_CONFIG") || DIFF_EXIT=$?

    if [ "$DIFF_EXIT" -ne 0 ]; then
        print_error "config_diff_analyzer.sh failed (exit $DIFF_EXIT) - its stderr is above."
        print_warning "Skipping breaking-changes detection; review $TARGET_CONFIG after the upgrade."
    elif [ -z "$DIFF_RESULT" ]; then
        print_error "config_diff_analyzer.sh produced no output - expected a JSON object on stdout."
        print_warning "Skipping breaking-changes detection; review $TARGET_CONFIG after the upgrade."
    else
        # The diff JSON and the daemon dir arrive as ARGV entries, never
        # spliced into the generated Python source: a value containing a quote
        # used to produce a SyntaxError that the old blanket suppression at the
        # end of this block then swallowed whole.
        BREAKING_CHANGES_EXIT=0
        "$VENV_PYTHON" - "$DAEMON_DIR" "$DIFF_RESULT" <<'BREAKING_CHANGES_PY' || BREAKING_CHANGES_EXIT=$?
import json
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.breaking_changes_detector import BreakingChangesDetector

daemon_dir = Path(sys.argv[1])
diff_json = sys.argv[2]

changelog_path = daemon_dir / "CHANGELOG.md"
if not changelog_path.exists():
    sys.exit(0)

diff_data = json.loads(diff_json)
removed_handlers = diff_data.get("removed", [])
renamed_handlers = diff_data.get("renamed", {})

if not removed_handlers and not renamed_handlers:
    sys.exit(0)

detector = BreakingChangesDetector(changelog_path)
warnings = detector.generate_warnings(
    removed_handlers=removed_handlers,
    renamed_handlers=renamed_handlers,
)

if warnings:
    print("", file=sys.stderr)
    print("⚠️  BREAKING CHANGES DETECTED IN CONFIG", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for warning in warnings:
        print(warning, file=sys.stderr)
        print("", file=sys.stderr)
    print("Your config will be automatically updated during merge.", file=sys.stderr)
    print("Review the config after upgrade completes.", file=sys.stderr)
    print("", file=sys.stderr)
BREAKING_CHANGES_PY

        if [ "$BREAKING_CHANGES_EXIT" -ne 0 ]; then
            print_error "Breaking-changes detection crashed (exit $BREAKING_CHANGES_EXIT) - traceback above."
            print_warning "Continuing the upgrade; review $TARGET_CONFIG after it completes."
        fi
    fi
fi

# ============================================================
# Step 5a: Upgrade guide reading enforcement
# ============================================================

# Detect version jump and list required upgrade guides.
#
# Nothing is captured here: the checker's report goes to stderr and streams
# straight to the operator. The previous shape captured stdout+stderr into
# GUIDE_CHECK purely to grep it for a sentinel string, which meant the
# "REQUIRED READING" report the user was meant to act on was swallowed by the
# capture and never printed. The sentinel is now an EXIT CODE, and every value
# the checker needs is an ARGV entry rather than text spliced into the
# generated Python source.
GUIDES_FOUND_STATUS=4
UPGRADE_GUIDES_LIST="/tmp/upgrade_guides_list.txt"
if [ "$CURRENT_VERSION" != "unknown" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Checking for required upgrade guides..."

    GUIDE_CHECK_EXIT=0
    "$VENV_PYTHON" - "$DAEMON_DIR" "$CURRENT_VERSION" "$TARGET_VERSION" \
        "$UPGRADE_GUIDES_LIST" "$GUIDES_FOUND_STATUS" <<'GUIDE_CHECK_PY' || GUIDE_CHECK_EXIT=$?
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.upgrade_compatibility import CompatibilityChecker

daemon_dir = Path(sys.argv[1])
current_version = sys.argv[2]
target_version = sys.argv[3]
guides_list_path = Path(sys.argv[4])
guides_found_status = int(sys.argv[5])

changelog_path = daemon_dir / "CHANGELOG.md"
if not changelog_path.exists():
    sys.exit(0)

checker = CompatibilityChecker(
    changelog_path=changelog_path,
    current_version=current_version,
    target_version=target_version,
)

guides = checker.suggest_upgrade_guides(daemon_dir)

if not guides:
    sys.exit(0)

print("", file=sys.stderr)
print("📚 REQUIRED READING: Upgrade Guides", file=sys.stderr)
print("=" * 70, file=sys.stderr)
print(f"Upgrading from v{checker.current_version} to v{checker.target_version}", file=sys.stderr)
print(f"You are skipping {len(guides)} intermediate version(s).", file=sys.stderr)
print("", file=sys.stderr)
print("Please review the following upgrade guides:", file=sys.stderr)
for guide in guides:
    print(f"  • {guide}", file=sys.stderr)
print("", file=sys.stderr)

# Hand the guide list to bash, which drives the interactive confirmation.
with guides_list_path.open("w") as handle:
    for guide in guides:
        handle.write(str(guide) + "\n")

sys.exit(guides_found_status)
GUIDE_CHECK_PY

    if [ "$GUIDE_CHECK_EXIT" -ne 0 ] && [ "$GUIDE_CHECK_EXIT" -ne "$GUIDES_FOUND_STATUS" ]; then
        print_error "Upgrade-guide check crashed (exit $GUIDE_CHECK_EXIT) - traceback above."
        print_warning "Continuing without a guide list; review $DAEMON_DIR/CLAUDE/UPGRADES/ manually."
    fi

    if [ "$GUIDE_CHECK_EXIT" -eq "$GUIDES_FOUND_STATUS" ]; then
        # Skip interactive prompt when:
        # - --skip-reading-confirmation flag is set, OR
        # - stdin is not a terminal (non-interactive mode, e.g. run by CI or Claude Code agent)
        #   Without this check, `read` hangs forever waiting for input that never arrives
        if [[ "$*" == *"--skip-reading-confirmation"* ]] || [ ! -t 0 ]; then
            if [ ! -t 0 ]; then
                print_info "Non-interactive mode detected, skipping upgrade guide confirmation"
            else
                print_info "--skip-reading-confirmation flag detected, skipping guide confirmation"
            fi
            print_info "Review upgrade guides after upgrade: $DAEMON_DIR/CLAUDE/UPGRADES/"
            rm -f "$UPGRADE_GUIDES_LIST"
        else
            echo ""
            echo "Have you read all upgrade guides? (yes/no/show)"
            read -r -p "> " response

            while true; do
                case "$response" in
                    yes|y|Y)
                        print_success "Proceeding with upgrade..."
                        break
                        ;;
                    show|s|S)
                        # Display guides using pager
                        if [ -f "$UPGRADE_GUIDES_LIST" ]; then
                            while IFS= read -r guide_path; do
                                if [ -f "$guide_path" ]; then
                                    echo ""
                                    echo "========================================="
                                    echo "Displaying: $guide_path"
                                    echo "========================================="
                                    ${PAGER:-less} "$guide_path"
                                fi
                            done < "$UPGRADE_GUIDES_LIST"
                        fi
                        echo ""
                        echo "Have you read all upgrade guides? (yes/no/show)"
                        read -r -p "> " response
                        ;;
                    no|n|N)
                        echo ""
                        print_warning "Please review upgrade guides before proceeding."
                        print_info "Guides location: $DAEMON_DIR/CLAUDE/UPGRADES/"
                        fail_fast "Upgrade aborted - read guides and try again"
                        ;;
                    *)
                        echo "Please answer 'yes', 'no', or 'show'"
                        read -r -p "> " response
                        ;;
                esac
            done

            # Cleanup temp file
            rm -f "$UPGRADE_GUIDES_LIST"
        fi
    fi
fi

# ============================================================
# Step 6: Checkout target version
# ============================================================

log_step "6" "Checking out target version"

print_info "Fetching tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

# Verify target version exists
if ! git -C "$DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null; then
    fail_fast "Version $TARGET_VERSION not found. Available versions:
$(git -C "$DAEMON_DIR" tag -l | sort -V | tail -10)"
fi

print_info "Checking out $TARGET_VERSION..."
git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet
print_success "Checked out $TARGET_VERSION"

# ============================================================
# Step 7: Recreate virtual environment (clean reinstall)
# ============================================================

log_step "7" "Recreating virtual environment"

# Plan 00099: use fingerprint-keyed venv so concurrent environments (container
# vs host, different Pythons) each keep their own healthy venv. ensure_venv
# rebuilds when the stamp is missing/stale and handles creation atomically.
VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$TARGET_VERSION" "${HOOKS_DAEMON_PYTHON:-python3}")
if [ -z "$VENV_PATH" ]; then
    fail_fast "ensure_venv returned empty path"
fi
VENV_PYTHON="$VENV_PATH/bin/python"

if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
    fail_fast "Virtual environment verification failed"
fi

# Plan 00099: clean up pre-v3.7.0 legacy venv to avoid confusion. Only remove
# the legacy path if we successfully provisioned a fingerprint-keyed venv at a
# distinct location.
LEGACY_VENV="$DAEMON_DIR/untracked/venv"
if [ -d "$LEGACY_VENV" ] && [ "$VENV_PATH" != "$LEGACY_VENV" ]; then
    print_info "Removing legacy pre-v3.7.0 venv at $LEGACY_VENV"
    rm -rf "$LEGACY_VENV"
fi

# ============================================================
# Step 8: Redeploy hook scripts
# ============================================================

log_step "8" "Redeploying hook scripts"
deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal" "$VENV_PYTHON"

# ============================================================
# Step 9: Redeploy settings.json
# ============================================================

log_step "9" "Redeploying settings.json"

TARGET_SETTINGS="$PROJECT_ROOT/.claude/settings.json"

if [ -f "$SETTINGS_JSON_SOURCE" ]; then
    cp "$SETTINGS_JSON_SOURCE" "$TARGET_SETTINGS"
    print_success "Redeployed settings.json"
else
    print_verbose "No settings.json in daemon repo (using existing)"
fi

# ============================================================
# Step 10: Config preservation (merge customizations onto new default)
# ============================================================

log_step "10" "Merging config customizations"

NEW_DEFAULT_CONFIG="$EXAMPLE_CONFIG"

if [ -n "$OLD_DEFAULT_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ] && [ -f "$TARGET_CONFIG" ]; then
    # Full config preservation: diff + merge + validate
    if preserve_config_for_upgrade "$VENV_PYTHON" "$PROJECT_ROOT" "$OLD_DEFAULT_CONFIG" "$NEW_DEFAULT_CONFIG"; then
        print_success "Config customizations preserved"
    else
        print_warning "Config preservation had issues - review config manually"
        print_info "Backup: $CONFIG_BACKUP"
    fi
elif [ ! -f "$TARGET_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ]; then
    # No existing config - copy new default
    cp "$NEW_DEFAULT_CONFIG" "$TARGET_CONFIG"
    print_success "Installed new default config"
else
    print_info "Config preservation skipped (missing baseline or config)"
    if [ -n "$CONFIG_BACKUP" ]; then
        print_info "Your config backup: $CONFIG_BACKUP"
    fi
fi

# Clean up temp file
if [ -n "$OLD_DEFAULT_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ]; then
    rm -f "$OLD_DEFAULT_CONFIG"
fi

# ============================================================
# Step 11: Setup .gitignore
# ============================================================

log_step "11" "Verifying .gitignore"
setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

# ============================================================
# Step 12: Redeploy slash commands
# ============================================================

log_step "12" "Redeploying slash commands"
deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 13: Redeploy skills
# ============================================================

log_step "13" "Redeploying user-facing skills"

"$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" <<'SLOWPATH_SKILLS_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path(sys.argv[1])
project_root = Path(sys.argv[2])

try:
    deploy_skills(daemon_source, project_root)
    print("✓ Skills redeployed to .claude/skills/hooks-daemon/")
except Exception as e:
    print(f"✗ Skill redeployment failed: {e}")
    sys.exit(1)
SLOWPATH_SKILLS_PY

# ============================================================
# Step 13b: Redeploy the hooks-daemon bin wrapper (Plan 00192)
# ============================================================
#
# Daemon-owned tooling: overwritten on every upgrade so a stale wrapper can
# never outlive a fix. This step is what delivers the wrapper to installs that
# predate it — without it, existing projects would keep the broken
# "$PYTHON -m ..." guidance forever. DAEMON_DIR is the daemon root in both
# install modes.

log_step "13b" "Redeploying hooks-daemon CLI wrapper"

"$VENV_PYTHON" - "$DAEMON_DIR" <<'REDEPLOY_BIN_WRAPPER_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.bin_wrapper import deploy_bin_wrapper

try:
    target = deploy_bin_wrapper(Path(sys.argv[1]))
    print(f"✓ CLI wrapper redeployed to {target}")
except Exception as e:
    print(f"✗ CLI wrapper redeployment failed: {e}")
    sys.exit(1)
REDEPLOY_BIN_WRAPPER_PY

# ============================================================
# Step 14: Deploy plan workflow (config-driven SSoT — Plan 00136)
# ============================================================
#
# Runs AFTER config merge (Step 10) so config.plan_workflow.enabled reflects
# the upgraded config. Deployment is derived from that config (the SSoT the
# daemon reads), exactly as hooks/slash-commands/skills are redeployed every
# run. This closes the bug where mkplan.bash was never delivered on upgrade.

log_step "14" "Deploying plan workflow (if enabled in config)"

if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_PLAN_WORKFLOW_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled

result = deploy_plan_workflow_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
SLOWPATH_PLAN_WORKFLOW_PY
    print_success "Plan workflow deployment complete"
else
    print_warning "Plan workflow deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14a: Core document deployment (config-driven SSoT — Plan 00334)
# ============================================================
#
# Daemon-owned core documents are refreshed on every upgrade, which is what
# lets an upstream correction reach an install set up long ago; the client's
# own override document beside each one is never touched. Gated per document
# on the subsystem whose guidance names it, NOT on the plan workflow above.

log_step "14a" "Deploying core documents (per-subsystem gates)"

if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_CORE_DOCS_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.core_docs import deploy_core_docs_if_enabled

result = deploy_core_docs_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
SLOWPATH_CORE_DOCS_PY
    print_success "Core document deployment complete"
else
    print_warning "Core document deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14b: Redeploy + arm ccy PTY supervisor (config-gated — Plan 00147/00148)
# ============================================================
#
# Refreshes .claude/ccy/claude-supervise.py from the upgraded daemon clone AND
# arms it (ensures ccy.env exports CCY_CLAUDE_WRAPPER) when a .claude/ccy/ dir is
# present and ccy.deploy_supervisor is not false, so ccy projects always run the
# current supervisor — and actually wrap claude with it — after an upgrade. An
# existing user-set CCY_CLAUDE_WRAPPER is left untouched.

log_step "14b" "Deploying + arming ccy supervisor (if a .claude/ccy/ project)"

if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_CCY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import deploy_ccy_supervisor_if_enabled

result = deploy_ccy_supervisor_if_enabled(
    Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
)
for msg in result.messages:
    print(f"  -> {msg}")
if result.recommend_enable:
    print("  -> TIP: set ccy.deploy_supervisor: true in .claude/hooks-daemon.yaml to keep this on")
SLOWPATH_CCY_PY
    print_success "ccy supervisor deployment complete"
else
    print_warning "ccy supervisor deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14c: Deploy relay binary (Plan 00290 Phase 5 — explicit config choice only)
# ============================================================
#
# daemon.transport.relay_source is null by default and never runs implicitly
# (Phase 5 owner ruling): "build" compiles from source with plain rustc when a
# musl-capable toolchain is present, "download" fetches the digest-verified
# release asset matching TARGET_VERSION. Either way this is advisory-only —
# a failure never aborts the upgrade; the relay rung simply stays unprovisioned
# and every hook falls back to the permanent bash+python3 transport.

log_step "14c" "Deploying relay binary (if daemon.transport.relay_source is configured)"

if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_VERSION" <<'SLOWPATH_RELAY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config
from claude_code_hooks_daemon.install.relay_deploy import deploy_relay_if_configured

daemon_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
version_tag = sys.argv[3]

transport = load_transport_config(project_root)
result = deploy_relay_if_configured(daemon_dir, project_root, transport, version_tag=version_tag)
for msg in result.messages:
    print(f"  -> {msg}")
sys.exit(0 if (transport.relay_source is None or result.deployed) else 1)
SLOWPATH_RELAY_PY
    print_success "Relay binary provisioning complete"
else
    print_warning "Relay binary provisioning had issues (non-fatal; relay rung falls back to the legacy transport)"
fi

# ============================================================
# Step 15: Restart daemon and verify
# ============================================================

log_step "15" "Restarting daemon"

if ! restart_daemon_verified "$VENV_PYTHON"; then
    print_error "Daemon failed to start after upgrade"
    print_info "This may indicate config validation errors"
    print_info "Check: $DAEMON_DIR/bin/hooks-daemon status"

    if [ -n "$CONFIG_BACKUP" ]; then
        echo ""
        print_info "To restore previous config:"
        echo "  cp $CONFIG_BACKUP $TARGET_CONFIG"
        echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    fi

    # Don't trigger rollback for daemon start failure - code is updated
    # User can fix config manually
    UPGRADE_STARTED=false
    exit 1
fi

# Clear version check cache to prevent stale upgrade indicators
rm -f "$DAEMON_DIR/untracked/version_check_cache.json"

# Plan 00100 Task 3.9: eager cleanup of stale venvs after the new daemon
# is verified RUNNING on $VENV_PATH. Order matters — cleanup runs AFTER
# restart_daemon_verified so a failed upgrade leaves prior state intact
# (rollback safety). Plain daemon start (non-upgrade) is unaffected; it
# still uses lazy-rebuild-via-stamp inside ensure_venv.
eager_cleanup_stale_venvs "$DAEMON_DIR" "$VENV_PATH"

# ============================================================
# Step 16: Post-upgrade validation
# ============================================================

log_step "16" "Running post-upgrade validation"
if ! run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"; then
    print_error "Post-upgrade validation failed"
    print_info "The daemon may not be fully functional. Review the errors above."

    if [ -n "$CONFIG_BACKUP" ]; then
        echo ""
        print_info "To restore previous config:"
        echo "  cp $CONFIG_BACKUP $TARGET_CONFIG"
        echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    fi

    # Don't trigger rollback - code is updated, but user needs to investigate
    UPGRADE_STARTED=false
    exit 1
fi

# ============================================================
# Step 16.5: Project-handler load validation (Plan 00143)
# ============================================================
#
# An upgrade can introduce a new REQUIRED handler method (e.g. get_claude_md,
# abstract since v2.30.0). Older project handlers that predate it then fail to
# load and are silently skipped — a protection regression. Surface it loudly at
# the moment it happens, but do NOT fail the upgrade: the daemon itself is
# healthy and skips the broken handlers safely; the user just needs to fix and
# restart. The session-start alert + `health` exit code (Plan 00143) keep
# nagging until they do.

log_step "16.5" "Validating project handlers"
if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli validate-project-handlers; then
    print_success "All project handlers load correctly"
else
    echo ""
    print_warning "PROJECT PROTECTION DEGRADED: one or more project handlers failed to load"
    print_warning "after this upgrade and are NOT protecting your sessions."
    print_info "This usually means an upgrade added a required handler method an older"
    print_info "handler does not implement yet. The daemon started fine and skipped them."
    print_info "Fix the handler(s) above, then restart the daemon:"
    echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    print_info "Until then, every new session will show a degraded-protection alert."
fi

# ============================================================
# Step 17: Cleanup old snapshots
# ============================================================

log_step "17" "Cleanup"
cleanup_old_snapshots "$DAEMON_DIR" 3

# Get new version
NEW_VERSION="unknown"
if [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    NEW_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# ============================================================
# Complete
# ============================================================

# Disable rollback on success
UPGRADE_STARTED=false

print_header "Upgrade Complete"

print_success "Claude Code Hooks Daemon upgraded successfully!"
echo ""
echo "  Previous version: $CURRENT_VERSION"
echo "  Current version:  $NEW_VERSION"
echo "  Config:           $TARGET_CONFIG"
echo "  Config backup:    ${CONFIG_BACKUP:-none}"
echo "  Rollback snapshot: ${SNAPSHOT_ID:-none}"
echo ""

# Check for upgrade guides
UPGRADE_DIR="$DAEMON_DIR/CLAUDE/UPGRADES"
if [ -d "$UPGRADE_DIR" ]; then
    echo "Version-specific upgrade notes:"
    echo "  ls $UPGRADE_DIR/"
    echo ""
fi

# Plan 00308: every upgrade ends with the config-optimisation review, unless
# explicitly opted out. Same --force-style detection as the compat check
# above -- this script has no proper flag parser, so match against $* and the
# UPGRADE_FLAGS passthrough.
#
# Plan 00322: the mandate claims THIS session and is printed BEFORE the
# restart instruction. Addressed to "your next Claude Code session", and
# printed after "exit your current session", it read as a hand-back note --
# a client upgrade duly filed it as an optional "run it at some point".
if [[ "$*" == *"--skip-config-optimisation"* ]] || [[ "${UPGRADE_FLAGS:-}" == *"--skip-config-optimisation"* ]]; then
    echo "Config-optimisation review skipped (--skip-config-optimisation)."
    echo "Run it yourself when ready: Skill tool, skill=hooks-daemon, args=optimise."
    echo ""
else
    echo "MANDATORY NEXT STEP -- do this NOW, in this session, before you"
    echo "report the upgrade as done and before the restart below: run the"
    echo "config-optimisation review (Skill tool: skill=hooks-daemon,"
    echo "args=optimise)."
    echo "It is not an optional follow-up and does not belong in a hand-back"
    echo "list: handlers new in $NEW_VERSION stay inert until it runs."
    echo "It inventories disabled-but-relevant handlers, surfaces what is new,"
    echo "and produces a per-handler enable/skip recommendation list -- it"
    echo "never applies changes without your explicit confirmation."
    echo "Pass --skip-config-optimisation to this script to opt out."
    echo ""
fi

echo "IMPORTANT: after the review, restart Claude Code to activate upgraded hooks."
echo "  1. Exit your current Claude Code session"
echo "  2. Start a new Claude Code session"
echo ""

exit 0
