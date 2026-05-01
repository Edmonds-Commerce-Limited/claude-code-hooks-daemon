#!/usr/bin/env bash
#
# check_canonical_callers.sh — Plan 00104 Phase 6 Task 6.1
#
# Static check: every shell script that iterates over a
# ``untracked/venv-*`` glob must either:
#   (a) be the canonical library at ``scripts/lib/resolve_venv.sh`` (it IS
#       the resolver, so the pattern is its definition),
#   (b) be a self-bootstrap script that cannot delegate (positive-include
#       allowlist below — chicken-and-egg case),
#   (c) carry an inline ``# canonical-resolver-exempt: <reason>`` marker
#       so the operator who added the exception is recorded in-place.
#
# This is the 11th ``run_all.sh`` gate. It guards Decision 7 (single source
# of truth for venv resolution) and prevents bit-rot of the DRY consolidation
# delivered in Phase 4.
#
# Usage:
#   scripts/qa/check_canonical_callers.sh [extra_file_or_dir ...]
#
# Extra arguments append to the scan scope — used by the static-check tests
# (tests/integration/test_canonical_callers_static_check.py) to point the
# checker at tmp_path fixtures without polluting the live repo.
#
# Exit codes:
#   0 — no unexempted violations found
#   1 — at least one violation; actionable directive printed to stderr (R24)

set -euo pipefail

# ----------------------------------------------------------------
# Repo-root resolution (BASH_SOURCE[0] — survives sourcing/aliases)
# ----------------------------------------------------------------
_CCC_SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
case "$_CCC_SCRIPT_DIR" in
    /*) ;;
    *) _CCC_SCRIPT_DIR="$PWD/$_CCC_SCRIPT_DIR" ;;
esac
# scripts/qa -> repo root
REPO_ROOT="${_CCC_SCRIPT_DIR%/*/*}"

# ----------------------------------------------------------------
# Allowlist + marker
# ----------------------------------------------------------------
# Files whose violation patterns are by-design (canonical library) or
# self-bootstrap (deployed independently of the daemon source tree).
ALLOWLIST=(
    "scripts/lib/resolve_venv.sh"
    "CLAUDE/UPGRADES/upgrade-template/verification.sh"
)

EXEMPT_MARKER='# canonical-resolver-exempt:'

# Match a ``for VAR in ... untracked/venv-*`` shell construct. The literal
# ``*`` in the pattern is escaped with ``\*`` so extended-regex doesn't
# interpret it as a quantifier. Catches both ``venv-*/bin/python`` and
# ``venv-*/bin/python3`` and any other ``untracked/venv-*`` iteration shape.
VIOLATION_PATTERN='for[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]+in[[:space:]].*untracked/venv-\*'

# ----------------------------------------------------------------
# Internal scan
# ----------------------------------------------------------------
violations=()

_ccc_check_file() {
    local file="$1"
    [ -f "$file" ] || return 0

    case "$file" in
        *.sh|*.bash) ;;
        *) return 0 ;;
    esac

    if ! grep -q -E "$VIOLATION_PATTERN" "$file"; then
        return 0
    fi

    local rel="${file#"$REPO_ROOT/"}"
    local allow
    for allow in "${ALLOWLIST[@]}"; do
        if [ "$rel" = "$allow" ]; then
            return 0
        fi
    done

    if grep -q -F "$EXEMPT_MARKER" "$file"; then
        return 0
    fi

    violations+=("$file")
}

# ----------------------------------------------------------------
# Scan the repo's authoritative shell-script roots
# ----------------------------------------------------------------
_ccc_scan_dir() {
    local dir="$1"
    [ -d "$dir" ] || return 0
    local f
    while IFS= read -r -d '' f; do
        _ccc_check_file "$f"
    done < <(find "$dir" -type f \( -name '*.sh' -o -name '*.bash' \) -print0 2>/dev/null)
}

_ccc_scan_dir "$REPO_ROOT/scripts"
_ccc_scan_dir "$REPO_ROOT/src"
_ccc_scan_dir "$REPO_ROOT/CLAUDE/UPGRADES"

# Top-level shell scripts (init.sh, etc.).
for top in "$REPO_ROOT"/*.sh "$REPO_ROOT"/*.bash; do
    [ -e "$top" ] && _ccc_check_file "$top"
done

# ----------------------------------------------------------------
# Extra paths from the command line (test fixtures)
# ----------------------------------------------------------------
for extra in "$@"; do
    if [ -d "$extra" ]; then
        _ccc_scan_dir "$extra"
    elif [ -f "$extra" ]; then
        _ccc_check_file "$extra"
    fi
done

# ----------------------------------------------------------------
# Report
# ----------------------------------------------------------------
if [ "${#violations[@]}" -eq 0 ]; then
    echo "check_canonical_callers: 0 violations"
    exit 0
fi

{
    echo "check_canonical_callers: ${#violations[@]} violation(s) found"
    echo ""
    for v in "${violations[@]}"; do
        echo "  $v"
    done
    echo ""
    echo "Each violating file iterates over a 'untracked/venv-*' glob directly,"
    echo "bypassing the canonical resolver at scripts/lib/resolve_venv.sh."
    echo ""
    echo "Fix: replace the loop with delegation to the canonical library:"
    echo "  source \"\${REPO_ROOT}/scripts/lib/resolve_venv.sh\""
    echo "  python_path=\"\$(resolve_venv_python \"\$DAEMON_DIR\")\""
    echo ""
    echo "If the file genuinely cannot delegate (self-bootstrap chicken-and-egg),"
    echo "add an inline exempt marker on the violating line or anywhere above:"
    echo "  # canonical-resolver-exempt: <reason>"
    echo ""
    echo "See Plan 00104 Phase 6 Task 6.1 / Decision 7."
} >&2

exit 1
