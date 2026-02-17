#!/bin/bash
#
# config_diff_analyzer.sh - Compare handler names between old and new configs
#
# This script compares handler names in two YAML config files and outputs
# a JSON report of removed, renamed (suggested), and added handlers.
#
# Used during upgrades to detect config incompatibilities before making changes.
#
# Usage:
#   bash config_diff_analyzer.sh <old_config> <new_config>
#
# Output Format (JSON):
#   {
#     "removed": ["handler1", "handler2"],
#     "renamed": {"old_name": "suggested_new_name"},
#     "added": ["handler3", "handler4"]
#   }
#
# Exit codes:
#   0 - Success (JSON output to stdout)
#   1 - Error (error message to stderr)
#

set -euo pipefail

# ============================================================
# Argument validation
# ============================================================

if [ $# -ne 2 ]; then
    echo "ERROR: Usage: $0 <old_config> <new_config>" >&2
    exit 1
fi

OLD_CONFIG="$1"
NEW_CONFIG="$2"

if [ ! -f "$OLD_CONFIG" ]; then
    echo "ERROR: Old config file not found: $OLD_CONFIG" >&2
    exit 1
fi

if [ ! -f "$NEW_CONFIG" ]; then
    echo "ERROR: New config file not found: $NEW_CONFIG" >&2
    exit 1
fi

# ============================================================
# Extract handler names from YAML
# ============================================================

# Extract all handler names from a config file
# Returns: newline-separated list of "event_type:handler_name"
extract_handlers() {
    local config_file="$1"

    # Use grep/awk to extract handler names from YAML structure
    # Pattern: handlers -> event_type -> handler_name

    # This parses YAML manually (simple but robust for our use case)
    awk '
        /^handlers:/ { in_handlers=1; next }
        in_handlers && /^[^ ]/ { in_handlers=0 }
        in_handlers && /^  [a-z_]+:/ {
            event_type=$1
            gsub(/:/, "", event_type)
            in_event=1
            next
        }
        in_event && /^    [a-z_]+:/ {
            handler=$1
            gsub(/:/, "", handler)
            print event_type ":" handler
        }
        in_event && /^  [a-z_]+:/ {
            in_event=0
        }
    ' "$config_file" | sort -u
}

# ============================================================
# Extract handlers
# ============================================================

OLD_HANDLERS=$(extract_handlers "$OLD_CONFIG")
NEW_HANDLERS=$(extract_handlers "$NEW_CONFIG")

# ============================================================
# Compute diffs
# ============================================================

# Handlers in old but not in new (removed)
REMOVED=()
while IFS= read -r handler; do
    [ -z "$handler" ] && continue
    if ! echo "$NEW_HANDLERS" | grep -qF "$handler"; then
        REMOVED+=("$handler")
    fi
done <<< "$OLD_HANDLERS"

# Handlers in new but not in old (added)
ADDED=()
while IFS= read -r handler; do
    [ -z "$handler" ] && continue
    if ! echo "$OLD_HANDLERS" | grep -qF "$handler"; then
        ADDED+=("$handler")
    fi
done <<< "$NEW_HANDLERS"

# ============================================================
# Fuzzy matching for renames (simple heuristic)
# ============================================================

# For each removed handler, check if there's a similar added handler
# This uses simple string similarity (common prefix/suffix)
RENAMED_MAP=()

for removed_handler in "${REMOVED[@]}"; do
    removed_name="${removed_handler#*:}"  # Strip event_type prefix
    event_type="${removed_handler%:*}"

    best_match=""
    best_score=0

    for added_handler in "${ADDED[@]}"; do
        added_name="${added_handler#*:}"
        added_event_type="${added_handler%:*}"

        # Only compare handlers from same event type
        [ "$event_type" != "$added_event_type" ] && continue

        # Simple similarity: count common characters
        # (This is a basic heuristic - Python fuzzy matching is better)
        common_len=$(echo "$removed_name" "$added_name" | awk '{
            len1 = length($1)
            len2 = length($2)
            min_len = (len1 < len2) ? len1 : len2
            common = 0
            for (i=1; i<=min_len; i++) {
                if (substr($1, i, 1) == substr($2, i, 1)) {
                    common++
                } else {
                    break
                }
            }
            print common
        }')

        # If >60% similar, consider it a potential rename
        removed_len=${#removed_name}
        if [ "$removed_len" -gt 0 ]; then
            score=$((common_len * 100 / removed_len))
            if [ "$score" -gt "$best_score" ] && [ "$score" -ge 60 ]; then
                best_score=$score
                best_match="$added_name"
            fi
        fi
    done

    if [ -n "$best_match" ]; then
        RENAMED_MAP+=("\"$removed_name\": \"$best_match\"")
    fi
done

# ============================================================
# Generate JSON output
# ============================================================

# Build removed array
removed_json="["
first=true
for handler in "${REMOVED[@]}"; do
    handler_name="${handler#*:}"
    if [ "$first" = true ]; then
        first=false
    else
        removed_json+=", "
    fi
    removed_json+="\"$handler_name\""
done
removed_json+="]"

# Build renamed object
renamed_json="{"
if [ ${#RENAMED_MAP[@]} -gt 0 ]; then
    first=true
    for mapping in "${RENAMED_MAP[@]}"; do
        if [ "$first" = true ]; then
            first=false
        else
            renamed_json+=", "
        fi
        renamed_json+="$mapping"
    done
fi
renamed_json+="}"

# Build added array
added_json="["
first=true
for handler in "${ADDED[@]}"; do
    handler_name="${handler#*:}"
    if [ "$first" = true ]; then
        first=false
    else
        added_json+=", "
    fi
    added_json+="\"$handler_name\""
done
added_json+="]"

# Output final JSON
cat <<EOF
{
  "removed": $removed_json,
  "renamed": $renamed_json,
  "added": $added_json
}
EOF

exit 0
