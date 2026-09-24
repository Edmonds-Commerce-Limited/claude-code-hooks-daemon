#!/bin/bash
#
# mode_guard.sh - Install/Upgrade mode validation and guards
#
# CRITICAL: Install and upgrade scripts must NEVER operate in self-install mode.
# This module provides guards to detect and abort if self-install mode is detected.
#
# Usage:
#   source "$(dirname "$0")/install/mode_guard.sh"
#   ensure_normal_mode_only  # Aborts script if in self-install mode
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# _is_real_daemon_clone() - Is a candidate directory a REAL daemon clone?
#
# The discriminator detect_self_install_mode needs for its third indicator:
# NOT merely "does .claude/hooks-daemon/ exist", because the self-install
# daemon generates a bare bin/hooks-daemon symlink under its own
# .claude/hooks-daemon/ so external tools find the CLI at the conventional
# path (Plan 00455) -- and that link-only directory is not a client
# installation. A real clone has its own pyproject.toml; the generated
# marker never does. Mirrors the Python-side discriminator
# (project_root_is_daemon_repo in daemon/validation.py) so both languages
# agree on what counts as "installed here".
#
# Args:
#   $1 - candidate: Path to check (typically <project_root>/.claude/hooks-daemon)
#
# Returns:
#   Exit code 0 if a real clone is present, 1 otherwise
#
_is_real_daemon_clone() {
    local candidate="$1"

    [ -f "$candidate/pyproject.toml" ]
}

#
# detect_self_install_mode() - Detect if running in self-install mode
#
# Self-install mode indicators:
# - src/claude_code_hooks_daemon exists at project root
# - pyproject.toml exists at project root with daemon package name
# - .claude/hooks-daemon/ is not a REAL daemon clone (see _is_real_daemon_clone)
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 if self-install mode, 1 if normal mode
#
detect_self_install_mode() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        return 1
    fi

    # Check for self-install indicators
    if [ -d "$project_root/src/claude_code_hooks_daemon" ] && \
       [ -f "$project_root/pyproject.toml" ] && \
       ! _is_real_daemon_clone "$project_root/.claude/hooks-daemon"; then
        return 0  # Self-install mode detected
    fi

    return 1  # Normal mode
}

#
# ensure_normal_mode_only() - Abort if self-install mode detected
#
# CRITICAL: This function must be called at the start of install.sh and upgrade.sh
# to prevent any operations in self-install mode.
#
# Args:
#   $1 - project_root (optional): Path to validate. Both callers
#        (install_version.sh, upgrade_version.sh) pass one explicitly; when
#        omitted, falls back to the PROJECT_ROOT env var, then cwd -- the
#        pre-Plan-00455 behaviour, kept for any other caller relying on it.
#        Previously this parameter was accepted but silently ignored in
#        favour of the global alone; both current callers already set
#        PROJECT_ROOT to the same value they pass, so this was not
#        observably wrong, but the dead parameter invited exactly the drift
#        it now prevents.
#
# Returns:
#   Exit code 0 if normal mode (safe to proceed)
#   ABORTS SCRIPT if self-install mode detected
#
ensure_normal_mode_only() {
    local project_root="${1:-${PROJECT_ROOT:-$(pwd)}}"

    if detect_self_install_mode "$project_root"; then
        cat >&2 <<'EOF'

========================================
CRITICAL ERROR: SELF-INSTALL MODE DETECTED
========================================

Install and upgrade scripts are ONLY for normal mode installations
where the daemon is installed in .claude/hooks-daemon/.

This appears to be the daemon's development repository (self-install mode).
The daemon is already "installed" as the repository itself.

WHAT YOU PROBABLY WANT TO DO:
- To update code: git pull
- To restart daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
- To test install: Create a dummy project in /tmp and install there

DO NOT run install/upgrade scripts in the daemon repository.

========================================
EOF
        exit 1
    fi

    return 0
}

#
# require_normal_mode() - Alternative name for ensure_normal_mode_only
#
# Alias for clarity in different contexts.
#
require_normal_mode() {
    ensure_normal_mode_only "$@"
}

#
# get_install_mode() - Determine install mode (for informational purposes)
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Prints "self-install" or "normal" to stdout
#
get_install_mode() {
    local project_root="$1"

    if detect_self_install_mode "$project_root"; then
        echo "self-install"
    else
        echo "normal"
    fi
}
