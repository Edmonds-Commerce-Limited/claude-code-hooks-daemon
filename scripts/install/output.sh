#!/bin/bash
#
# output.sh - Unified output and logging functions
#
# Provides color-coded output functions with terminal detection.
# Single source of truth for all install/upgrade script logging.
#
# Usage:
#   source "$(dirname "$0")/lib/output.sh"
#   print_success "Operation completed"
#   print_error "Something went wrong"
#

# Terminal detection for color support (only define if not already set)
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    if [ -t 1 ]; then
        # stdout is a terminal - use colors
        readonly RED='\033[0;31m'
        readonly GREEN='\033[0;32m'
        readonly YELLOW='\033[1;33m'
        readonly BLUE='\033[0;34m'
        readonly CYAN='\033[0;36m'
        readonly BOLD='\033[1m'
        readonly NC='\033[0m' # No Color
    else
        # stdout is not a terminal (pipe/redirect) - no colors
        readonly RED=''
        readonly GREEN=''
        readonly YELLOW=''
        readonly BLUE=''
        readonly CYAN=''
        readonly BOLD=''
        readonly NC=''
    fi

    # Mark as loaded to prevent redefinition
    readonly OUTPUT_SH_LOADED=1
fi

#
# print_header() - Print a prominent header section
#
# Args:
#   $1 - Header text
#
print_header() {
    echo ""
    echo "============================================================"
    echo "$1"
    echo "============================================================"
    echo ""
}

#
# print_success() - Print success message with checkmark
#
# Args:
#   $1 - Success message
#
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

#
# print_error() - Print error message with X mark (to stderr)
#
# Args:
#   $1 - Error message
#
print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

#
# print_warning() - Print warning message with warning symbol
#
# Args:
#   $1 - Warning message
#
print_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

#
# print_info() - Print info message with arrow
#
# Args:
#   $1 - Info message
#
print_info() {
    echo -e "${BLUE}→${NC} $1"
}

#
# log_step() - Print a numbered step with separator
#
# Args:
#   $1 - Step number
#   $2 - Step description
#
log_step() {
    local step="$1"
    local message="$2"
    echo ""
    echo -e "${BOLD}Step $step: $message${NC}"
    echo "----------------------------------------"
}

#
# fail_fast() - Print error and exit immediately
#
# Args:
#   $1 - Error message
#   $2 - Exit code (optional, defaults to 1)
#
fail_fast() {
    local message="$1"
    local exit_code="${2:-1}"

    print_error "$message"
    echo ""
    echo "Operation aborted."
    exit "$exit_code"
}

#
# print_verbose() - Print verbose/debug message (only if VERBOSE=true)
#
# Args:
#   $1 - Debug message
#
print_verbose() {
    if [ "${VERBOSE:-false}" = "true" ]; then
        echo -e "${CYAN}[DEBUG]${NC} $1"
    fi
}
