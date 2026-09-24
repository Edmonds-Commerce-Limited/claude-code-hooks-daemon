#!/bin/bash
#
# DAEMON-OWNED FILE - do not edit. Deployed into your project by the
# claude-code-hooks-daemon installer and refreshed on every upgrade, so local
# changes are discarded. See the daemon clone's CLAUDE/LLM-INSTALL.md,
# "Which Files Under .claude/ Are Yours?", for the full list and the
# linter exclusions.
#
# install.sh - Install hooks daemon into current project
#
# Usage:
#   ./install.sh [--force]
#
# Arguments:
#   --force (optional): Force reinstall over existing installation
#

set -euo pipefail

GITHUB_ORG="Edmonds-Commerce-Limited"
GITHUB_REPO="claude-code-hooks-daemon"
INSTALL_URL="https://raw.githubusercontent.com/${GITHUB_ORG}/${GITHUB_REPO}/main/install.sh"
# Plan 00100 Task 0.3: daemon's requires-python is the single source of truth
# for minimum Python. Fetched from the repo's pyproject.toml below and used
# to pre-check the active python3 BEFORE the installer runs.
PYPROJECT_URL="https://raw.githubusercontent.com/${GITHUB_ORG}/${GITHUB_REPO}/main/pyproject.toml"
# Plan 00110 Task 4.3: canonical glob-and-sort interpreter discovery helper.
# Fetched alongside pyproject.toml so the skill bootstrap can pick the latest
# compatible python3.NN on $PATH — no hardcoded version list, no host-a
# "suggests python3.11 even though python3.13/3.14 are installed" trap.
PYTHON_DISCOVERY_URL="https://raw.githubusercontent.com/${GITHUB_ORG}/${GITHUB_REPO}/main/scripts/lib/python_discovery.sh"

# Detect project root by searching upward for .claude/
PROJECT_ROOT="$(pwd)"
while [ "$PROJECT_ROOT" != "/" ]; do
    if [ -d "$PROJECT_ROOT/.claude" ]; then
        break
    fi
    PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done

if [ ! -d "$PROJECT_ROOT/.claude" ]; then
    echo "Error: Not in a Claude Code project (no .claude/ directory found)"
    echo ""
    echo "The hooks daemon must be installed in a project that has Claude Code configured."
    echo "Ensure you are in a project directory with a .claude/ folder."
    exit 1
fi

DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
FORCE_FLAG="${1:-}"

echo "Claude Code Hooks Daemon - Install"
echo ""
echo "Project: $PROJECT_ROOT"
echo ""

# Plan 00100 Task 0.3 + Plan 00110 Task 4.3: Python pre-check BEFORE download.
# Fetch two artifacts from main: (1) pyproject.toml for requires-python (the
# floor), (2) scripts/lib/python_discovery.sh — the canonical glob-and-sort
# interpreter discovery helper. The helper walks $PATH for python3.NN, picks
# the latest meeting the floor, and on failure emits a diagnostic naming
# interpreters ACTUALLY observed on this host (never a hardcoded suggestion
# that may not exist — the host-a trap that Plan 00110 closes).
PYPROJECT_TMP="/tmp/hooks-daemon-precheck-pyproject.toml.$$"
DISCOVERY_TMP="/tmp/hooks-daemon-precheck-python-discovery.sh.$$"

# Plan 00456 (GitHub issue #53): an explicit --force reinstall deletes the whole
# daemon directory, and every environment's venv lives inside it — a host view
# and a container view of one bind-mounted project share the clone but each
# has its own untracked/venv-*. So before the installer runs, every venv-* is
# moved aside (same filesystem, so a rename: byte-for-byte, symlinks and all)
# and afterwards moved back to the SAME path, which its absolute paths need.
# A name the fresh install rebuilt is this environment's own venv: the new
# one wins. Restoring runs from the EXIT trap, so a failed install restores too.
KEPT_VENVS_DIR=""

_keep_venvs_aside() {
    local daemon_dir="$1" venv
    for venv in "$daemon_dir"/untracked/venv-*; do
        [ -d "$venv" ] || continue
        if [ -z "$KEPT_VENVS_DIR" ]; then
            KEPT_VENVS_DIR="$(mktemp -d "$PROJECT_ROOT/.claude/.hooks-daemon-venvs.XXXXXX")"
            echo "Keeping every environment's venv aside in $KEPT_VENVS_DIR during the reinstall:"
        fi
        mv "$venv" "$KEPT_VENVS_DIR/"
        echo "  kept: ${venv##*/}"
    done
}

_restore_venvs() {
    [ -n "$KEPT_VENVS_DIR" ] || return 0
    local target="$DAEMON_DIR/untracked" venv name
    mkdir -p "$target"
    echo "Restoring the kept venvs into $target:"
    for venv in "$KEPT_VENVS_DIR"/venv-*; do
        [ -d "$venv" ] || continue
        name="${venv##*/}"
        if [ -e "$target/$name" ]; then
            echo "  $name: rebuilt by this install for this environment; its old copy is discarded"
            rm -rf "$venv"
        else
            mv "$venv" "$target/"
            echo "  restored: $name"
        fi
    done
    # rmdir, never rm -rf: anything still in here is a venv that did not move
    # back, and it must be kept for a human rather than deleted.
    if ! rmdir "$KEPT_VENVS_DIR"; then
        echo "WARNING: $KEPT_VENVS_DIR is not empty; what is left in it was kept for you to inspect." >&2
        KEPT_VENVS_DIR=""
        return 1
    fi
    KEPT_VENVS_DIR=""
}

_on_exit() {
    _restore_venvs
    rm -f "$PYPROJECT_TMP" "$DISCOVERY_TMP"
}
trap _on_exit EXIT

if ! curl -sSL "$PYPROJECT_URL" -o "$PYPROJECT_TMP" || [ ! -s "$PYPROJECT_TMP" ]; then
    echo "Error: Failed to fetch pyproject.toml from $PYPROJECT_URL"
    echo "Check your network connection and try again."
    exit 1
fi
if ! curl -sSL "$PYTHON_DISCOVERY_URL" -o "$DISCOVERY_TMP" || [ ! -s "$DISCOVERY_TMP" ]; then
    echo "Error: Failed to fetch python_discovery.sh from $PYTHON_DISCOVERY_URL"
    echo "Check your network connection and try again."
    exit 1
fi

MIN_PY="$(grep -E '^requires-python[[:space:]]*=' "$PYPROJECT_TMP" | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"
if [ -z "$MIN_PY" ]; then
    echo "Error: Could not parse requires-python from pyproject.toml"
    exit 1
fi

# shellcheck source=/dev/null
. "$DISCOVERY_TMP"
if ! FOUND_PY="$(find_latest_python "$MIN_PY" "$PYPROJECT_TMP")"; then
    # Helper already wrote a remediation hint to stderr enumerating every
    # interpreter observed during the glob. Add a one-line summary line and
    # exit — no second guessing of the helper's diagnostic.
    echo ""
    echo "Aborting install: no compatible Python (>=$MIN_PY) found on \$PATH."
    exit 1
fi

# Export so the inner installer (downloaded below) reuses the discovered
# interpreter without re-running discovery on its own. The downstream
# scripts/install/prerequisites.sh also honours HOOKS_DAEMON_PYTHON via
# the same helper (Plan 00110 Task 4.2).
export HOOKS_DAEMON_PYTHON="$FOUND_PY"
echo "Using Python: $FOUND_PY"
echo ""

# Plan 00122 BUG 3: an install counts as "already installed" only if it is
# HEALTHY — a venv python exists AND the daemon package imports. A bare
# directory check treated a broken/partial install (dir present, no working
# venv) as complete, so the documented `/hooks-daemon install` could not repair
# it (only `--force` could, which re-clones from scratch). Returns 0 when
# healthy, non-zero otherwise. Probe output goes to a temp file (never
# /dev/null) so failures stay inspectable.
_installation_is_healthy() {
    local dir="$1"
    local py probe_out
    probe_out="$(mktemp)"
    # canonical-resolver-exempt: this is the skill bootstrap, which runs
    # standalone in a client project BEFORE the daemon source tree (and
    # scripts/lib/resolve_venv.sh) exists. This is a lightweight health probe,
    # not venv resolution for use, so it globs directly.
    # Probes BOTH layouts on purpose: the retired pre-v3.7.0 path is listed so
    # an old-but-working install is detected as healthy (and so left alone)
    # rather than silently re-cloned over.
    for py in "$dir"/untracked/venv-*/bin/python "$dir"/untracked/venv/bin/python; do  # python-var-guidance-exempt: deliberate dual-layout probe
        if [ -x "$py" ] && "$py" -c "import claude_code_hooks_daemon" > "$probe_out" 2> "$probe_out"; then
            rm -f "$probe_out"
            return 0
        fi
    done
    rm -f "$probe_out"
    return 1
}

# _trusted_clone_version() - The clone's version, when the clone is whole enough
# to repair itself: the same real-clone marker init.sh uses
# (scripts/lib/resolve_venv.sh), the wrapper that runs the repair, and a
# version.py that reads. Echoes the version; returns 1 otherwise.
_trusted_clone_version() {
    local dir="$1" version
    local version_file="$dir/src/claude_code_hooks_daemon/version.py"
    [ -f "$dir/scripts/lib/resolve_venv.sh" ] || return 1
    [ -f "$dir/bin/hooks-daemon" ] || return 1
    [ -f "$version_file" ] || return 1
    version="$(awk -F'"' '/^__version__[[:space:]]*=/ { print $2; exit }' "$version_file")"
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
    echo "$version"
}

# _holds_nothing_to_keep() - Is dir only the runtime shell hooks create?
#
# init.sh runs `mkdir -p .claude/hooks-daemon/untracked` on every hook, so a
# checkout that never had a clone still has this directory. Nothing but that
# untracked/ may be present, and no venv inside it.
_holds_nothing_to_keep() {
    local dir="$1" entry
    for entry in "$dir"/* "$dir"/.[!.]* "$dir"/..?*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        [ "$entry" = "$dir/untracked" ] && continue
        return 1
    done
    for entry in "$dir"/untracked/venv*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        return 1
    done
    return 0
}

# Check if already installed.
#
# Plan 00456 (GitHub issue #53): this script NEVER escalates to --force on its
# own. It used to, whenever the health probe failed, and the force path's
# rm -rf took every other environment's venv with the clone. In the #53 state
# (one clone, two views of a bind-mounted project) the probe cannot pass, so
# each view deleted the other's venv on every switch. Now:
#   - healthy                       -> nothing to do
#   - only the hooks' runtime shell -> nothing to keep: removed, fresh install
#   - a whole clone                 -> its own `bin/hooks-daemon repair` builds
#                                      THIS path's venv in place, then re-probe
#   - anything else                 -> stop, change nothing, explain
if [ -d "$DAEMON_DIR" ] && [ "$FORCE_FLAG" != "--force" ]; then
    if _installation_is_healthy "$DAEMON_DIR"; then
        echo "Daemon is already installed at: $DAEMON_DIR"
        echo ""
        echo "To upgrade to a new version:"
        echo "  /hooks-daemon upgrade"
        echo ""
        echo "To force reinstall:"
        echo "  /hooks-daemon install --force"
        exit 0
    fi
    if _holds_nothing_to_keep "$DAEMON_DIR"; then
        echo "$DAEMON_DIR holds only the runtime directory hooks create (no clone, no venv)."
        echo "Removing it and installing fresh."
        echo ""
        rm -rf "$DAEMON_DIR"
    elif CLONE_VERSION="$(_trusted_clone_version "$DAEMON_DIR")"; then
        echo "The daemon clone (v$CLONE_VERSION) is present at $DAEMON_DIR, but no working"
        echo "venv serves this project path. Repairing it IN PLACE: only this path's venv is"
        echo "built, and nothing is deleted."
        echo ""
        if bash "$DAEMON_DIR/bin/hooks-daemon" repair && _installation_is_healthy "$DAEMON_DIR"; then
            echo ""
            echo "Repaired. The next hook starts the daemon (restart your Claude session if hooks stay inactive)."
            exit 0
        fi
        echo ""
        echo "The in-place repair did not leave a working venv for this project path (its output is above)."
        echo "Nothing was deleted. Next steps, in order:"
        echo "  1. Fix what the repair reported, then run: $DAEMON_DIR/bin/hooks-daemon repair"
        echo "  2. Or run the same-version upgrade: /hooks-daemon upgrade $CLONE_VERSION"
        echo "  3. Only if both fail: /hooks-daemon install --force"
        echo "     (re-clones the daemon; every venv-* under untracked/ is kept and restored)"
        exit 1
    else
        echo "The daemon directory exists at $DAEMON_DIR, but it is not a complete clone"
        echo "(scripts/lib/resolve_venv.sh, bin/hooks-daemon or a readable version.py is missing),"
        echo "and it holds files this script will not delete on its own. Nothing was changed."
        echo "Ask a human to inspect it. To reinstall over it deliberately:"
        echo "  /hooks-daemon install --force   (every venv-* under untracked/ is kept and restored)"
        exit 1
    fi
fi

# Download installer to temp file (never pipe curl to shell — we block that pattern)
INSTALLER="/tmp/hooks-daemon-install.sh"
echo "Downloading installer..."
echo "  URL: $INSTALL_URL"
curl -sSL "$INSTALL_URL" -o "$INSTALLER"

if [ ! -s "$INSTALLER" ]; then
    echo ""
    echo "Error: Failed to download installer (empty file)"
    echo "Check your network connection and try again."
    exit 1
fi

INSTALLER_SIZE=$(wc -c < "$INSTALLER")
echo "  Downloaded: ${INSTALLER_SIZE} bytes"
echo ""

# Run installer from project root
echo "Running installer..."
echo ""
cd "$PROJECT_ROOT"

if [ "$FORCE_FLAG" = "--force" ]; then
    if [ -d "$DAEMON_DIR" ]; then
        _keep_venvs_aside "$DAEMON_DIR"
    fi
    FORCE=true bash "$INSTALLER"
else
    bash "$INSTALLER"
fi
