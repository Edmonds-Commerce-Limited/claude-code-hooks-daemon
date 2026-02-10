#!/bin/bash
#
# validation.sh - Unified validation wrapper for ClientInstallValidator
#
# Wraps Python ClientInstallValidator calls with bash functions.
# Provides pre-install and post-install validation checks.
#
# Usage:
#   source "$(dirname "$0")/install/validation.sh"
#   run_pre_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR"
#   run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# run_pre_install_checks() - Run pre-installation safety checks
#
# Validates project state before installing/upgrading daemon.
# Calls ClientInstallValidator.validate_pre_install().
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - venv_python: Path to venv Python binary
#   $3 - daemon_dir: Path to daemon installation directory
#   $4 - fail_on_error (optional, default: true)
#        If true, fails fast on validation errors
#        If false, returns non-zero but doesn't exit
#
# Returns:
#   Exit code 0 if validation passed
#   Exit code 1 if validation failed
#
run_pre_install_checks() {
    local project_root="$1"
    local venv_python="$2"
    local daemon_dir="$3"
    local fail_on_error="${4:-true}"

    if [ -z "$project_root" ] || [ -z "$venv_python" ] || [ -z "$daemon_dir" ]; then
        print_error "run_pre_install_checks: project_root, venv_python, and daemon_dir required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_warning "Venv Python not found, skipping pre-install checks: $venv_python"
        return 0
    fi

    print_info "Running pre-installation safety checks..."

    local validation_script
    validation_script=$(cat <<'PYTHON_EOF'
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("DAEMON_DIR_PLACEHOLDER")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    project_root = Path("PROJECT_ROOT_PLACEHOLDER")

    # Run pre-install validation
    result = ClientInstallValidator.validate_pre_install(project_root)

    # Print warnings
    for warning in result.warnings:
        print(f"⚠️  {warning}")

    # Print errors
    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

    print("✅ Pre-install checks passed")

except ImportError as e:
    print(f"⚠️  Warning: Could not import validator (old version?): {e}", file=sys.stderr)
    # Don't fail if validator can't be imported (backward compatibility)
    sys.exit(0)
except Exception as e:
    print(f"⚠️  Warning: Could not run safety checks: {e}", file=sys.stderr)
    # Don't fail if checks can't run (might be old version)
    sys.exit(0)
PYTHON_EOF
)

    # Replace placeholders
    validation_script="${validation_script//PROJECT_ROOT_PLACEHOLDER/$project_root}"
    validation_script="${validation_script//DAEMON_DIR_PLACEHOLDER/$daemon_dir}"

    # Run validation
    local validation_output
    local validation_exit_code

    validation_output=$("$venv_python" -c "$validation_script" 2>&1)
    validation_exit_code=$?

    if [ $validation_exit_code -eq 0 ]; then
        echo "$validation_output"
        return 0
    else
        echo "$validation_output"

        if [ "$fail_on_error" = "true" ]; then
            fail_fast "Pre-installation validation failed. Please fix the issues above."
        else
            print_error "Pre-installation validation failed"
            return 1
        fi
    fi
}

#
# run_post_install_checks() - Run post-installation verification checks
#
# Validates installation completed successfully.
# Calls ClientInstallValidator.validate_post_install().
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - venv_python: Path to venv Python binary
#   $3 - daemon_dir: Path to daemon installation directory
#   $4 - fail_on_error (optional, default: true)
#
# Returns:
#   Exit code 0 if validation passed
#   Exit code 1 if validation failed
#
run_post_install_checks() {
    local project_root="$1"
    local venv_python="$2"
    local daemon_dir="$3"
    local fail_on_error="${4:-true}"

    if [ -z "$project_root" ] || [ -z "$venv_python" ] || [ -z "$daemon_dir" ]; then
        print_error "run_post_install_checks: project_root, venv_python, and daemon_dir required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    print_info "Running post-installation verification checks..."

    local validation_script
    validation_script=$(cat <<'PYTHON_EOF'
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("DAEMON_DIR_PLACEHOLDER")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    project_root = Path("PROJECT_ROOT_PLACEHOLDER")

    # Run post-install validation
    result = ClientInstallValidator.validate_post_install(project_root)

    # Print warnings
    for warning in result.warnings:
        print(f"⚠️  {warning}")

    # Print errors
    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

    print("✅ Post-install checks passed")

except ImportError as e:
    print(f"⚠️  Warning: Could not import validator: {e}", file=sys.stderr)
    sys.exit(0)
except Exception as e:
    print(f"⚠️  Warning: Could not run verification checks: {e}", file=sys.stderr)
    sys.exit(0)
PYTHON_EOF
)

    # Replace placeholders
    validation_script="${validation_script//PROJECT_ROOT_PLACEHOLDER/$project_root}"
    validation_script="${validation_script//DAEMON_DIR_PLACEHOLDER/$daemon_dir}"

    # Run validation
    local validation_output
    local validation_exit_code

    validation_output=$("$venv_python" -c "$validation_script" 2>&1)
    validation_exit_code=$?

    if [ $validation_exit_code -eq 0 ]; then
        echo "$validation_output"
        return 0
    else
        echo "$validation_output"

        if [ "$fail_on_error" = "true" ]; then
            fail_fast "Post-installation verification failed. Please review the issues above."
        else
            print_error "Post-installation verification failed"
            return 1
        fi
    fi
}

#
# cleanup_stale_runtime_files() - Remove stale daemon runtime files
#
# Calls ClientInstallValidator.cleanup_stale_runtime_files().
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - venv_python: Path to venv Python binary
#   $3 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Exit code 0 always (warnings are printed but don't fail)
#
cleanup_stale_runtime_files() {
    local project_root="$1"
    local venv_python="$2"
    local daemon_dir="$3"

    if [ -z "$project_root" ] || [ -z "$venv_python" ] || [ -z "$daemon_dir" ]; then
        print_error "cleanup_stale_runtime_files: project_root, venv_python, and daemon_dir required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_verbose "Venv Python not found, skipping cleanup: $venv_python"
        return 0
    fi

    print_verbose "Cleaning up stale runtime files..."

    local cleanup_script
    cleanup_script=$(cat <<'PYTHON_EOF'
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("DAEMON_DIR_PLACEHOLDER")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    project_root = Path("PROJECT_ROOT_PLACEHOLDER")

    # Run cleanup
    result = ClientInstallValidator.cleanup_stale_runtime_files(project_root)

    # Print warnings
    for warning in result.warnings:
        print(f"  {warning}")

except ImportError:
    # Silently skip if validator not available
    pass
except Exception as e:
    # Silently skip on errors (cleanup is non-critical)
    pass
PYTHON_EOF
)

    # Replace placeholders
    cleanup_script="${cleanup_script//PROJECT_ROOT_PLACEHOLDER/$project_root}"
    cleanup_script="${cleanup_script//DAEMON_DIR_PLACEHOLDER/$daemon_dir}"

    # Run cleanup (suppress errors)
    "$venv_python" -c "$cleanup_script" 2>/dev/null || true

    return 0
}

#
# verify_config_valid() - Verify configuration is valid
#
# Calls ClientInstallValidator._verify_config_valid().
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - venv_python: Path to venv Python binary
#   $3 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Exit code 0 if config is valid, 1 if invalid
#
verify_config_valid() {
    local project_root="$1"
    local venv_python="$2"
    local daemon_dir="$3"

    if [ -z "$project_root" ] || [ -z "$venv_python" ] || [ -z "$daemon_dir" ]; then
        print_error "verify_config_valid: project_root, venv_python, and daemon_dir required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    local verify_script
    verify_script=$(cat <<'PYTHON_EOF'
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path("DAEMON_DIR_PLACEHOLDER")
sys.path.insert(0, str(daemon_dir / "src"))

try:
    from claude_code_hooks_daemon.install import ClientInstallValidator

    project_root = Path("PROJECT_ROOT_PLACEHOLDER")

    # Verify config
    result = ClientInstallValidator._verify_config_valid(project_root)

    if not result.passed:
        for error in result.errors:
            print(f"❌ {error}", file=sys.stderr)
        sys.exit(1)

except ImportError:
    # Assume valid if validator not available
    sys.exit(0)
except Exception as e:
    print(f"⚠️  Warning: Could not verify config: {e}", file=sys.stderr)
    sys.exit(0)
PYTHON_EOF
)

    # Replace placeholders
    verify_script="${verify_script//PROJECT_ROOT_PLACEHOLDER/$project_root}"
    verify_script="${verify_script//DAEMON_DIR_PLACEHOLDER/$daemon_dir}"

    # Run verification
    if "$venv_python" -c "$verify_script" 2>&1; then
        return 0
    else
        return 1
    fi
}
