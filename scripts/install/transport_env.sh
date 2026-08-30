#!/bin/bash
#
# transport_env.sh - Thread Plan 00290 transport-probe facts into hooks-daemon.env
#
# hooks-daemon.env is written once at Step 6 of install_version.sh, before
# Step 7 (config deploy) has run — so for a genuine fresh install the probe
# below resolves the pure defaults (both rungs off) and appends nothing,
# which is the byte-identical-by-default contract every other Plan 00290
# installer step honours. The function exists so the SAME write step can
# ALSO carry probe-derived lines whenever a `daemon.transport` config is
# already resolvable at this point (e.g. a repair/idempotent re-run over an
# existing config) — DESIGN-socket-relay.md §6.3 names
# HOOKS_DAEMON_NC_UNIX_CAPABLE as the one runtime fact init.sh actually reads.
#
# Usage:
#   source "$(dirname "$0")/install/transport_env.sh"
#   append_transport_probe_env_lines "$PROJECT_ROOT" "$ENV_FILE" "$VENV_PYTHON"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# append_transport_probe_env_lines() - Append probe-derived env lines, if any
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - env_file: Path to the already-written hooks-daemon.env
#   $3 - venv_python: Path to the daemon's venv Python (may be empty/unset —
#        an early-stage caller that has not resolved a venv yet)
#
# Returns:
#   Exit code 0 always (advisory only) — this step must never abort an
#   install/upgrade; a hooks-daemon.env without these lines still works
#   correctly via the permanent bash+python3 rung.
#
append_transport_probe_env_lines() {
    local project_root="$1"
    local env_file="$2"
    local venv_python="${3:-}"

    if [ -z "$venv_python" ] || [ ! -x "$venv_python" ]; then
        print_verbose "No venv Python available — skipping transport-probe env lines"
        return 0
    fi

    local probe_lines
    if ! probe_lines="$("$venv_python" - "$project_root" <<'TRANSPORT_ENV_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config
from claude_code_hooks_daemon.install.relay_deploy import resolve_relay_binary_path
from claude_code_hooks_daemon.install.transport_probe import probe_transport, render_env_lines

project_root = Path(sys.argv[1])
transport = load_transport_config(project_root)
if not (transport.relay_enabled or transport.nc_enabled):
    sys.exit(0)

relay_binary = resolve_relay_binary_path(project_root, transport)
result = probe_transport(project_root=project_root, relay_binary=relay_binary)
for line in render_env_lines(
    result, relay_enabled=transport.relay_enabled, nc_enabled=transport.nc_enabled
):
    print(line)
TRANSPORT_ENV_PY
    )"; then
        print_verbose "Transport probe failed while building hooks-daemon.env lines (non-fatal)"
        return 0
    fi

    if [ -z "$probe_lines" ]; then
        return 0
    fi

    {
        echo ""
        echo "# --- Plan 00290 transport-probe facts (regenerate: bin/hooks-daemon transport-probe) ---"
        echo "$probe_lines"
    } >> "$env_file"
    print_verbose "Appended transport-probe facts to $env_file"
    return 0
}
