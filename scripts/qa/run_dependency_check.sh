#!/bin/bash
#
# Run deptry dependency checker and output results to JSON
#
# Checks for:
#   DEP001 - Missing dependencies (imported but not declared)
#   DEP004 - Misplaced dev dependencies (dev dep used in production code)
#
# Exit codes:
#   0 - No dependency issues found
#   1 - Dependency issues found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# The QA_DEPENDENCY_* overrides exist so
# tests/unit/qa/test_run_dependency_check.py can drive this exact wrapper
# against a planted target, a fake deptry binary, and a forced "uv missing"
# branch without touching the real deptry invocation, the real uv on this
# host, or the real untracked/qa/ output. Unset, they change nothing
# (00466 N21).
OUTPUT_DIR="${QA_DEPENDENCY_OUTPUT_DIR:-${PROJECT_ROOT}/untracked/qa}"
OUTPUT_FILE="${OUTPUT_DIR}/dependencies.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import deptry" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "${OUTPUT_DIR}"

# Plan 00100 Task 3.0: uv.lock is a first-class repo artefact. CI-gate it so
# pyproject.toml drift without a regenerated lockfile surfaces immediately.
# `uv lock --check` exits non-zero when the lockfile is stale.
#
# 00466 N21: uv missing used to be a WARNING that let the run continue and
# report passed -- silently dropping this gate rather than failing it. uv is
# required to check the lockfile at all, so its absence is now a hard
# failure, same as a stale lockfile.
UV_AVAILABLE=true
if [ -n "${QA_DEPENDENCY_FORCE_NO_UV:-}" ] || ! command -v uv >/dev/null; then
    UV_AVAILABLE=false
fi

if [ "${UV_AVAILABLE}" = "true" ]; then
    echo "Running uv lock --check..."
    if ! uv lock --check; then
        echo "❌ uv.lock is out of sync with pyproject.toml." >&2
        echo "   Fix: run 'uv lock' and commit the updated uv.lock." >&2
        exit 1
    fi
else
    echo "❌ uv not on PATH -- cannot verify uv.lock is in sync with pyproject.toml." >&2
    echo "   Install uv (https://docs.astral.sh/uv/) to run this gate locally." >&2
    exit 1
fi

# Plan 00346 Task 2.1: the gate above proves the LOCK agrees with
# pyproject.toml. This proves the INSTALLED packages agree with the LOCK —
# two different claims, and only the first one was ever checked. A fresh,
# CI-gated lockfile sat beside a venv running mypy a whole major version
# ahead of it, and every QA gate stayed green.
echo "Checking the venv matches uv.lock..."
assert_venv_matches_lock || exit 1

echo "Running deptry dependency checker..."

DEPTRY_TARGET="${QA_DEPENDENCY_TARGETS:-src/}"
DEPTRY_BIN="${QA_DEPENDENCY_DEPTRY_BIN:-${VENV_DIR}/bin/deptry}"

# Run deptry on src/ only, capture output
# Only check DEP001 (missing) and DEP004 (misplaced) - the real issues
# DEP002 (unused) and DEP003 (transitive/self) are configured as ignored in pyproject.toml
#
# 00466 N21: deptry's own contract is 0 = clean, 1 = issues found; it
# writes its JSON output ONLY after a full, successful run. A CLI usage
# error (bad path, bad flag) exits 2 and writes no JSON at all, and the
# exit code is captured and checked below instead of discarded.
if "${DEPTRY_BIN}" "${DEPTRY_TARGET}" --json-output "${OUTPUT_FILE}.raw" 2>&1; then
    DEPTRY_EXIT=0
else
    DEPTRY_EXIT=$?
fi

if [ "${DEPTRY_EXIT}" != "0" ] && [ "${DEPTRY_EXIT}" != "1" ]; then
    DEPTRY_ERROR_MESSAGE="deptry exited ${DEPTRY_EXIT} (expected 0 or 1) -- it did not complete a check, so nothing below was actually checked"
    echo "FATAL: ${DEPTRY_ERROR_MESSAGE}" >&2
    "${VENV_PYTHON}" -c '
import json
import sys

message = sys.argv[1]
output_file = sys.argv[2]
summary = {
    "total_issues": 1,
    "missing_deps": 0,
    "misplaced_deps": 0,
    "passed": False,
    "error": message,
}
output = {
    "tool": "deptry",
    "summary": summary,
    "issues": [{
        "rule": "deptry-run-error",
        "module": "",
        "message": message,
    }],
}
with open(output_file, "w") as f:
    json.dump(output, f, indent=2)
    f.write("\n")
' "${DEPTRY_ERROR_MESSAGE}" "${OUTPUT_FILE}"
    rm -f "${OUTPUT_FILE}.raw"
    exit 1
fi
# Issues (if any) are captured as JSON in the output file for parsing below

# Parse deptry JSON output and transform to our format
"${VENV_PYTHON}" - "${OUTPUT_FILE}.raw" "${OUTPUT_FILE}" <<'PYEOF'
import json
import sys
from pathlib import Path

raw_file = Path(sys.argv[1])
output_file = Path(sys.argv[2])

# 00466 N21: deptry writes its JSON output file only after a full,
# successful run -- a missing (or empty) raw file means nothing was
# actually checked, and must not be read as "zero issues".
if not raw_file.exists() or raw_file.stat().st_size == 0:
    message = "deptry produced no JSON output -- nothing was checked"
    summary = {
        "total_issues": 1,
        "missing_deps": 0,
        "misplaced_deps": 0,
        "passed": False,
        "error": message,
    }
    output = {
        "tool": "deptry",
        "summary": summary,
        "issues": [{
            "rule": "deptry-run-error",
            "module": "",
            "message": message,
        }],
    }
    output_file.write_text(json.dumps(output, indent=2) + "\n")
    print(f"FATAL: {message}", file=sys.stderr)
    sys.exit(1)

try:
    with open(raw_file) as f:
        content = f.read().strip()
        issues_raw = json.loads(content) if content else []
except json.JSONDecodeError as exc:
    # FAIL FAST (Plan 00200 Task 1.5 / Phase 5 self-scan). This
    # previously swallowed the error into `issues_raw = []`, which made
    # `passed` True over an unreadable capture -- the same shape as the
    # run_lint.sh swallow that started this plan. Genuinely-empty output
    # is already handled by the st_size guard above, so anything
    # non-empty and unparseable is a defect, not a clean run.
    print(
        "FATAL: deptry output could not be parsed as JSON. The capture "
        "is corrupted -- something wrote to stdout alongside deptry.\n"
        f"  parse error: {exc}\n"
        f"  first 200 bytes: {content[:200]!r}",
        file=sys.stderr,
    )
    sys.exit(1)

# Transform to our format
issues = []
for item in issues_raw:
    violation_code = item.get("error", {}).get("code", "")
    violation_msg = item.get("error", {}).get("message", "")
    module = item.get("module", "")

    issues.append({
        "rule": violation_code,
        "module": module,
        "message": violation_msg,
    })

# Build summary
summary = {
    "total_issues": len(issues),
    "missing_deps": sum(1 for i in issues if i["rule"] == "DEP001"),
    "misplaced_deps": sum(1 for i in issues if i["rule"] == "DEP004"),
    "passed": len(issues) == 0,
}

output = {
    "tool": "deptry",
    "summary": summary,
    "issues": issues,
}

output_file.write_text(json.dumps(output, indent=2) + "\n")
PYEOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary
echo ""
echo "Dependency Check Results:"
"${VENV_PYTHON}" -c "
import json
import sys
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Total issues: {summary['total_issues']}\")
    print(f\"  Missing deps (DEP001): {summary['missing_deps']}\")
    print(f\"  Misplaced deps (DEP004): {summary['misplaced_deps']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
    sys.exit(0 if summary['passed'] else 1)
"
