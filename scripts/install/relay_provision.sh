#!/bin/bash
#
# relay_provision.sh - Put the relay binary in place at install/upgrade (Plan 00529)
#
# One shared step for install_version.sh (Step 7b) and upgrade_version.sh (the
# idempotent fast path and Step 14c). It runs the relay_deploy CLI, which reads
# daemon.transport from the project config:
#
#   exit 0  relay disabled (nothing done) or binary provisioned
#   exit 3  relay enabled but NOT provisioned; a banner on stdout names the
#           binary path, every reason and the fix
#   other   the CLI itself failed; treated as not provisioned
#
# A failure WARNS and never aborts the install/upgrade: the relay is a
# performance path, and the forwarder's bash transport still enforces every
# rule (Plan 00529 Task 2 report, section 3). To keep the warning impossible to
# miss, the banner is kept in RELAY_PROVISION_BANNER and the caller prints it
# again with report_relay_provision_failure just before its final exit.
#
# After provisioning, the forwarders are regenerated for the transport config:
# on a fresh install they were deployed before the config existed, and on an
# upgrade the config merge that may enable the relay runs after the hooks
# were deployed.
#
# Usage:
#   source "$INSTALL_LIB_DIR/relay_provision.sh"
#   provision_relay_binary "$VENV_PYTHON" "$DAEMON_DIR" "$PROJECT_ROOT" "$VERSION_TAG"
#   ...
#   report_relay_provision_failure
#   exit 0
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    # shellcheck source=output.sh
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Ensure regenerate_forwarders_for_transport is available
if ! declare -F regenerate_forwarders_for_transport > /dev/null; then
    # shellcheck source=hooks_deploy.sh
    source "$(dirname "${BASH_SOURCE[0]}")/hooks_deploy.sh"
fi

#: Exit code of the relay_deploy CLI for "relay enabled but not provisioned".
#: Mirrors RELAY_PROVISION_FAILED_EXIT_CODE in install/relay_deploy.py.
RELAY_PROVISION_FAILED_EXIT_CODE=3

#: 1 once a provisioning attempt in this run has failed, else 0.
RELAY_PROVISION_FAILED=0
#: The failure text to repeat at the end of the run.
RELAY_PROVISION_BANNER=""

#
# provision_relay_binary() - Provision the relay binary, then regenerate forwarders
#
# Args:
#   $1 - venv_python: Path to the daemon's venv Python
#   $2 - daemon_dir: Path to the daemon installation directory
#   $3 - project_root: Path to project root
#   $4 - version_tag: Release tag the downloaded asset must match (e.g. v3.71.0)
#
# Sets:
#   RELAY_PROVISION_FAILED, RELAY_PROVISION_BANNER
#
# Returns:
#   0 always; a failure is recorded in RELAY_PROVISION_FAILED and printed loudly.
#
provision_relay_binary() {
    local venv_python="$1"
    local daemon_dir="$2"
    local project_root="$3"
    local version_tag="$4"

    local output
    local rc=0
    output="$("$venv_python" -m claude_code_hooks_daemon.install.relay_deploy \
        --daemon-dir "$daemon_dir" \
        --project-root "$project_root" \
        --version-tag "$version_tag" 2>&1)" || rc=$?

    if [ "$rc" -eq 0 ]; then
        printf '%s\n' "$output"
        print_success "Relay binary step complete"
    elif [ "$rc" -eq "$RELAY_PROVISION_FAILED_EXIT_CODE" ]; then
        RELAY_PROVISION_FAILED=1
        RELAY_PROVISION_BANNER="$output"
        printf '%s\n' "$RELAY_PROVISION_BANNER"
        print_warning "Relay binary NOT provisioned (continuing; see the banner above, repeated at the end)"
    else
        RELAY_PROVISION_FAILED=1
        RELAY_PROVISION_BANNER="$(printf '%s\n%s\n%s\n%s' \
            "WARNING: RELAY BINARY NOT PROVISIONED" \
            "The relay provisioning step itself failed (exit $rc). Its output:" \
            "$output" \
            "Fix the error above, then run: $daemon_dir/bin/hooks-daemon transport on")"
        printf '%s\n' "$RELAY_PROVISION_BANNER"
        print_warning "Relay provisioning step failed with exit $rc (continuing; repeated at the end)"
    fi

    regenerate_forwarders_for_transport "$project_root" "$project_root/.claude/hooks" "$venv_python"
    return 0
}

#
# report_relay_provision_failure() - Repeat the failure banner, if any
#
# Call just before the script's final exit so the warning is the last thing
# printed. Prints nothing when provisioning succeeded or was disabled.
#
# Returns:
#   0 always
#
report_relay_provision_failure() {
    if [ "$RELAY_PROVISION_FAILED" -ne 1 ]; then
        return 0
    fi
    echo ""
    echo "Repeated from the relay binary step earlier in this run:"
    printf '%s\n' "$RELAY_PROVISION_BANNER"
    echo ""
    return 0
}
