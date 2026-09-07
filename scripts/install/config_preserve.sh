#!/bin/bash
#
# config_preserve.sh - Config preservation for upgrades
#
# Wraps the Python config diff/merge/validate CLI commands to provide
# config preservation during upgrades. Follows the "Upgrade = Clean
# Reinstall + Config Preservation" philosophy.
#
# Usage:
#   source "$(dirname "$0")/install/config_preserve.sh"
#   backup_config "$PROJECT_ROOT"
#   extract_custom_config "$VENV_PYTHON" "$USER_CONFIG" "$DEFAULT_CONFIG"
#   merge_custom_config "$VENV_PYTHON" "$USER_CONFIG" "$OLD_DEFAULT" "$NEW_DEFAULT"
#   validate_merged_config "$VENV_PYTHON" "$MERGED_CONFIG"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Basename prefix of the temp baseline copy resolve_old_default_config makes.
# It is the ONLY thing that distinguishes our own copy from the path Layer 1
# handed over, which cleanup_old_default_config must never delete.
OLD_DEFAULT_TMP_PREFIX="hooks_daemon_old_default_"

#
# backup_config() - Create timestamped backup of config file
#
# Creates a backup copy of the config file with timestamp suffix.
# Safe to call if config file doesn't exist (returns 0).
#
# Args:
#   $1 - project_root: Path to project root
#   $2 - backup_dir (optional): Directory for backup file
#        Defaults to same directory as config file
#
# Returns:
#   Prints backup file path to stdout
#   Exit code 0 on success, 1 on failure
#
backup_config() {
    local project_root="$1"
    local backup_dir="${2:-}"

    if [ -z "$project_root" ]; then
        print_error "backup_config: project_root parameter required"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    if [ ! -f "$config_file" ]; then
        print_verbose "No config file to backup: $config_file"
        return 0
    fi

    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)

    local backup_file
    if [ -n "$backup_dir" ]; then
        mkdir -p "$backup_dir"
        backup_file="$backup_dir/hooks-daemon.yaml.backup-${timestamp}"
    else
        backup_file="${config_file}.backup-${timestamp}"
    fi

    cp "$config_file" "$backup_file"
    print_success "Config backed up to: $backup_file" >&2
    echo "$backup_file"
    return 0
}

#
# run_with_split_streams() - Run a command with its two output streams APART.
#
# Every caller below parses the command's stdout as JSON, and `2>&1` folds
# diagnostics into it. The exit code is checked first, so the folded capture
# only ever bit when the command SUCCEEDED and also wrote to stderr: one
# deprecation notice prefixes the payload, `json.loads` rejects it, and the
# upgrade reports "Failed to write merged config" for a run that worked. The
# user is told their customisations were lost when they were not.
#
# Diagnostics are kept, not dropped -- CLI_STDERR is the caller's to relay
# (relay_cli_diagnostics) or to quote in a failure message.
#
# Args:
#   $@ - the command and its arguments
#
# Sets:
#   CLI_STDOUT - the command's stdout, with no diagnostics mixed in
#   CLI_STDERR - the command's stderr
#
# Returns:
#   The command's own exit code.
#
# MUST NOT be called inside a command substitution or on either side of a
# pipeline: both run it in a SUBSHELL, where the two assignments are discarded
# and the caller silently reads stale values. Feed stdin with a herestring
# (`<<< "$payload"`) rather than a pipe.
#
run_with_split_streams() {
    local stderr_file
    stderr_file=$(mktemp "${TMPDIR:-/tmp}/hooks_daemon_cli_stderr_XXXXXX")

    CLI_STDOUT=$("$@" 2>"$stderr_file")
    local exit_code=$?

    CLI_STDERR=$(cat "$stderr_file")
    rm -f "$stderr_file"
    return $exit_code
}

#
# relay_cli_diagnostics() - Pass a command's stderr through to the user.
#
# Splitting the streams keeps the payload parseable; it must not also make the
# command's own warnings disappear, which would trade a loud wrong answer for
# a silent one.
#
# Args:
#   $1 - diagnostics: the captured stderr (may be empty)
#
relay_cli_diagnostics() {
    local diagnostics="${1:-}"

    if [ -n "$diagnostics" ]; then
        printf '%s\n' "$diagnostics" >&2
    fi
}

#
# resolve_old_default_config() - Resolve the diff baseline: the default config
# shipped by the version being upgraded FROM.
#
# The baseline decides whether a user's value is a CUSTOMISATION or merely the
# previous default they never touched, and those two are identical at the data
# level -- only the baseline separates them. Get it wrong in the "new default"
# direction and every accepted default looks deliberate, so it is preserved and
# the new default never reaches the user. That failure is silent and looks
# exactly like honouring a customisation.
#
# Two callers, two situations:
#
#   - Via Layer 1 (upgrade.sh, the documented path): Layer 1 has ALREADY
#     checked out the target before invoking Layer 2, so the example config on
#     disk here is the NEW default. Layer 1 therefore preserves the old one
#     before its checkout and hands the path over in
#     HOOKS_DAEMON_OLD_DEFAULT_CONFIG.
#   - Direct Layer 2 invocation: Step 5 genuinely does run before Step 6, so
#     the on-disk example IS the old default and the fallback is correct.
#
# Fails open: a stale or unreadable handover falls back to the on-disk example
# rather than losing the baseline entirely.
#
# Args:
#   $1 - example_config: Path to the on-disk .claude/hooks-daemon.yaml.example
#
# Returns:
#   Prints the baseline path to stdout (empty when no baseline exists at all --
#   a fresh install has no previous example, which is not an error).
#   Exit code 0.
#
resolve_old_default_config() {
    local example_config="${1:-}"
    local handover="${HOOKS_DAEMON_OLD_DEFAULT_CONFIG:-}"

    if [ -n "$handover" ] && [ -f "$handover" ]; then
        warn_if_baseline_handover_looks_stale "$handover"
        print_verbose "Using pre-checkout diff baseline: $handover" >&2
        echo "$handover"
        return 0
    fi

    if [ -n "$handover" ]; then
        print_warning "Handed-over diff baseline is missing: $handover" >&2
        print_info "Falling back to the on-disk example config." >&2
    fi

    if [ -n "$example_config" ] && [ -f "$example_config" ]; then
        local baseline
        baseline=$(mktemp "${TMPDIR:-/tmp}/${OLD_DEFAULT_TMP_PREFIX}XXXXXX.yaml")
        cp "$example_config" "$baseline"
        echo "$baseline"
        return 0
    fi

    echo ""
    return 0
}

#
# warn_if_baseline_handover_looks_stale() - Say so when the handover may be
# left over from an earlier upgrade.
#
# The handover is an EXPORTED path, and an export outlives the run that set
# it. Re-running the upgrade in the same shell, or invoking Layer 2 directly
# after a Layer 1 run, therefore hands over the PREVIOUS upgrade's baseline —
# a real config file that passes every check, so the wrong baseline is used
# without a word. The misclassification it causes (an accepted old default
# read as a deliberate customisation) is invisible by construction, so saying
# something is the only available defence.
#
# The only signal that separates "my caller preserved this" from "this was
# lying around in someone's shell" is whether the process that made it is
# still running -- Layer 1 waits for Layer 2, so a live owner is the
# documented path and a dead one is a leftover. PID reuse could mask a stale
# handover; that costs a warning, never a wrong answer.
#
# Deliberately advisory: the baseline is still USED. Refusing it would break
# the documented path on any false negative (no `ps`, a recycled PID), and
# this resolver's contract is to fail open.
#
# Args:
#   $1 - handover: the handed-over baseline path
#
warn_if_baseline_handover_looks_stale() {
    local handover="$1"
    local owner="${HOOKS_DAEMON_OLD_DEFAULT_PID:-}"

    case "$owner" in
        '' | *[!0-9]*)
            print_warning "Diff baseline handed over with no owning upgrade process: $handover" >&2
            print_info "If this is a leftover export, unset HOOKS_DAEMON_OLD_DEFAULT_CONFIG and re-run." >&2
            return 0
            ;;
    esac

    if ps -p "$owner" > /dev/null; then
        return 0
    fi

    print_warning "Diff baseline was handed over by process $owner, which has exited: $handover" >&2
    print_info "That looks like a stale export from an earlier upgrade, so this baseline may be the wrong version." >&2
    print_info "Unset HOOKS_DAEMON_OLD_DEFAULT_CONFIG and re-run to use the on-disk example instead." >&2
}

#
# cleanup_old_default_config() - Remove the baseline copy THIS module made.
#
# resolve_old_default_config returns one of two things and its caller cannot
# tell them apart: a temp copy of the on-disk example (ours to delete) or the
# path Layer 1 handed over (Layer 1's, cleaned up by its own EXIT trap). The
# mktemp prefix is what separates them, so the ownership rule lives here
# rather than in every caller.
#
# Args:
#   $1 - baseline: the path resolve_old_default_config returned (may be empty)
#
# Returns:
#   Exit code 0 always -- cleanup must never be the thing that fails an
#   upgrade, and it runs from an EXIT trap where a non-zero return is noise.
#
cleanup_old_default_config() {
    local baseline="${1:-}"

    [ -n "$baseline" ] || return 0
    [ "$baseline" != "${HOOKS_DAEMON_OLD_DEFAULT_CONFIG:-}" ] || return 0

    case "$(basename "$baseline")" in
        "$OLD_DEFAULT_TMP_PREFIX"*) rm -f "$baseline" ;;
    esac

    return 0
}

#
# extract_custom_config() - Extract user customizations from config
#
# Calls the Python config-diff CLI to compare user config against
# the default config and extract customizations.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - user_config: Path to user's current config YAML
#   $3 - default_config: Path to default/example config YAML
#
# Returns:
#   Prints JSON diff result to stdout
#   Exit code 0 on success, 1 on failure
#
extract_custom_config() {
    local venv_python="$1"
    local user_config="$2"
    local default_config="$3"

    if [ -z "$venv_python" ] || [ -z "$user_config" ] || [ -z "$default_config" ]; then
        print_error "extract_custom_config: venv_python, user_config, and default_config required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    if [ ! -f "$user_config" ]; then
        print_error "User config not found: $user_config"
        return 1
    fi

    if [ ! -f "$default_config" ]; then
        print_error "Default config not found: $default_config"
        return 1
    fi

    print_verbose "Extracting customizations from config..."

    if ! run_with_split_streams \
        "$venv_python" -m claude_code_hooks_daemon.daemon.cli config-diff \
        "$user_config" "$default_config"; then
        print_error "Config diff failed: ${CLI_STDERR:-$CLI_STDOUT}"
        return 1
    fi

    relay_cli_diagnostics "$CLI_STDERR"
    print_verbose "Config customizations extracted"
    echo "$CLI_STDOUT"
    return 0
}

#
# merge_custom_config() - Merge user customizations onto new default
#
# Calls the Python config-merge CLI to:
# 1. Diff user config vs old default to extract customizations
# 2. Apply customizations onto new default config
# 3. Return merged config + any conflicts
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - user_config: Path to user's current config YAML
#   $3 - old_default_config: Path to default config from current version
#   $4 - new_default_config: Path to default config from new version
#   $5 - output_file (optional): Path to write merged YAML config
#        If provided, extracts merged_config from JSON and writes as YAML
#
# Returns:
#   Prints JSON merge result to stdout (includes merged_config, conflicts, is_clean)
#   Exit code 0 on success, 1 on failure
#
merge_custom_config() {
    local venv_python="$1"
    local user_config="$2"
    local old_default_config="$3"
    local new_default_config="$4"
    local output_file="${5:-}"

    if [ -z "$venv_python" ] || [ -z "$user_config" ] || [ -z "$old_default_config" ] || [ -z "$new_default_config" ]; then
        print_error "merge_custom_config: venv_python, user_config, old_default_config, and new_default_config required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    for config_file in "$user_config" "$old_default_config" "$new_default_config"; do
        if [ ! -f "$config_file" ]; then
            print_error "Config file not found: $config_file"
            return 1
        fi
    done

    print_info "Merging config customizations onto new default..."

    if ! run_with_split_streams \
        "$venv_python" -m claude_code_hooks_daemon.daemon.cli config-merge \
        "$user_config" "$old_default_config" "$new_default_config"; then
        print_error "Config merge failed: ${CLI_STDERR:-$CLI_STDOUT}"
        return 1
    fi

    relay_cli_diagnostics "$CLI_STDERR"
    local merge_output="$CLI_STDOUT"

    # If output_file specified, extract merged_config and write as YAML.
    #
    # The JSON arrives on STDIN and the destination on ARGV. Neither may be
    # interpolated into the Python source: a config value is arbitrary user
    # text, and pasting it into a `'''...'''` literal means Python's tokenizer
    # decodes it BEFORE json.loads ever sees it. A regex option such as
    # `^pip\b` was halved to a real backspace and written to the config
    # silently; `v\d+\.\d+` was not a legal JSON escape at all and aborted the
    # upgrade; a value containing `'''` closed the literal and reached the
    # interpreter as code.
    #
    # The JSON reaches the writer on a HERESTRING rather than a pipe: a pipe
    # would run run_with_split_streams in a subshell, where CLI_STDOUT and
    # CLI_STDERR are set and then thrown away.
    if [ -n "$output_file" ]; then
        if ! run_with_split_streams "$venv_python" -c "
import json, sys, yaml
data = json.loads(sys.stdin.read())
merged = data.get('merged_config', {})
with open(sys.argv[1], 'w') as f:
    yaml.dump(merged, f, default_flow_style=False, sort_keys=False)
print('OK')
" "$output_file" <<< "$merge_output"; then
            print_error "Failed to write merged config: ${CLI_STDERR:-$CLI_STDOUT}"
            return 1
        fi

        relay_cli_diagnostics "$CLI_STDERR"

        if [ "$CLI_STDOUT" != "OK" ]; then
            print_error "Failed to write merged config: $CLI_STDOUT"
            return 1
        fi

        print_success "Merged config written to: $output_file"
    fi

    echo "$merge_output"
    return 0
}

#
# validate_merged_config() - Validate config against Pydantic schema
#
# Calls the Python config-validate CLI to validate a config file.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - config_path: Path to config YAML to validate
#
# Returns:
#   Prints JSON validation result to stdout
#   Exit code 0 if valid, 1 if invalid or error
#
validate_merged_config() {
    local venv_python="$1"
    local config_path="$2"

    if [ -z "$venv_python" ] || [ -z "$config_path" ]; then
        print_error "validate_merged_config: venv_python and config_path required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    if [ ! -f "$config_path" ]; then
        print_error "Config file not found: $config_path"
        return 1
    fi

    print_verbose "Validating merged config..."

    if ! run_with_split_streams \
        "$venv_python" -m claude_code_hooks_daemon.daemon.cli config-validate \
        "$config_path"; then
        print_warning "Config validation found issues"
        relay_cli_diagnostics "$CLI_STDERR"
        echo "$CLI_STDOUT"
        return 1
    fi

    relay_cli_diagnostics "$CLI_STDERR"
    print_success "Config validation passed"
    echo "$CLI_STDOUT"
    return 0
}

#
# report_incompatibilities() - Display user-friendly conflict report
#
# Parses JSON merge output and displays human-readable report
# of any conflicts or incompatibilities found during merge.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - merge_json: JSON string from merge_custom_config output
#
# Returns:
#   Exit code 0 if no conflicts (is_clean=true)
#   Exit code 1 if conflicts exist (is_clean=false)
#
report_incompatibilities() {
    local venv_python="$1"
    local merge_json="$2"

    if [ -z "$venv_python" ] || [ -z "$merge_json" ]; then
        print_error "report_incompatibilities: venv_python and merge_json required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    # As in merge_custom_config: the JSON arrives on stdin, never inside a
    # Python literal. A conflict record carries the user's own config value,
    # so interpolating it here meant a regex option could abort the very
    # report that exists to tell the user their value was not applied.
    # Herestring, not a pipe: see the note in merge_custom_config. The exit
    # code IS the answer here (0 clean / 1 conflicts), so it is captured
    # rather than tested -- `if !` would collapse it to a plain boolean.
    local exit_code=0
    run_with_split_streams "$venv_python" -c "
import json, sys

data = json.loads(sys.stdin.read())
is_clean = data.get('is_clean', True)
conflicts = data.get('conflicts', [])

if is_clean:
    print('No conflicts found - config merge was clean.')
    sys.exit(0)

print(f'Found {len(conflicts)} conflict(s) during config merge:')
print('')

for i, conflict in enumerate(conflicts, 1):
    path = conflict.get('path', 'unknown')
    ctype = conflict.get('conflict_type', 'unknown')
    desc = conflict.get('description', '')
    user_val = conflict.get('user_value')
    default_val = conflict.get('default_value')

    print(f'  {i}. [{ctype}] {path}')
    print(f'     {desc}')
    if user_val is not None:
        print(f'     Your value: {user_val}')
    if default_val is not None:
        print(f'     New default: {default_val}')
    print('')

print('Review merged config and adjust manually if needed.')
sys.exit(1)
" <<< "$merge_json" || exit_code=$?

    relay_cli_diagnostics "$CLI_STDERR"
    echo "$CLI_STDOUT"
    return $exit_code
}

#
# preserve_config_for_upgrade() - Complete config preservation workflow
#
# High-level function that performs the full config preservation flow:
# 1. Backup current config
# 2. Extract customizations (diff against old default)
# 3. Merge customizations onto new default
# 4. Validate merged config
# 5. Report any incompatibilities
# 6. Write merged config to destination
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - project_root: Path to project root
#   $3 - old_default_config: Path to default config from current version
#   $4 - new_default_config: Path to default config from new version
#   $5 - backup_dir (optional): Directory for backup file
#
# Returns:
#   Exit code 0 on success (clean merge or merge with warnings)
#   Exit code 1 on failure
#
preserve_config_for_upgrade() {
    local venv_python="$1"
    local project_root="$2"
    local old_default_config="$3"
    local new_default_config="$4"
    local backup_dir="${5:-}"

    if [ -z "$venv_python" ] || [ -z "$project_root" ] || [ -z "$old_default_config" ] || [ -z "$new_default_config" ]; then
        print_error "preserve_config_for_upgrade: venv_python, project_root, old_default_config, and new_default_config required"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    # If no user config exists, just copy new default
    if [ ! -f "$config_file" ]; then
        print_info "No existing config - using new default"
        cp "$new_default_config" "$config_file"
        print_success "Default config installed"
        return 0
    fi

    # Step 1: Backup
    print_info "Step 1/5: Backing up current config..."
    local backup_path
    backup_path=$(backup_config "$project_root" "$backup_dir")

    # Step 2: Merge (includes diff + apply)
    print_info "Step 2/5: Merging customizations onto new default..."
    local merge_output
    merge_output=$(merge_custom_config "$venv_python" "$config_file" "$old_default_config" "$new_default_config" "$config_file")
    local merge_exit=$?

    if [ $merge_exit -ne 0 ]; then
        print_error "Config merge failed"
        # Restore backup
        if [ -n "$backup_path" ] && [ -f "$backup_path" ]; then
            cp "$backup_path" "$config_file"
            print_warning "Restored config from backup"
        fi
        return 1
    fi

    # Step 3: Validate
    print_info "Step 3/5: Validating merged config..."
    local validate_output
    validate_output=$(validate_merged_config "$venv_python" "$config_file")
    local validate_exit=$?

    if [ $validate_exit -ne 0 ]; then
        print_warning "Merged config has validation issues"
        echo "$validate_output"
        # Don't restore backup - let user see the merged config
        # They can manually fix or use the backup
        print_info "Backup available at: $backup_path"
    else
        print_success "Merged config is valid"
    fi

    # Step 4: Report incompatibilities
    print_info "Step 4/5: Checking for conflicts..."
    report_incompatibilities "$venv_python" "$merge_output"
    local report_exit=$?

    # Step 4a: Detect and document breaking changes
    print_info "Step 4a/5: Detecting breaking changes..."
    local migration_notes="$project_root/.claude/config-migration-notes.txt"

    # Same contract as the two blocks above: JSON on stdin, paths on argv.
    # This site is the one a behavioural test is least likely to catch: the
    # `try` below and the sanctioned exit-code suppression on the closing line
    # turn a failure into a SKIPPED breaking-changes report rather than a
    # visible error — and that report is what warns before a change lands.
    if ! printf '%s' "$merge_output" | "$venv_python" -c "
import json
import sys
from pathlib import Path
from datetime import datetime

try:
    from claude_code_hooks_daemon.install.breaking_changes_detector import BreakingChangesDetector

    old_default_config, migration_notes = sys.argv[1], sys.argv[2]

    # Determine current and target versions
    daemon_dir = Path(old_default_config).parent.parent.parent
    changelog_path = daemon_dir / 'CHANGELOG.md'

    if not changelog_path.exists():
        sys.exit(0)

    # Parse merge output to get config diff
    merge_data = json.loads(sys.stdin.read())
    conflicts = merge_data.get('conflicts', [])

    # Look for handler removal/rename conflicts
    removed_handlers = []
    renamed_handlers = {}

    for conflict in conflicts:
        path = conflict.get('path', '')
        conflict_type = conflict.get('conflict_type', '')

        if 'handlers.' in path and conflict_type in ('removed_in_new', 'value_changed'):
            # Extract handler name from path like 'handlers.pre_tool_use.validate_sitemap'
            parts = path.split('.')
            if len(parts) >= 3:
                handler_name = parts[2]
                removed_handlers.append(handler_name)

    if not removed_handlers and not renamed_handlers:
        sys.exit(0)

    # Generate warnings
    detector = BreakingChangesDetector(changelog_path)
    warnings = detector.generate_warnings(
        removed_handlers=removed_handlers,
        renamed_handlers=renamed_handlers
    )

    if warnings:
        # Write migration notes to file
        with open(migration_notes, 'w') as f:
            f.write('=' * 70 + '\n')
            f.write('Config Migration Notes\n')
            f.write('Generated: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '\n')
            f.write('=' * 70 + '\n')
            f.write('\n')
            f.write('BREAKING CHANGES DETECTED DURING UPGRADE\n')
            f.write('\n')
            for warning in warnings:
                f.write(warning + '\n')
                f.write('\n')
            f.write('ACTIONS TAKEN:\n')
            f.write('- Config automatically updated during merge\n')
            f.write('- Incompatible handlers removed or updated\n')
            f.write('- Config backup saved (see above for path)\n')
            f.write('\n')
            f.write('REVIEW:\n')
            f.write('- Check .claude/hooks-daemon.yaml for changes\n')
            f.write('- Verify daemon starts successfully\n')
            f.write('- See upgrade guides in CLAUDE/UPGRADES/ for details\n')

        print(f'✓ Migration notes written to {Path(migration_notes).name}', file=sys.stderr)

except Exception as e:
    print(f'WARNING: Breaking changes documentation failed: {e}', file=sys.stderr)
" "$old_default_config" "$migration_notes"; then
        # Documenting breaking changes is a best-effort, purely informational
        # step, so it must not abort an otherwise-successful upgrade. It is
        # still SAID OUT LOUD: the previous blanket suppression here hid the
        # interpreter error raised by this block's own interpolated source,
        # which is why the field report saw no migration notes and no reason.
        print_warning "Breaking-changes documentation step failed; continuing upgrade"
    fi

    # Step 5: Summary
    print_info "Step 5/5: Config preservation summary"

    if [ $report_exit -eq 0 ] && [ $validate_exit -eq 0 ]; then
        print_success "Config preserved cleanly - all customizations applied"
        if [ -f "$migration_notes" ]; then
            print_info "Migration notes: $migration_notes"
        fi
        return 0
    elif [ $validate_exit -eq 0 ]; then
        print_warning "Config preserved with conflicts (see above)"
        print_info "Backup: $backup_path"
        if [ -f "$migration_notes" ]; then
            print_info "Migration notes: $migration_notes"
        fi
        return 0
    else
        print_warning "Config preserved but has validation issues"
        print_info "Backup: $backup_path"
        print_info "You may need to manually adjust: $config_file"
        if [ -f "$migration_notes" ]; then
            print_info "Migration notes: $migration_notes"
        fi
        return 0
    fi
}
