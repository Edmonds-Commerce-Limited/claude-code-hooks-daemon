#!/bin/bash
#
# Claude Code Hooks Daemon - Upgrade Script (Layer 1)
#
# SECURITY: Always fetch the latest version from GitHub before running:
#   curl -fsSL https://raw.githubusercontent.com/.../scripts/upgrade.sh -o /tmp/upgrade.sh
#   less /tmp/upgrade.sh   # Review contents
#   bash /tmp/upgrade.sh --project-root /path/to/project [VERSION]
#
# This is a minimal Layer 1 script that:
# 1. Takes explicit project root (no magic detection)
# 2. Stops daemon (best-effort)
# 3. Checks out target version
# 4. Cleans up nested install artifacts
# 5. Delegates to Layer 2 (scripts/upgrade_version.sh)
#
# Arguments:
#   --project-root PATH  - REQUIRED: Project root directory
#   VERSION              - Git tag to upgrade to (optional, defaults to latest)
#

set -euo pipefail

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT=""
TARGET_VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        --project-root)
            [ -n "${2:-}" ] || { echo "ERR --project-root requires a path argument" >&2; exit 1; }
            PROJECT_ROOT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: upgrade.sh --project-root PATH [VERSION]"
            echo ""
            echo "  --project-root PATH  Project root directory (REQUIRED)"
            echo "  VERSION              Git tag to upgrade to (default: latest)"
            exit 0
            ;;
        --already-bootstrapped)
            # Plan 00114 F1: backward-compat allowlist for historical bootstrap
            # flags. Pre-v3.15 skill shims (still in the wild) self-bootstrap by
            # re-exec'ing this script with --already-bootstrapped. This script no
            # longer uses that flag, but REJECTING it created a bootstrap deadlock
            # (the fix is delivered BY the upgrade the broken shim blocks). Accept
            # and ignore it. Genuinely-unknown flags are still rejected below
            # (typo protection — see the -* case).
            echo "WARN Ignoring legacy bootstrap flag (no longer required): $1" >&2
            shift
            ;;
        -*)
            echo "ERR Unknown option: $1" >&2
            echo "Usage: upgrade.sh --project-root PATH [VERSION]" >&2
            exit 1
            ;;
        *)
            # Positional arg = version
            TARGET_VERSION="$1"
            shift
            ;;
    esac
done

# Minimal output functions
if [ -t 1 ]; then
    _RED='\033[0;31m'; _GREEN='\033[0;32m'; _YELLOW='\033[1;33m'
    _BLUE='\033[0;34m'; _BOLD='\033[1m'; _NC='\033[0m'
else
    _RED=''; _GREEN=''; _YELLOW=''; _BLUE=''; _BOLD=''; _NC=''
fi

_ok()   { echo -e "${_GREEN}OK${_NC} $1"; }
_err()  { echo -e "${_RED}ERR${_NC} $1" >&2; }
_warn() { echo -e "${_YELLOW}WARN${_NC} $1"; }
_info() { echo -e "${_BLUE}>>>${_NC} $1"; }
_fail() { _err "$1"; exit 1; }

# ============================================================
# Python version detection
# ============================================================

#
# find_compatible_python() - Find a Python 3.11+ interpreter
#
# Plan 00110 Phase 4 Task 4.1: delegates to the canonical
# ``scripts/lib/python_discovery.sh::find_latest_python`` helper. Replaces
# the prior hardcoded candidate list (``python3.13`` / ``python3.12`` /
# ``python3.11``) and inline ``compgen`` discovery with one source of truth.
#
# Precedence (preserved unchanged from the prior implementation):
#   1. ``HOOKS_DAEMON_PYTHON`` — explicit override, validated, fails fast
#   2. Glob ``$PATH`` for ``python3.[1-9][0-9]``, pick highest minor
#
# When a daemon_dir is provided AND its pyproject.toml carries a
# ``requires-python`` lower bound, the helper raises the floor accordingly
# (the host-a-style cross-check from Plan 00104 Phase 7 Task 7.2).
#
# Sets and exports HOOKS_DAEMON_PYTHON so Layer 2 scripts can use it.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (exits via _fail)
#
# Plan 00110 Phase 6: defer sourcing python_discovery.sh until after the
# daemon_dir is known. The script may be curl-fetched into /tmp (the
# canonical "review-before-running" pattern) or exec'd from /tmp by the
# skill thin-shim — in both cases ``$(dirname "${BASH_SOURCE[0]}")/lib/``
# is empty. Resolving from the installed daemon dir first is the only
# layout that works for all three call sites:
#   - self-install (script sibling)
#   - downstream install (daemon dir = $PROJECT_ROOT/.claude/hooks-daemon)
#   - skill shim exec from /tmp (script sibling absent → daemon dir wins)
# Plan 00114 F2: when Layer 1 is curl-fetched into /tmp (the documented
# "review-before-running" flow) AND the installed daemon predates
# python_discovery.sh, BOTH local lookups miss and the upgrade aborts with
# "Canonical python discovery helper missing" — the documented escape hatch is
# itself broken. As a last resort, self-fetch the helper from the same
# ref/base-URL the skill thin-shim uses. Writes to a temp file cleaned by an
# EXIT trap. curl's exit code is captured EXPLICITLY (not via an inline
# `if curl && [ -s ]`) so a transient curl failure is distinguishable from an
# empty download.
# EXIT-time cleanup of the self-fetched temp file. The trap runs a direct
# `rm -f` (not a wrapper function) so shellcheck does not flag an
# only-invoked-via-trap helper as unreachable (SC2317). `rm -f ""` on an
# unset path is a harmless no-op that returns 0.
_PYTHON_DISCOVERY_FETCHED_TMP=""
trap 'rm -f "$_PYTHON_DISCOVERY_FETCHED_TMP"' EXIT

_fetch_python_discovery_lib() {
    local ref base_url url tmp curl_path
    ref="${HOOKS_DAEMON_UPGRADE_REF:-main}"
    base_url="${HOOKS_DAEMON_UPGRADE_BASE_URL:-https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon}"
    url="$base_url/$ref/scripts/lib/python_discovery.sh"

    # Presence check: capture `command -v` output into a variable instead of
    # redirecting to a null sink, so nothing is discarded (no error-hiding).
    if ! curl_path="$(command -v curl)"; then
        return 1
    fi
    if [ -z "$curl_path" ]; then
        return 1
    fi
    if ! tmp="$(mktemp)"; then
        return 1
    fi
    # curl's exit status is consumed directly by the `if` (success only when
    # curl returns 0 AND the download is non-empty), so a transient fetch
    # failure is never swallowed — it falls through to the failure path.
    if curl -fsSL --max-time 30 -o "$tmp" "$url" && [ -s "$tmp" ]; then
        _PYTHON_DISCOVERY_FETCHED_TMP="$tmp"
        printf '%s\n' "$tmp"
        return 0
    fi
    rm -f "$tmp"
    return 1
}

_resolve_python_discovery_lib() {
    local daemon_dir="${1:-}"
    if [ -n "$daemon_dir" ] && [ -f "$daemon_dir/scripts/lib/python_discovery.sh" ]; then
        printf '%s\n' "$daemon_dir/scripts/lib/python_discovery.sh"
        return 0
    fi
    local sibling
    sibling="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/python_discovery.sh"
    if [ -f "$sibling" ]; then
        printf '%s\n' "$sibling"
        return 0
    fi
    # Plan 00114 F2: last-resort network self-fetch for the /tmp call site.
    local fetched
    if fetched="$(_fetch_python_discovery_lib)"; then
        printf '%s\n' "$fetched"
        return 0
    fi
    return 1
}

find_compatible_python() {
    local daemon_dir="${1:-}"
    local pyproject=""
    if [ -n "$daemon_dir" ] && [ -f "$daemon_dir/pyproject.toml" ]; then
        pyproject="$daemon_dir/pyproject.toml"
    fi

    local discovery_lib
    if ! discovery_lib="$(_resolve_python_discovery_lib "$daemon_dir")"; then
        # Plan 00114 F4: this only fires when the daemon dir lacks the helper,
        # the script has no sibling lib/, AND the F2 network self-fetch failed
        # (offline / behind a proxy). Surface actionable recovery — never leave
        # the user hard-stuck guessing the internal escape hatch.
        _fail "Canonical python discovery helper missing: searched ${daemon_dir:+$daemon_dir/scripts/lib/python_discovery.sh and }$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/python_discovery.sh, and the network self-fetch also failed.
Recovery options:
  1. Run upgrade.sh from the INSTALLED daemon dir (it ships the helper):
       bash \"\$PROJECT_ROOT/.claude/hooks-daemon/scripts/upgrade.sh\" --project-root \"\$PROJECT_ROOT\"
  2. Set HOOKS_DAEMON_PYTHON to an absolute Python 3.11+ path to skip discovery:
       HOOKS_DAEMON_PYTHON=/path/to/python3 bash $0 --project-root \"\$PROJECT_ROOT\"
  3. If a stale skill shim re-execs with a legacy flag, bypass its bootstrap:
       HOOKS_DAEMON_SKIP_BOOTSTRAP=1 bash \"\$PROJECT_ROOT/.claude/skills/hooks-daemon/scripts/upgrade.sh\""
    fi
    # shellcheck source=lib/python_discovery.sh
    . "$discovery_lib"

    local found
    if ! found="$(find_latest_python 3.11 "$pyproject")"; then
        exit 1
    fi
    HOOKS_DAEMON_PYTHON="$found"
    export HOOKS_DAEMON_PYTHON
    _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
    return 0
}

# ============================================================
# Main
# ============================================================

echo -e "${_BOLD}Claude Code Hooks Daemon - Upgrade${_NC}"
echo "========================================"

# Step 1: Validate project root
[ -n "$PROJECT_ROOT" ] || _fail "--project-root is required.\nUsage: upgrade.sh --project-root /path/to/project [VERSION]"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)" # Resolve to absolute path
[ -d "$PROJECT_ROOT" ] || _fail "Project root does not exist: $PROJECT_ROOT"
_ok "Project root: $PROJECT_ROOT"

# Step 2: Find compatible Python interpreter (3.11+)
#
# Plan 00104 Phase 7 Task 7.2: locate the daemon's pyproject.toml so the
# probe can cross-check requires-python. Prefer the namespaced install
# path; fall back to PROJECT_ROOT only when this script lives inside the
# daemon's own repo (self-install — scripts/upgrade.sh is daemon-only).
_DAEMON_PYPROJECT_DIR=""
if [ -f "$PROJECT_ROOT/.claude/hooks-daemon/pyproject.toml" ]; then
    _DAEMON_PYPROJECT_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
elif [ -f "$PROJECT_ROOT/pyproject.toml" ] && [ -f "$PROJECT_ROOT/scripts/upgrade.sh" ]; then
    _DAEMON_PYPROJECT_DIR="$PROJECT_ROOT"
fi
find_compatible_python "$_DAEMON_PYPROJECT_DIR"

# Step 3: Determine daemon directory and mode
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
SELF_INSTALL="false"
if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ] && [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
    SELF_INSTALL=$("$HOOKS_DAEMON_PYTHON" -c "
import yaml
try:
    with open('$PROJECT_ROOT/.claude/hooks-daemon.yaml') as f:
        c = yaml.safe_load(f) or {}
    print('true' if c.get('daemon', {}).get('self_install_mode', False) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
    if [ "$SELF_INSTALL" = "true" ]; then
        DAEMON_DIR="$PROJECT_ROOT"
    fi
fi

[ -d "$DAEMON_DIR/.git" ] || _fail "Daemon directory is not a git repository: $DAEMON_DIR"
_ok "Daemon directory: $DAEMON_DIR"

# Step 3b: Capture FROM_VERSION before checkout overwrites pyproject.toml.
# Plan 00109 Phase 1.3: emit UPGRADE_METADATA after Layer 2 returns. The
# from_version field is the version we are upgrading FROM, so it must be read
# from the daemon's current pyproject.toml BEFORE Step 6 checks out a new tag.
FROM_VERSION=""
if [ -f "$DAEMON_DIR/pyproject.toml" ]; then
    FROM_VERSION="$(awk -F'"' '/^version[[:space:]]*=/ {print $2; exit}' "$DAEMON_DIR/pyproject.toml")"
    if [ -n "$FROM_VERSION" ] && [[ ! "$FROM_VERSION" =~ ^v ]]; then
        FROM_VERSION="v$FROM_VERSION"
    fi
fi

# Step 4: Best-effort daemon stop (before checkout)
# Plan 00100 Task 2.5: PID-kill only. The previous implementation resolved a
# venv python just to invoke `daemon.cli stop`, reintroducing the very
# precedence logic the Phase 2 SSOT consolidated. Bootstrap now reads PID
# files directly so zero venv / Python resolution is needed here.
#
# Contract (pinned by tests/integration/test_upgrade_sh_stop_bootstrap.py):
#   - SIGTERM every PID listed in $DAEMON_DIR/untracked/daemon-*.pid
#   - Skip missing/empty/non-numeric/stale PID files silently
#   - Skip missing untracked/ directory silently
#   - Never invoke python, python3, or daemon.cli
_stop_running_daemons() {
    local daemon_dir="$1"
    local untracked="$daemon_dir/untracked"
    [ -d "$untracked" ] || return 0

    local pid_file pid_raw pid
    local any_killed=0
    for pid_file in "$untracked"/daemon-*.pid; do
        [ -f "$pid_file" ] || continue
        if ! pid_raw=$(tr -d '[:space:]' < "$pid_file" 2> /dev/null); then
            continue
        fi
        pid="$pid_raw"
        # Require a pure positive integer; skip empty / garbage / stale.
        case "$pid" in
            '' | *[!0-9]*) continue ;;
        esac
        if kill -0 "$pid" 2> /dev/null; then
            if kill -TERM "$pid" 2> /dev/null; then
                any_killed=1
            fi
        fi
    done
    # Give terminated daemons a moment to shut sockets before checkout runs.
    [ "$any_killed" -eq 1 ] && sleep 1
    return 0
}

_info "Stopping daemon (best-effort, PID-only)..."
_stop_running_daemons "$DAEMON_DIR"

# Step 5: Fetch tags and determine target version
_info "Fetching latest tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

if [ -z "$TARGET_VERSION" ]; then
    TARGET_VERSION=$(git -C "$DAEMON_DIR" describe --tags \
        "$(git -C "$DAEMON_DIR" rev-list --tags --max-count=1)" 2>/dev/null || echo "")
    if [ -z "$TARGET_VERSION" ]; then
        _fail "No tags found. Specify a version explicitly."
    fi
fi

# Normalise version: prepend 'v' if missing
if [[ -n "$TARGET_VERSION" && ! "$TARGET_VERSION" =~ ^v ]]; then
    TARGET_VERSION="v${TARGET_VERSION}"
fi

git -C "$DAEMON_DIR" rev-parse "$TARGET_VERSION" &>/dev/null || \
    _fail "Version $TARGET_VERSION not found"
_ok "Target version: $TARGET_VERSION"

# Plan 00109 Phase 2.3: clean up stray untracked uv.lock before checkout.
# Migrated from the old skill upgrade.sh (Plan 00104 Issue #3 fix). The
# upstream copy is git-aware: only removes uv.lock when it is UNTRACKED in
# $DAEMON_DIR. In self-install mode uv.lock is tracked and must be left
# alone (the new tag's checkout will overwrite it cleanly). In a client
# install a prior `uv sync` may have left an untracked uv.lock that
# would otherwise block `git checkout` with
# "untracked working tree files would be overwritten by checkout".
if [ -f "$DAEMON_DIR/uv.lock" ]; then
    if ! git -C "$DAEMON_DIR" ls-files --error-unmatch uv.lock > /dev/null 2> /dev/null; then
        rm -f "$DAEMON_DIR/uv.lock"
        _ok "Removed untracked uv.lock from $DAEMON_DIR (would block checkout)"
    fi
fi

# Step 6: Checkout target version FIRST (before looking for Layer 2)
_info "Checking out $TARGET_VERSION..."
git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet
_ok "Checked out $TARGET_VERSION"

# Step 7: Clean up nested install artifacts
# When daemon repo has .claude/ in git (self-install dogfooding), normal installs
# can end up with runtime artifacts at the wrong path:
#   .claude/hooks-daemon/.claude/hooks-daemon/untracked/ (socket, pid, log files)
# This is a nested install artifact, not a legitimate directory.
if [ "$SELF_INSTALL" != "true" ]; then
    NESTED_INSTALL="$DAEMON_DIR/.claude/hooks-daemon"
    if [ -d "$NESTED_INSTALL" ]; then
        _warn "Cleaning up nested install artifacts: $NESTED_INSTALL"
        rm -rf "$NESTED_INSTALL"
        _ok "Nested install artifacts removed"
    fi
fi

# Step 8: Delegate to Layer 2 (now available after checkout)
#
# Plan 00109 Phase 1.3: invoke Layer 2 as a child process (NOT exec), capture
# its exit code, and on success emit a sentinel-wrapped UPGRADE_METADATA
# block on stdout. The block is the contract between this script and the
# project agent that follows up with an atomic `hooks daemon upgrade` commit.
LAYER2_SCRIPT="$DAEMON_DIR/scripts/upgrade_version.sh"

if [ ! -f "$LAYER2_SCRIPT" ]; then
    _fail "Layer 2 upgrader not found at: $LAYER2_SCRIPT
Target version $TARGET_VERSION does not include the upgrade system.
Use a fresh install instead: see CLAUDE/LLM-INSTALL.md"
fi

_info "Delegating to version-specific upgrader..."
# Invoke Layer 2 inside an `if` so set -e does not abort on its (potentially
# nonzero) exit. Non-zero = abort without emitting metadata.
if ! bash "$LAYER2_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"; then
    LAYER2_EXIT=$?
    exit "$LAYER2_EXIT"
fi

# ------------------------------------------------------------
# Emit UPGRADE_METADATA (Plan 00109 Decision 2)
#
# Format: sentinel-wrapped key=value block on stdout. Every required field
# is present; values may be empty for modified_files and config_diff_summary
# on idempotent upgrades. Parsed by the project agent — see
# src/claude_code_hooks_daemon/skills/hooks-daemon/upgrade.md.
# ------------------------------------------------------------

# Resolve the daemon's venv python (fingerprint-keyed; first match wins).
_metadata_venv_python=""
for _candidate in "$DAEMON_DIR"/untracked/venv-py*/bin/python; do
    if [ -x "$_candidate" ]; then
        _metadata_venv_python="$_candidate"
        break
    fi
done

_metadata_python_version=""
_metadata_python_path=""
_metadata_venv_path=""
if [ -n "$_metadata_venv_python" ] && [ -x "$_metadata_venv_python" ]; then
    if _pv_out="$("$_metadata_venv_python" -c 'import sys; print(".".join(str(x) for x in sys.version_info[:3]))' 2>/dev/null)"; then
        _metadata_python_version="$_pv_out"
    fi
    _metadata_python_path="$_metadata_venv_python"
    _metadata_venv_path="$(dirname "$(dirname "$_metadata_venv_python")")"
fi

# Host: prefer $HOSTNAME (set by container runtimes and test fixtures), fall
# back to hostname(1) for bare-metal hosts that don't export it.
_metadata_host="${HOSTNAME:-}"
if [ -z "$_metadata_host" ]; then
    if _hn_out="$(hostname 2>/dev/null)"; then
        _metadata_host="$_hn_out"
    else
        _metadata_host="unknown"
    fi
fi

# modified_files: comma-separated relative paths in $PROJECT_ROOT that are
# currently dirty (vs HEAD). Informational — the project agent filters by
# daemon-owned prefixes before staging.
_metadata_modified_files=""
if [ -d "$PROJECT_ROOT/.git" ]; then
    if _status_out="$(cd "$PROJECT_ROOT" && git status --porcelain 2>/dev/null | awk '{print $NF}' | tr '\n' ',')"; then
        _metadata_modified_files="${_status_out%,}"
    fi
fi

# config_diff_summary: human-readable summary of hooks-daemon.yaml changes.
# Layer 2's installer writes hooks-daemon.yaml.backup before applying config
# migration. Absent backup = no config changes this run.
_metadata_config_summary="no config changes"
_metadata_config_file="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
_metadata_config_backup="$PROJECT_ROOT/.claude/hooks-daemon.yaml.backup"
if [ -f "$_metadata_config_backup" ] && [ -f "$_metadata_config_file" ]; then
    # Capture diff output via `if cmd=$(...); then`. diff returns 0 when
    # files are identical, 1 when they differ. awk counts diff markers and
    # always exits 0 (even with zero matches via END {print c+0}).
    if _diff_text="$(diff "$_metadata_config_backup" "$_metadata_config_file" 2>/dev/null)"; then
        : # files identical — keep "no config changes"
    else
        _diff_count="$(printf '%s\n' "$_diff_text" | awk '/^[<>]/ {c++} END {print c+0}')"
        _metadata_config_summary="${_diff_count} lines changed"
    fi
fi

# Emit the sentinel-wrapped block. Leading newline ensures the open sentinel
# starts on its own line even if Layer 2's last output had no trailing \n.
printf '\n<<<UPGRADE_METADATA\n'
printf 'from_version=%s\n' "$FROM_VERSION"
printf 'to_version=%s\n' "$TARGET_VERSION"
printf 'python_version=%s\n' "$_metadata_python_version"
printf 'python_path=%s\n' "$_metadata_python_path"
printf 'venv_path=%s\n' "$_metadata_venv_path"
printf 'host=%s\n' "$_metadata_host"
printf 'daemon_dir=%s\n' "$DAEMON_DIR"
printf 'project_root=%s\n' "$PROJECT_ROOT"
printf 'modified_files=%s\n' "$_metadata_modified_files"
printf 'config_diff_summary=%s\n' "$_metadata_config_summary"
printf 'UPGRADE_METADATA>>>\n'

exit 0
