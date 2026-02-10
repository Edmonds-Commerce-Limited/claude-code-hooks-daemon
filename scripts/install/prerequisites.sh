#!/bin/bash
#
# prerequisites.sh - Unified prerequisite checking for install/upgrade
#
# Checks for required system dependencies: git, python3 (3.11+), and uv.
# Single source of truth for prerequisite validation.
#
# Usage:
#   source "$(dirname "$0")/lib/prerequisites.sh"
#   check_all_prerequisites
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# check_git() - Verify git is installed
#
# Returns:
#   0 - git found
#   1 - git not found (also exits via fail_fast)
#
check_git() {
    if ! command -v git &> /dev/null; then
        fail_fast "git is not installed. Please install git first.

Installation:
  Ubuntu/Debian: sudo apt-get install git
  macOS: brew install git or xcode-select --install
  Fedora: sudo dnf install git"
    fi
    print_success "git found"
    return 0
}

#
# check_python3() - Verify python3 is installed and meets version requirements
#
# Requires Python 3.11 or higher
#
# Returns:
#   0 - python3 found and version >= 3.11
#   1 - python3 not found or version too old (also exits via fail_fast)
#
check_python3() {
    # Check if python3 command exists
    if ! command -v python3 &> /dev/null; then
        fail_fast "python3 is not installed. Please install Python 3.11+ first.

Installation:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11"
    fi

    # Check Python version (must be 3.11+)
    local python_version
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null)

    if [ -z "$python_version" ]; then
        fail_fast "Could not determine Python version. python3 command failed."
    fi

    local major minor
    major=$(echo "$python_version" | cut -d. -f1)
    minor=$(echo "$python_version" | cut -d. -f2)

    # Validate major.minor format
    if ! [[ "$major" =~ ^[0-9]+$ ]] || ! [[ "$minor" =~ ^[0-9]+$ ]]; then
        fail_fast "Invalid Python version format: $python_version"
    fi

    # Check version is 3.11+
    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
        fail_fast "Python 3.11+ required. Found: $python_version

Please upgrade Python:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11"
    fi

    print_success "Python $python_version found"
    return 0
}

#
# check_uv() - Verify uv is installed (optionally auto-install)
#
# Args:
#   $1 - auto_install (optional, default: true)
#        If true, attempts to install uv if not found
#        If false, fails fast if uv not found
#
# Returns:
#   0 - uv found or successfully installed
#   1 - uv not found and auto-install failed (also exits via fail_fast)
#
check_uv() {
    local auto_install="${1:-true}"

    if command -v uv &> /dev/null; then
        print_success "uv found"
        return 0
    fi

    # uv not found
    if [ "$auto_install" != "true" ]; then
        fail_fast "uv is not installed. Please install uv first.

Installation:
  curl -LsSf https://astral.sh/uv/install.sh | sh
  Then restart your shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    # Auto-install uv
    print_info "uv not found, installing..."

    if ! curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1; then
        fail_fast "Failed to install uv. Please install manually:

Installation:
  curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi

    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    # Verify uv is now available
    if ! command -v uv &> /dev/null; then
        fail_fast "uv installed but not found in PATH.

Please restart your shell or run:
  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    print_success "uv installed successfully"
    return 0
}

#
# check_all_prerequisites() - Run all prerequisite checks
#
# Args:
#   $1 - auto_install_uv (optional, default: true)
#        Passed to check_uv()
#
# Returns:
#   0 - all prerequisites met
#   1 - one or more prerequisites failed (also exits via fail_fast)
#
check_all_prerequisites() {
    local auto_install_uv="${1:-true}"

    print_info "Checking prerequisites..."

    check_git
    check_python3
    check_uv "$auto_install_uv"

    print_success "All prerequisites met"
    return 0
}

#
# get_python_version() - Get Python version string
#
# Returns:
#   Prints version string (e.g., "3.11.5") to stdout
#   Exit code 0 on success, 1 on failure
#
get_python_version() {
    if ! command -v python3 &> /dev/null; then
        return 1
    fi

    python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null
}

#
# get_python_major_minor() - Get Python major.minor version
#
# Returns:
#   Prints version string (e.g., "3.11") to stdout
#   Exit code 0 on success, 1 on failure
#
get_python_major_minor() {
    if ! command -v python3 &> /dev/null; then
        return 1
    fi

    python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null
}
