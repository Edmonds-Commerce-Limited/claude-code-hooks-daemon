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
# _is_python_at_least_311() - Verify a Python interpreter is 3.11 or newer
#
# Plan 00103 Decision 3 Rule B: parses ``--version`` output rather than
# trusting the command name (because ``python3`` on RHEL/CentOS is 3.9 and
# on a Debian image may be anything from 3.7 to 3.13). Asserts MAJOR == 3
# AND MINOR >= 11, OR MAJOR > 3 (covers a hypothetical Python 4).
#
# Args:
#   $1 - cmd: Path or name of Python interpreter to probe
#
# Returns:
#   0 - cmd is executable AND reports Python 3.11+
#   1 - cmd missing, non-executable, or reports Python <3.11
#
# (Plan 00104 will move this helper into a shared library; currently
# duplicated between scripts/upgrade.sh and scripts/install/prerequisites.sh
# per the Decision 3 acceptance plan.)
#
_is_python_at_least_311() {
    local cmd="$1"
    [ -n "$cmd" ] || return 1
    if ! command -v "$cmd" > /dev/null; then
        return 1
    fi
    local version_output=""
    version_output="$("$cmd" --version 2>&1)" || return 1
    if [[ "$version_output" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
        local major="${BASH_REMATCH[1]}"
        local minor="${BASH_REMATCH[2]}"
        if [ "$major" -gt 3 ]; then
            return 0
        fi
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
            return 0
        fi
    fi
    return 1
}

#
# find_compatible_python() - Find a Python 3.11+ interpreter
#
# Plan 00103 Decision 3 Rule B (probe-list ban):
#   - Bare ``python3`` is INTENTIONALLY excluded from the candidate list.
#     Bare ``python3`` is a "diceroll" on the user's PATH (RHEL/CentOS-default
#     ``python3`` is 3.9, container images vary, etc). Probing it first means
#     the daemon gets bootstrapped against the wrong interpreter and fails
#     deep in the call stack with confusing errors. The probe must only use
#     versioned commands (``python3.11`` and up).
#   - ``compgen -c python3.`` enumerates PATH for any ``python3.NN`` so future
#     versions like 3.14 / 3.15 are picked up automatically without requiring
#     a daemon update.
#   - ``HOOKS_DAEMON_PYTHON`` is honoured as an explicit *input* override
#     (validated against the 3.11 minimum). An invalid override fails fast —
#     never silently falls back to PATH probing because that masks the user's
#     misconfiguration.
#
# Sets and exports HOOKS_DAEMON_PYTHON so Layer 2 scripts can use it.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (exits via _fail)
#
find_compatible_python() {
    # Plan 00104 Phase 7 Task 7.2: optional <daemon_dir> positional arg.
    # When provided AND its pyproject.toml carries a parseable
    # requires-python lower bound, every candidate's --version is
    # cross-checked against that bound. Without the cross-check, a 3.11
    # interpreter satisfies the hardcoded 3.11 floor and the daemon
    # explodes deep in the call stack on a 3.13-only language feature.
    local daemon_dir="${1:-}"

    # Parse pyproject's [project] requires-python lower bound. Inlined
    # rather than extracted to a helper because the integration test in
    # tests/integration/test_bootstrap_requires_python_cross_check.py
    # extracts only this function and _is_python_at_least_311 — adding a
    # new helper would silently break the extraction. Supports the
    # forms users actually write: ``>=3.13``, ``~=3.13`` (with optional
    # whitespace, with or without trailing upper bound).
    local _rp_min_major="" _rp_min_minor="" _rp_constraint=""
    if [ -n "$daemon_dir" ] && [ -f "$daemon_dir/pyproject.toml" ]; then
        local _rp_line _rp_value=""
        while IFS= read -r _rp_line; do
            if [[ "$_rp_line" =~ ^[[:space:]]*requires-python[[:space:]]*=[[:space:]]*[\"\']([^\"\']+)[\"\'] ]]; then
                _rp_value="${BASH_REMATCH[1]}"
                break
            fi
        done < "$daemon_dir/pyproject.toml"
        if [ -n "$_rp_value" ] && [[ "$_rp_value" =~ (\>=|~=)[[:space:]]*([0-9]+)\.([0-9]+) ]]; then
            _rp_min_major="${BASH_REMATCH[2]}"
            _rp_min_minor="${BASH_REMATCH[3]}"
            _rp_constraint="$_rp_value"
        fi
    fi

    # Step 1: explicit override wins (validated, no fallback on failure).
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        if _is_python_at_least_311 "$HOOKS_DAEMON_PYTHON"; then
            local _ovr_ok=1
            if [ -n "$_rp_min_major" ]; then
                local _ovr_ver _ovr_maj _ovr_min
                _ovr_ver="$("$HOOKS_DAEMON_PYTHON" --version 2>&1)" || _ovr_ver=""
                if [[ "$_ovr_ver" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
                    _ovr_maj="${BASH_REMATCH[1]}"
                    _ovr_min="${BASH_REMATCH[2]}"
                    if [ "$_ovr_maj" -lt "$_rp_min_major" ] \
                        || { [ "$_ovr_maj" -eq "$_rp_min_major" ] \
                             && [ "$_ovr_min" -lt "$_rp_min_minor" ]; }; then
                        _ovr_ok=0
                    fi
                fi
            fi
            if [ "$_ovr_ok" -eq 1 ]; then
                export HOOKS_DAEMON_PYTHON
                _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
                return 0
            fi
            _fail "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON satisfies the hardcoded 3.11 floor but violates pyproject.toml requires-python = \"$_rp_constraint\".

Point HOOKS_DAEMON_PYTHON at a Python ${_rp_min_major}.${_rp_min_minor}+ interpreter (or unset it to let the installer probe PATH for one)."
        fi
        _fail "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON is not a usable Python 3.11+ interpreter.

Refusing to fall back to PATH probing — that would silently mask your broken override.

Either:
  - Unset HOOKS_DAEMON_PYTHON and let the installer probe PATH, or
  - Point HOOKS_DAEMON_PYTHON at an absolute path to a Python 3.11 or newer interpreter."
    fi

    # Step 2: build candidate list (versioned only) + open-ended discovery.
    local candidates=("python3.13" "python3.12" "python3.11")
    local discovered=""
    discovered="$(compgen -c "python3." 2> /dev/null)" || discovered=""
    if [ -n "$discovered" ]; then
        local cmd
        while IFS= read -r cmd; do
            [[ "$cmd" =~ ^python3\.[0-9]+$ ]] || continue
            local already=0
            local existing
            for existing in "${candidates[@]}"; do
                if [ "$existing" = "$cmd" ]; then
                    already=1
                    break
                fi
            done
            if [ "$already" -eq 0 ]; then
                candidates+=("$cmd")
            fi
        done <<< "$discovered"
    fi

    # Step 3: probe candidates in order; first 3.11+ AND requires-python match wins.
    local candidate
    for candidate in "${candidates[@]}"; do
        if _is_python_at_least_311 "$candidate"; then
            local _accept=1
            if [ -n "$_rp_min_major" ]; then
                local _cand_ver _cand_maj _cand_min
                _cand_ver="$("$candidate" --version 2>&1)" || _cand_ver=""
                if [[ "$_cand_ver" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
                    _cand_maj="${BASH_REMATCH[1]}"
                    _cand_min="${BASH_REMATCH[2]}"
                    if [ "$_cand_maj" -lt "$_rp_min_major" ] \
                        || { [ "$_cand_maj" -eq "$_rp_min_major" ] \
                             && [ "$_cand_min" -lt "$_rp_min_minor" ]; }; then
                        _accept=0
                    fi
                fi
            fi
            if [ "$_accept" -eq 1 ]; then
                HOOKS_DAEMON_PYTHON="$(command -v "$candidate")"
                export HOOKS_DAEMON_PYTHON
                _ok "Compatible Python found: $HOOKS_DAEMON_PYTHON ($("$HOOKS_DAEMON_PYTHON" --version 2>&1))"
                return 0
            fi
        fi
    done

    if [ -n "$_rp_min_major" ]; then
        _fail "No Python interpreter satisfying requires-python = \"$_rp_constraint\" found.

Searched (versioned commands only): ${candidates[*]}
Every candidate clears the hardcoded 3.11 floor, but none meets the requires-python lower bound of ${_rp_min_major}.${_rp_min_minor}.

Install Python ${_rp_min_major}.${_rp_min_minor} or newer, or set HOOKS_DAEMON_PYTHON explicitly to an interpreter that satisfies the constraint."
    fi

    _fail "No compatible Python (3.11+) found.

Searched (versioned commands only — bare ``python3`` is intentionally not probed
because it is unreliable across distros): ${candidates[*]}

Please install Python 3.11 or higher:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11
  Arch: sudo pacman -S python

Or set HOOKS_DAEMON_PYTHON to the absolute path of a 3.11+ interpreter:
  HOOKS_DAEMON_PYTHON=/usr/bin/python3.12 ./upgrade.sh ..."
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
