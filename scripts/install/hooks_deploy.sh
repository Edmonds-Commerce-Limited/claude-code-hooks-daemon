#!/bin/bash
#
# hooks_deploy.sh - Unified hook script deployment
#
# Deploys hook scripts from daemon installation to project .claude/hooks/.
# Single source of truth: actual hook scripts in daemon's .claude/hooks/ directory.
# Handles both normal and self-install modes.
#
# Usage:
#   source "$(dirname "$0")/lib/hooks_deploy.sh"
#   deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "$INSTALL_MODE"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Canonical hook entrypoint basenames the installer deploys to .claude/hooks/.
# Single source of truth for which files the installer OWNS and may mark
# executable. Permission functions must restrict themselves to these names so
# they never touch pre-existing non-hook files (docs like CLAUDE.md/README.md,
# or another tool's hooks) that happen to sit alongside them — force-chmod'ing
# those produced content-free git mode-bit noise on every reinstall (Issue #4).
# Mirrors the daemon_hooks map + status-line in install.py and the daemon's own
# .claude/hooks/ directory.
_DAEMON_HOOK_BASENAMES=(
    pre-tool-use
    post-tool-use
    session-start
    permission-request
    notification
    user-prompt-submit
    stop
    subagent-stop
    pre-compact
    session-end
    status-line
    # Plan 00170: zero-handler-passthrough events (wired for coverage).
    setup
    permission-denied
    cwd-changed
    worktree-create
    worktree-remove
    user-prompt-expansion
    post-tool-use-failure
    post-tool-batch
    subagent-start
    task-created
    task-completed
    stop-failure
    teammate-idle
    instructions-loaded
    config-change
    file-changed
    post-compact
    elicitation
    elicitation-result
)

# Relative path (within the daemon dir — the git clone/checkout, NOT the
# project's own .claude/) to the echd-capture output-capture helper the
# pipe_blocker handler recommends. Single source of truth mirrored by
# _ECHD_CAPTURE_REL_PARTS in pipe_blocker.py.
_ECHD_CAPTURE_REL_PATH="scripts/echd-capture"

#
# list_deployed_hook_paths() - Emit paths of installer-owned hook entrypoints
#
# Prints (one per line) the absolute path of each canonical hook entrypoint
# that actually exists as a regular file in the given hooks directory. Used to
# scope permission changes to files the installer manages (Issue #4).
#
# Args:
#   $1 - hooks_dir: Path to the project's .claude/hooks directory
#
list_deployed_hook_paths() {
    local hooks_dir="$1"
    local name path
    for name in "${_DAEMON_HOOK_BASENAMES[@]}"; do
        path="$hooks_dir/$name"
        if [ -f "$path" ]; then
            printf '%s\n' "$path"
        fi
    done
}

#
# deploy_hook_scripts() - Deploy hook forwarder scripts to project
#
# Copies hook scripts from daemon installation to project .claude/hooks/.
# In self-install mode, creates symlinks instead of copies.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_hook_scripts() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "deploy_hook_scripts: project_root and daemon_dir required"
        return 1
    fi

    local source_hooks="$daemon_dir/.claude/hooks"
    local target_hooks="$project_root/.claude/hooks"

    # CRITICAL: In self-install mode, source and target are THE SAME.
    # Do NOT create symlinks or copy - hooks are already in place.
    if [ "$install_mode" = "self-install" ]; then
        if [ "$source_hooks" = "$target_hooks" ]; then
            print_verbose "Self-install mode: hooks already in place, skipping deployment"
            return 0
        fi
    fi

    if [ ! -d "$source_hooks" ]; then
        print_error "Source hooks directory not found: $source_hooks"
        return 1
    fi

    print_info "Deploying hook scripts..."

    # Create target directory
    mkdir -p "$target_hooks"

    # Get list of hook scripts (exclude directories and hidden files)
    local hook_files
    hook_files=$(find "$source_hooks" -maxdepth 1 -type f ! -name ".*" -exec basename {} \;)

    if [ -z "$hook_files" ]; then
        print_warning "No hook scripts found in: $source_hooks"
        return 0
    fi

    local deployed_count=0

    for hook_file in $hook_files; do
        local source="$source_hooks/$hook_file"
        local target="$target_hooks/$hook_file"

        # Normal mode: copy files (never symlink hooks)
        cp "$source" "$target"
        print_verbose "Copied: $hook_file"

        deployed_count=$((deployed_count + 1))
    done

    print_success "Deployed $deployed_count hook scripts"
    return 0
}

#
# deploy_init_script() - Deploy init.sh to project
#
# Copies init.sh script from daemon installation to project .claude/.
# In self-install mode, creates symlink instead of copy.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_init_script() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "deploy_init_script: project_root and daemon_dir required"
        return 1
    fi

    local source_init="$daemon_dir/init.sh"
    local target_init="$project_root/.claude/init.sh"

    # CRITICAL: In self-install mode, check if source and target are the same
    if [ "$install_mode" = "self-install" ]; then
        # If init.sh is already at target location, skip. Use bash's `-ef`
        # operator (same device + inode, resolves symlinks) — Plan 00123 BUG 4
        # (MEDIUM): the previous `readlink -f` compare is GNU-only; BSD/macOS
        # readlink has no -f, so both sides fell back to differing literal
        # paths and the short-circuit never fired on macOS.
        if [ -f "$target_init" ] && [ "$source_init" -ef "$target_init" ]; then
            print_verbose "Self-install mode: init.sh already in place, skipping deployment"
            return 0
        fi
    fi

    if [ ! -f "$source_init" ]; then
        print_error "Source init.sh not found: $source_init"
        return 1
    fi

    print_verbose "Deploying init.sh..."

    # Normal mode: copy file (never symlink)
    cp "$source_init" "$target_init"
    print_verbose "Copied init.sh"

    return 0
}

#
# set_hook_permissions() - Ensure hook scripts are executable
#
# Sets executable permissions on all hook scripts.
# Handles git core.fileMode=false case by checking if permissions stick.
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
set_hook_permissions() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        print_error "set_hook_permissions: project_root required"
        return 1
    fi

    local hooks_dir="$project_root/.claude/hooks"

    if [ ! -d "$hooks_dir" ]; then
        print_warning "Hooks directory not found: $hooks_dir"
        return 0
    fi

    print_verbose "Setting executable permissions on hook scripts..."

    # Only the installer-owned hook entrypoints — never pre-existing non-hook
    # files (docs, other tools' hooks) that share the directory (Issue #4).
    local hook_files
    hook_files=$(list_deployed_hook_paths "$hooks_dir")

    if [ -z "$hook_files" ]; then
        print_verbose "No hook files found to set permissions"
        return 0
    fi

    local chmod_count=0
    local chmod_failed=0
    local failed_files=""

    # Issue #29: do NOT silence chmod failures. A silently-failing chmod
    # leaves wrappers non-executable, which the daemon cannot detect and
    # the user only notices when hooks silently stop firing.
    for hook_file in $hook_files; do
        if chmod +x "$hook_file"; then
            chmod_count=$((chmod_count + 1))
        else
            chmod_failed=$((chmod_failed + 1))
            failed_files="$failed_files $hook_file"
        fi
    done

    if [ "$chmod_failed" -gt 0 ]; then
        print_error "Failed to set executable on $chmod_failed hook script(s):$failed_files"
        return 1
    fi

    # Verify permissions actually stuck. The common cause of a successful
    # chmod call producing a still-non-executable file is git's
    # core.fileMode=false combined with a subsequent filesystem event
    # (e.g. checkout/merge) resetting tracked modes — advisory, not fatal.
    local test_file
    test_file=$(echo "$hook_files" | awk 'NR==1')
    if [ -f "$test_file" ] && [ ! -x "$test_file" ]; then
        print_warning "Hook permissions may not persist (git core.fileMode=false)"
        print_info "Hooks will still work after re-chmod, but permissions won't be tracked by git"
    else
        print_verbose "Set executable on $chmod_count hook scripts"
    fi

    return 0
}

#
# ensure_echd_capture_executable() - Ensure the echd-capture helper is executable
#
# The pipe_blocker handler recommends `daemon_dir/scripts/echd-capture` (an
# ABSOLUTE path resolved by PipeBlockerHandler._resolve_echd_capture_path) as
# the alternative to piping expensive commands into tail/head. The script is
# vendored inside the daemon's own git checkout, so it is already present at
# `daemon_dir/scripts/echd-capture` after any clone/checkout — but the exec
# bit tracked by git can be lost the same way hook wrappers can (e.g. client
# repo/checkout with `core.fileMode=false`). Explicitly chmod it here,
# mirroring set_hook_permissions, so the recommended command always works
# regardless of how the exec bit travelled.
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Exit code 0 on success (missing helper is non-fatal — older daemon
#   versions predating the helper simply have nothing to chmod), 1 if a
#   present helper's chmod call fails.
#
ensure_echd_capture_executable() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        print_error "ensure_echd_capture_executable: daemon_dir required"
        return 1
    fi

    local helper="$daemon_dir/$_ECHD_CAPTURE_REL_PATH"

    if [ ! -f "$helper" ]; then
        print_verbose "echd-capture helper not present (older daemon checkout), skipping"
        return 0
    fi

    if ! chmod +x "$helper"; then
        print_error "Failed to set executable on echd-capture helper: $helper"
        return 1
    fi

    print_verbose "Set executable on echd-capture helper: $helper"
    return 0
}

#
# git_force_executable() - Force executable bit in git index
#
# Uses `git update-index --chmod=+x` to ensure hook scripts are stored
# as 100755 in git's index, regardless of core.fileMode setting.
# This ensures hooks survive checkout/merge/rebase operations.
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 on success (always succeeds - git index errors are non-fatal)
#
git_force_executable() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        print_error "git_force_executable: project_root required"
        return 1
    fi

    # Check we're in a git repository (stderr suppressed: expected to fail outside git repos)
    if ! git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        print_verbose "Not a git repository, skipping git update-index"
        return 0
    fi

    local hooks_dir="$project_root/.claude/hooks"
    local init_script="$project_root/.claude/init.sh"
    local forced_count=0

    # Force executable on hook scripts — installer-owned entrypoints only, so
    # pre-existing non-hook files sharing the directory keep their tree mode
    # instead of being force-marked 100755 in the index (Issue #4).
    if [ -d "$hooks_dir" ]; then
        local hook_files
        hook_files=$(list_deployed_hook_paths "$hooks_dir")

        for hook_file in $hook_files; do
            local rel_path
            # stderr suppressed: file may not be tracked by git (expected case)
            rel_path=$(git -C "$project_root" ls-files --full-name "$hook_file" 2>/dev/null) || rel_path=""
            if [ -n "$rel_path" ]; then
                # stderr suppressed: update-index may fail if file not staged (expected case)
                if git -C "$project_root" update-index --chmod=+x "$rel_path" 2>/dev/null; then
                    forced_count=$((forced_count + 1))
                else
                    print_verbose "Could not force executable on $rel_path (file may not be staged)"
                fi
            fi
        done
    fi

    # Force executable on init.sh (if tracked by git)
    if [ -f "$init_script" ]; then
        local init_rel
        # stderr suppressed: file may not be tracked by git (expected case)
        init_rel=$(git -C "$project_root" ls-files --full-name "$init_script" 2>/dev/null) || init_rel=""
        if [ -n "$init_rel" ]; then
            # stderr suppressed: update-index may fail if file not staged (expected case)
            if git -C "$project_root" update-index --chmod=+x "$init_rel" 2>/dev/null; then
                forced_count=$((forced_count + 1))
            else
                print_verbose "Could not force executable on init.sh (file may not be staged)"
            fi
        fi
    fi

    if [ "$forced_count" -gt 0 ]; then
        print_info "Forced executable bit in git index for $forced_count files"
    fi

    # Detect core.fileMode=false and warn
    local filemode
    # stderr suppressed: git config may fail outside git repos (expected case)
    filemode=$(git -C "$project_root" config --local core.fileMode 2>/dev/null) || filemode=""
    if [ "$filemode" = "false" ]; then
        print_warning "git core.fileMode=false detected - hook permissions may not persist across git operations"
        print_info "Hook scripts have been force-marked as executable in git's index (git update-index --chmod=+x)"
        print_info "Strongly recommended: git config core.fileMode true"
    fi

    return 0
}

#
# deploy_all_hooks() - Complete hook deployment workflow
#
# Deploys all hooks, init script, and sets permissions.
# This is the recommended high-level function.
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
deploy_all_hooks() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        fail_fast "deploy_all_hooks: project_root and daemon_dir required"
    fi

    print_info "Deploying hooks to project..."

    # Deploy hook scripts
    if ! deploy_hook_scripts "$project_root" "$daemon_dir" "$install_mode"; then
        print_error "Failed to deploy hook scripts"
        return 1
    fi

    # Deploy init script
    if ! deploy_init_script "$project_root" "$daemon_dir" "$install_mode"; then
        print_error "Failed to deploy init.sh"
        return 1
    fi

    # Issue #29: always set permissions, in BOTH modes. Previously self-install
    # relied on install.py's `hook_file.chmod(0o755)` + git checkout preserving
    # 100755 tree mode, but any filesystem event that strips exec bits (IDE
    # save over network FS, core.fileMode=false checkout, manual cp from
    # non-executable source) would leave wrappers broken with no remediation.
    # Running set_hook_permissions unconditionally is idempotent and cheap.
    if ! set_hook_permissions "$project_root"; then
        print_warning "Failed to set hook permissions — hooks may not fire"
    fi

    # Ensure the echd-capture helper (recommended by pipe_blocker) is
    # executable — same rationale as set_hook_permissions above.
    if ! ensure_echd_capture_executable "$daemon_dir"; then
        print_warning "Failed to set echd-capture helper permissions — recommended command may fail"
    fi

    # Force executable bit in git index (both install modes benefit from this)
    git_force_executable "$project_root"

    print_success "Hooks deployed successfully"
    return 0
}

#
# verify_hooks_deployed() - Verify hooks are present and executable
#
# Args:
#   $1 - project_root: Path to project root
#
# Returns:
#   Exit code 0 if hooks are deployed, 1 if not
#
verify_hooks_deployed() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        return 1
    fi

    local hooks_dir="$project_root/.claude/hooks"
    local init_script="$project_root/.claude/init.sh"

    # Check hooks directory exists
    if [ ! -d "$hooks_dir" ]; then
        print_error "Hooks directory not found: $hooks_dir"
        return 1
    fi

    # Check init.sh exists
    if [ ! -f "$init_script" ]; then
        print_error "init.sh not found: $init_script"
        return 1
    fi

    # Count hook files
    local hook_count
    hook_count=$(find "$hooks_dir" -maxdepth 1 -type f -o -type l | wc -l)

    if [ "$hook_count" -lt 5 ]; then
        print_warning "Only $hook_count hook scripts found (expected at least 5)"
        return 1
    fi

    print_verbose "Hooks verified: $hook_count scripts found"
    return 0
}
