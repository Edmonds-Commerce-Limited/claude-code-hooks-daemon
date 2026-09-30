#!/bin/bash
#
# Record the daemon version a project expects in its config (Plan 00477).
#
# install and upgrade call this after the deploy, so the tracked
# .claude/hooks-daemon.yaml names the version .claude/provision.sh installs into
# a fresh checkout. The edit itself is install/expected_version.py.
#

#
# record_expected_version() - Write daemon.expected_version into the project config
#
# Args:
#   $1 - venv_python: The venv interpreter of the daemon just deployed
#   $2 - project_root: Path to the project root
#
# Returns:
#   Exit code 0 on success, 1 on failure (the caller decides whether that is fatal)
#
record_expected_version() {
    local venv_python="$1"
    local project_root="$2"

    if [ -z "$venv_python" ] || [ -z "$project_root" ]; then
        print_error "record_expected_version: venv_python and project_root required"
        return 1
    fi

    "$venv_python" -m claude_code_hooks_daemon.install.expected_version \
        --project-root "$project_root"
}
