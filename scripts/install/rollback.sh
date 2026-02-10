#!/bin/bash
#
# rollback.sh - State snapshot and rollback functionality
#
# Provides comprehensive state snapshots for upgrade rollback.
# Captures: code (git ref), config, hooks, settings, gitignore, venv state.
#
# Usage:
#   source "$(dirname "$0")/install/rollback.sh"
#   create_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "$INSTALL_MODE"
#   restore_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "$SNAPSHOT_ID"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Snapshot directory structure
readonly SNAPSHOT_BASE_DIR="untracked/upgrade-snapshots"

#
# get_snapshot_dir() - Get snapshot base directory for install mode
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Prints snapshot directory path to stdout
#
get_snapshot_dir() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        return 1
    fi

    echo "$daemon_dir/$SNAPSHOT_BASE_DIR"
}

#
# create_state_snapshot() - Create comprehensive state snapshot
#
# Captures complete state for rollback:
# - Git ref (current version)
# - Config file (.claude/hooks-daemon.yaml)
# - Settings file (.claude/settings.json)
# - Hook scripts (.claude/hooks/*)
# - Init script (.claude/init.sh)
# - Root .gitignore (daemon entry only)
# - Venv metadata (python version, package list)
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - install_mode: "self-install" or "normal"
#
# Returns:
#   Prints snapshot ID to stdout
#   Exit code 0 on success, 1 on failure
#
create_state_snapshot() {
    local project_root="$1"
    local daemon_dir="$2"
    local install_mode="$3"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ]; then
        print_error "create_state_snapshot: project_root and daemon_dir required"
        return 1
    fi

    local snapshot_base
    snapshot_base=$(get_snapshot_dir "$daemon_dir")

    # Create snapshot ID (timestamp)
    local snapshot_id
    snapshot_id=$(date +%Y%m%d_%H%M%S)
    local snapshot_dir="$snapshot_base/$snapshot_id"

    print_info "Creating state snapshot: $snapshot_id"

    # Create snapshot directory
    mkdir -p "$snapshot_dir"

    # Create manifest
    local manifest="$snapshot_dir/manifest.json"

    # Capture git ref (current version)
    local git_ref="unknown"
    if [ -d "$daemon_dir/.git" ]; then
        git_ref=$(git -C "$daemon_dir" rev-parse HEAD 2>/dev/null || echo "unknown")
    fi

    # Capture venv metadata
    local python_version="unknown"
    local venv_python
    if [ "$install_mode" = "self-install" ]; then
        venv_python="$daemon_dir/untracked/venv/bin/python"
    else
        venv_python="$daemon_dir/untracked/venv/bin/python"
    fi

    if [ -f "$venv_python" ]; then
        python_version=$("$venv_python" --version 2>&1 | awk '{print $2}')
    fi

    # Write manifest
    cat > "$manifest" <<EOF
{
  "snapshot_id": "$snapshot_id",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_root": "$project_root",
  "daemon_dir": "$daemon_dir",
  "install_mode": "$install_mode",
  "git_ref": "$git_ref",
  "python_version": "$python_version",
  "files": []
}
EOF

    # Helper function to backup file
    backup_file() {
        local source="$1"
        local relative_path="$2"

        if [ ! -f "$source" ] && [ ! -L "$source" ]; then
            print_verbose "Skipping (not found): $relative_path"
            return 0
        fi

        local dest="$snapshot_dir/files/$relative_path"
        local dest_dir
        dest_dir=$(dirname "$dest")

        mkdir -p "$dest_dir"
        cp -P "$source" "$dest"
        print_verbose "Backed up: $relative_path"
    }

    # Backup config
    backup_file "$project_root/.claude/hooks-daemon.yaml" "config/hooks-daemon.yaml"

    # Backup settings.json
    backup_file "$project_root/.claude/settings.json" "config/settings.json"

    # Backup init.sh
    backup_file "$project_root/.claude/init.sh" "init/init.sh"

    # Backup hook scripts
    if [ -d "$project_root/.claude/hooks" ]; then
        local hook_files
        hook_files=$(find "$project_root/.claude/hooks" -maxdepth 1 -type f -o -type l)

        for hook_file in $hook_files; do
            local hook_name
            hook_name=$(basename "$hook_file")
            backup_file "$hook_file" "hooks/$hook_name"
        done
    fi

    # Backup root .gitignore (extract daemon-specific entries)
    if [ -f "$project_root/.gitignore" ]; then
        if [ "$install_mode" = "self-install" ]; then
            grep -F "/untracked/" "$project_root/.gitignore" > "$snapshot_dir/files/gitignore/root.gitignore" 2>/dev/null || true
        else
            grep -F ".claude/hooks-daemon" "$project_root/.gitignore" > "$snapshot_dir/files/gitignore/root.gitignore" 2>/dev/null || true
        fi
    fi

    # Backup venv package list
    if [ -f "$venv_python" ]; then
        local venv_pip
        venv_pip="$(dirname "$venv_python")/pip"
        if [ -f "$venv_pip" ]; then
            "$venv_pip" freeze > "$snapshot_dir/files/venv/requirements.txt" 2>/dev/null || true
        fi
    fi

    print_success "State snapshot created: $snapshot_id"
    echo "$snapshot_id"
    return 0
}

#
# restore_state_snapshot() - Restore state from snapshot
#
# Atomically restores state from snapshot:
# 1. Git checkout to snapshot ref
# 2. Restore config files
# 3. Restore hook scripts
# 4. Restore init.sh
# 5. Recreate venv (if needed)
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - snapshot_id: Snapshot ID to restore
#   $4 - install_mode: "self-install" or "normal"
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
restore_state_snapshot() {
    local project_root="$1"
    local daemon_dir="$2"
    local snapshot_id="$3"
    local install_mode="$4"

    if [ -z "$project_root" ] || [ -z "$daemon_dir" ] || [ -z "$snapshot_id" ]; then
        print_error "restore_state_snapshot: project_root, daemon_dir, and snapshot_id required"
        return 1
    fi

    local snapshot_base
    snapshot_base=$(get_snapshot_dir "$daemon_dir")
    local snapshot_dir="$snapshot_base/$snapshot_id"

    if [ ! -d "$snapshot_dir" ]; then
        print_error "Snapshot not found: $snapshot_id"
        return 1
    fi

    print_info "Restoring state from snapshot: $snapshot_id"

    # Read manifest
    local manifest="$snapshot_dir/manifest.json"
    if [ ! -f "$manifest" ]; then
        print_error "Snapshot manifest not found: $manifest"
        return 1
    fi

    # Extract git ref from manifest (simple grep since we control the format)
    local git_ref
    git_ref=$(grep '"git_ref"' "$manifest" | sed 's/.*": "\(.*\)".*/\1/')

    # Restore git ref (checkout to previous version)
    if [ -d "$daemon_dir/.git" ] && [ "$git_ref" != "unknown" ]; then
        print_info "Checking out git ref: $git_ref"
        if ! git -C "$daemon_dir" checkout "$git_ref" 2>/dev/null; then
            print_error "Failed to checkout git ref: $git_ref"
            return 1
        fi
        print_success "Git checkout complete"
    fi

    # Restore config
    if [ -f "$snapshot_dir/files/config/hooks-daemon.yaml" ]; then
        cp "$snapshot_dir/files/config/hooks-daemon.yaml" "$project_root/.claude/hooks-daemon.yaml"
        print_verbose "Restored: hooks-daemon.yaml"
    fi

    # Restore settings.json
    if [ -f "$snapshot_dir/files/config/settings.json" ]; then
        cp "$snapshot_dir/files/config/settings.json" "$project_root/.claude/settings.json"
        print_verbose "Restored: settings.json"
    fi

    # Restore init.sh
    if [ -f "$snapshot_dir/files/init/init.sh" ]; then
        cp "$snapshot_dir/files/init/init.sh" "$project_root/.claude/init.sh"
        print_verbose "Restored: init.sh"
    fi

    # Restore hook scripts
    if [ -d "$snapshot_dir/files/hooks" ]; then
        local hook_files
        hook_files=$(find "$snapshot_dir/files/hooks" -maxdepth 1 -type f -o -type l 2>/dev/null)

        for hook_file in $hook_files; do
            local hook_name
            hook_name=$(basename "$hook_file")
            cp -P "$hook_file" "$project_root/.claude/hooks/$hook_name"
            print_verbose "Restored: hooks/$hook_name"
        done
    fi

    print_success "State restored from snapshot: $snapshot_id"
    print_warning "Venv may need to be recreated - run upgrade script or install dependencies"

    return 0
}

#
# list_snapshots() - List available snapshots
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Prints snapshot list to stdout
#   Exit code 0 on success
#
list_snapshots() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        print_error "list_snapshots: daemon_dir required"
        return 1
    fi

    local snapshot_base
    snapshot_base=$(get_snapshot_dir "$daemon_dir")

    if [ ! -d "$snapshot_base" ]; then
        print_info "No snapshots found (directory does not exist)"
        return 0
    fi

    local snapshots
    snapshots=$(find "$snapshot_base" -mindepth 1 -maxdepth 1 -type d | sort -r)

    if [ -z "$snapshots" ]; then
        print_info "No snapshots found"
        return 0
    fi

    print_info "Available snapshots:"
    for snapshot_dir in $snapshots; do
        local snapshot_id
        snapshot_id=$(basename "$snapshot_dir")

        local manifest="$snapshot_dir/manifest.json"
        if [ -f "$manifest" ]; then
            local timestamp
            timestamp=$(grep '"timestamp"' "$manifest" | sed 's/.*": "\(.*\)".*/\1/' || echo "unknown")
            local git_ref
            git_ref=$(grep '"git_ref"' "$manifest" | sed 's/.*": "\(.*\)".*/\1/' | cut -c1-8 || echo "unknown")

            echo "  $snapshot_id - $timestamp (git: $git_ref)"
        else
            echo "  $snapshot_id - (manifest missing)"
        fi
    done

    return 0
}

#
# cleanup_old_snapshots() - Remove old snapshots
#
# Keeps the N most recent snapshots, removes older ones.
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - keep_count (optional, default: 3)
#        Number of snapshots to keep
#
# Returns:
#   Exit code 0 on success
#
cleanup_old_snapshots() {
    local daemon_dir="$1"
    local keep_count="${2:-3}"

    if [ -z "$daemon_dir" ]; then
        print_error "cleanup_old_snapshots: daemon_dir required"
        return 1
    fi

    local snapshot_base
    snapshot_base=$(get_snapshot_dir "$daemon_dir")

    if [ ! -d "$snapshot_base" ]; then
        print_verbose "No snapshot directory to clean up"
        return 0
    fi

    local snapshots
    snapshots=$(find "$snapshot_base" -mindepth 1 -maxdepth 1 -type d | sort -r)

    if [ -z "$snapshots" ]; then
        print_verbose "No snapshots to clean up"
        return 0
    fi

    local snapshot_count
    snapshot_count=$(echo "$snapshots" | wc -l)

    if [ "$snapshot_count" -le "$keep_count" ]; then
        print_verbose "Only $snapshot_count snapshots, keeping all (threshold: $keep_count)"
        return 0
    fi

    local to_remove=$((snapshot_count - keep_count))
    print_info "Removing $to_remove old snapshot(s), keeping $keep_count most recent"

    local removed_count=0
    local snapshot_index=0

    for snapshot_dir in $snapshots; do
        snapshot_index=$((snapshot_index + 1))

        # Skip the first keep_count snapshots
        if [ $snapshot_index -le "$keep_count" ]; then
            continue
        fi

        local snapshot_id
        snapshot_id=$(basename "$snapshot_dir")

        rm -rf "$snapshot_dir"
        print_verbose "Removed snapshot: $snapshot_id"
        removed_count=$((removed_count + 1))
    done

    print_success "Removed $removed_count old snapshot(s)"
    return 0
}

#
# get_latest_snapshot() - Get ID of most recent snapshot
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#
# Returns:
#   Prints snapshot ID to stdout
#   Exit code 0 if snapshot found, 1 if none exist
#
get_latest_snapshot() {
    local daemon_dir="$1"

    if [ -z "$daemon_dir" ]; then
        return 1
    fi

    local snapshot_base
    snapshot_base=$(get_snapshot_dir "$daemon_dir")

    if [ ! -d "$snapshot_base" ]; then
        return 1
    fi

    local latest
    latest=$(find "$snapshot_base" -mindepth 1 -maxdepth 1 -type d | sort -r | head -1)

    if [ -z "$latest" ]; then
        return 1
    fi

    basename "$latest"
    return 0
}
