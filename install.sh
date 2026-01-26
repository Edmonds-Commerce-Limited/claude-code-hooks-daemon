#!/bin/bash
#
# Claude Code Hooks Daemon - One-Line Installer
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/EdmondsCommerce/claude-code-hooks-daemon/main/install.sh | bash
#
# This script:
# 1. Validates project root (.claude and .git must exist)
# 2. Clones daemon repository to .claude/hooks-daemon/
# 3. Runs install_v2.py to set up hooks and config
# 4. Installs Python package dependencies
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DAEMON_REPO="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"
DAEMON_BRANCH="${DAEMON_BRANCH:-main}"
DRY_RUN="${DRY_RUN:-false}"
FORCE="${FORCE:-false}"

#
# Print functions
#
print_header() {
    echo ""
    echo "============================================================"
    echo "$1"
    echo "============================================================"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

print_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

print_info() {
    echo -e "${BLUE}→${NC} $1"
}

#
# Fail fast with clear error message
#
fail_fast() {
    print_error "$1"
    echo ""
    echo "Installation aborted."
    exit 1
}

#
# Check prerequisites
#
check_prerequisites() {
    print_info "Checking prerequisites..."

    # Check for git
    if ! command -v git &> /dev/null; then
        fail_fast "git is not installed. Please install git first."
    fi
    print_success "git found"

    # Check for Python 3
    if ! command -v python3 &> /dev/null; then
        fail_fast "python3 is not installed. Please install Python 3.11+ first."
    fi

    # Check Python version (must be 3.11+)
    local python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    local major=$(echo "$python_version" | cut -d. -f1)
    local minor=$(echo "$python_version" | cut -d. -f2)

    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
        fail_fast "Python 3.11+ required. Found: $python_version"
    fi
    print_success "Python $python_version found"

    # Check for uv (install if missing)
    if ! command -v uv &> /dev/null; then
        print_info "uv not found, installing..."
        if ! curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1; then
            fail_fast "Failed to install uv. Please install manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
        fi
        # Add uv to PATH for this session
        export PATH="$HOME/.local/bin:$PATH"
        if ! command -v uv &> /dev/null; then
            fail_fast "uv installed but not found in PATH. Please restart your shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
        print_success "uv installed"
    else
        print_success "uv found"
    fi
}

#
# Validate project root
#
validate_project_root() {
    print_info "Validating project root..."

    local pwd="$(pwd)"

    # Check for .claude directory
    if [[ ! -d ".claude" ]]; then
        fail_fast "No .claude directory found in current directory: $pwd
This script must be run from a Claude Code project root.

Expected directory structure:
  your-project/
  ├── .claude/
  ├── .git/
  └── ..."
    fi
    print_success ".claude directory exists"

    # Check for .git directory
    if [[ ! -d ".git" ]]; then
        fail_fast "No .git directory found in current directory: $pwd
This script must be run from a git repository root.

Expected directory structure:
  your-project/
  ├── .claude/
  ├── .git/
  └── ..."
    fi
    print_success ".git directory exists"

    print_success "Project root validated: $pwd"
}

#
# Clone daemon repository
#
clone_daemon() {
    local daemon_dir=".claude/hooks-daemon"

    print_info "Checking daemon installation..."

    # Check if daemon directory already exists
    if [[ -d "$daemon_dir" ]]; then
        if [[ "$FORCE" == "true" ]]; then
            print_warning "Daemon already installed at $daemon_dir"
            print_info "Removing existing installation (--force mode)..."
            rm -rf "$daemon_dir"
        else
            print_error "Daemon already installed at $daemon_dir"
            echo ""
            echo "To reinstall, run with FORCE=true:"
            echo "  curl -sSL ... | FORCE=true bash"
            echo ""
            echo "Or manually remove and reinstall:"
            echo "  rm -rf $daemon_dir"
            echo "  curl -sSL ... | bash"
            exit 1
        fi
    fi

    print_info "Cloning daemon from GitHub..."
    print_info "Repository: $DAEMON_REPO"
    print_info "Branch: $DAEMON_BRANCH"

    if ! git clone --branch "$DAEMON_BRANCH" --depth 1 "$DAEMON_REPO" "$daemon_dir" > /dev/null 2>&1; then
        fail_fast "Failed to clone daemon repository"
    fi

    print_success "Daemon cloned to $daemon_dir"
}

#
# Ensure daemon directory is git-ignored in main project
#
ensure_gitignore() {
    print_info "Ensuring daemon is git-ignored..."

    local gitignore_file=".gitignore"
    local ignore_entry="/.claude/hooks-daemon/"

    # Create .gitignore if it doesn't exist
    if [[ ! -f "$gitignore_file" ]]; then
        echo "$ignore_entry" > "$gitignore_file"
        print_success "Created .gitignore with daemon entry"
        return
    fi

    # Check if entry already exists
    if grep -qF "$ignore_entry" "$gitignore_file"; then
        print_success "Daemon already in .gitignore"
        return
    fi

    # Add entry to .gitignore
    echo "" >> "$gitignore_file"
    echo "# Claude Code Hooks Daemon (separate git repo)" >> "$gitignore_file"
    echo "$ignore_entry" >> "$gitignore_file"
    print_success "Added daemon to .gitignore"
}

#
# Install Python dependencies
#
install_dependencies() {
    local daemon_dir=".claude/hooks-daemon"

    print_info "Installing Python dependencies with uv..."

    cd "$daemon_dir"

    # Create untracked dir with self-excluding .gitignore
    mkdir -p untracked
    echo "/untracked/" > untracked/.gitignore

    # Use uv to sync dependencies to untracked/venv (not .venv)
    # UV_PROJECT_ENVIRONMENT tells uv where to create the venv
    if UV_PROJECT_ENVIRONMENT="$(pwd)/untracked/venv" uv sync --project . > /dev/null 2>&1; then
        print_success "Dependencies installed (uv managed venv)"
    else
        print_warning "Failed to install dependencies via uv"
        print_info "You may need to install manually:"
        echo "  cd $daemon_dir"
        echo "  UV_PROJECT_ENVIRONMENT=\$(pwd)/untracked/venv uv sync"
    fi

    cd - > /dev/null
}

#
# Run install.py with --force flag
#
run_installer() {
    local daemon_dir=".claude/hooks-daemon"

    print_info "Running daemon installer..."

    # Always use --force when called from bash installer
    local install_cmd="python3 $daemon_dir/install.py --force"

    if ! $install_cmd; then
        fail_fast "Daemon installation failed"
    fi
}

#
# Print next steps
#
print_next_steps() {
    print_header "Installation Complete!"

    echo "The Claude Code Hooks Daemon has been installed successfully."
    echo ""
    echo "Next Steps:"
    echo ""
    echo "  1. Edit configuration (optional):"
    echo "     vim .claude/hooks-daemon.yaml"
    echo ""
    echo "  2. Commit the hook scripts to your repository:"
    echo "     git add .claude/hooks/ .claude/settings.json .claude/hooks-daemon.yaml"
    echo "     git commit -m 'Add Claude Code hooks daemon'"
    echo ""
    echo "  3. Hooks will start automatically on next tool use"
    echo ""
    echo "Daemon Management:"
    echo "  Status:  cd .claude/hooks-daemon && uv run python -m claude_code_hooks_daemon.daemon.cli status"
    echo "  Config:  cd .claude/hooks-daemon && uv run python -m claude_code_hooks_daemon.daemon.cli init-config"
    echo ""
    echo "Documentation:"
    echo "  README:       .claude/hooks-daemon/README.md"
    echo ""
    echo "Dependencies:"
    echo "  Managed by:   uv (https://docs.astral.sh/uv/)"
    echo "  Location:     .claude/hooks-daemon/untracked/venv/"
    echo ""
}

#
# Main installation flow
#
main() {
    print_header "Claude Code Hooks Daemon - Installer"

    check_prerequisites
    validate_project_root
    clone_daemon
    ensure_gitignore
    install_dependencies
    run_installer
    print_next_steps
}

# Run main function
main "$@"
