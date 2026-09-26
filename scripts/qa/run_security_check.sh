#!/bin/bash
#
# Run Bandit security linter and output results to JSON
#
# Exit codes:
#   0 - No security issues found
#   1 - Security issues found
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# The QA_SECURITY_* overrides exist so tests/unit/qa/test_run_security_check.py
# can drive this exact wrapper against a planted target and a fake bandit
# binary without touching the real bandit invocation or the real
# untracked/qa/ output. Unset, they change nothing (00466 N21).
OUTPUT_DIR="${QA_SECURITY_OUTPUT_DIR:-${PROJECT_ROOT}/untracked/qa}"
OUTPUT_FILE="${OUTPUT_DIR}/security.json"

# Source venv management
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"

cd "${PROJECT_ROOT}"

# Ensure venv and deps
ensure_venv || exit 1
if ! "${VENV_PYTHON}" -c "import bandit" 2>/dev/null; then
    install_deps || exit 1
fi

# Ensure output directory exists
mkdir -p "${OUTPUT_DIR}"

echo "Running Bandit security scanner..."

BANDIT_TARGETS=("src/" ".claude/ccy/claude-supervise.py")
if [ -n "${QA_SECURITY_TARGETS:-}" ]; then
    BANDIT_TARGETS=("${QA_SECURITY_TARGETS}")
fi
BANDIT_BIN="${QA_SECURITY_BANDIT_BIN:-${VENV_DIR}/bin/bandit}"

# Run bandit with JSON output
# Note: Bandit uses -f json for JSON format, -r for recursive
# Skip ONLY test assertions (B101) - we run bandit on src/ not tests/
#
# 00466 N21: bandit puts a file it could NOT scan (syntax error, missing
# path, ...) into top-level errors[] and still exits 0 -- that file was
# never checked by any rule, so reading results[] alone cannot tell "clean"
# from "blind" (same shape as run_semgrep_check.sh's errors[] fix). A CLI
# usage error (bad flag, bad config) exits 2 and writes no output file at
# all. Both are captured below instead of discarded.
if "${BANDIT_BIN}" -r "${BANDIT_TARGETS[@]}" -f json -o "${OUTPUT_FILE}.raw" -s B101; then
    BANDIT_EXIT=0
else
    BANDIT_EXIT=$?
fi

# Parse bandit JSON output and transform to our format
"${VENV_PYTHON}" - "${OUTPUT_FILE}.raw" "${OUTPUT_FILE}" "${BANDIT_EXIT}" <<'PYEOF'
import json
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
bandit_exit = int(sys.argv[3])


def _fail_closed(message: str) -> None:
    """Write a report bandit's own exit code agrees with, then exit 1.

    A single issue entry is written alongside the count so llm_qa's
    "count implies detail" check (tests/unit/qa/test_llm_qa_count_implies_detail.py)
    holds even for a tool-level failure, not just a real finding.
    """
    summary = {
        "total_files_checked": 0,
        "total_issues": 1,
        "errors": 1,
        "warnings": 0,
        "info": 0,
        "passed": False,
        "error": message,
    }
    output = {
        "tool": "bandit",
        "summary": summary,
        "issues": [
            {
                "file": "",
                "line": 0,
                "column": 0,
                "rule": "bandit-run-error",
                "message": message,
                "severity": "error",
                "confidence": "",
            }
        ],
        "files": [],
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"FATAL: {message}", file=sys.stderr)
    sys.exit(1)


# Bandit's own contract: 0 = clean, 1 = issues found (at the configured
# severity/confidence). Anything else means bandit did not complete a scan
# at all -- a CLI usage error, a crash -- and any raw file it may have
# half-written cannot be trusted as a verdict.
if bandit_exit not in (0, 1):
    _fail_closed(
        f"bandit exited {bandit_exit} (expected 0 or 1) -- it did not complete "
        "a scan, so nothing below was actually checked"
    )

if not raw_path.exists():
    _fail_closed("bandit produced no output file -- nothing was checked")

bandit_output = {}
if raw_path.stat().st_size > 0:
    try:
        content = raw_path.read_text().strip()
        if content:
            bandit_output = json.loads(content)
    except json.JSONDecodeError as exc:
        # FAIL FAST (Plan 00200 Task 1.5 / Phase 5 self-scan). This
        # previously swallowed the error into `bandit_output = {}`, which
        # made `passed` True over an unreadable capture -- the same shape as
        # the run_lint.sh swallow that started this plan. Genuinely-empty
        # output is already handled by the st_size guard above, so anything
        # non-empty and unparseable is a defect, not a clean run.
        print(
            "FATAL: bandit output could not be parsed as JSON. The capture "
            "is corrupted -- something wrote to stdout alongside bandit.\n"
            f"  parse error: {exc}\n"
            f"  first 200 bytes: {content[:200]!r}",
            file=sys.stderr,
        )
        sys.exit(1)

# Extract results
results = bandit_output.get("results", [])
metrics = bandit_output.get("metrics", {})
# 00466 N21: files bandit could NOT scan -- syntax error, missing path, a
# rule that crashed on this file. Each was checked by nothing, so each is
# reported as an issue of its own: counted, listed under the same jq hint,
# and never mistaken for a clean scan.
scan_errors = bandit_output.get("errors", [])

# Transform to our format
issues = []
files_checked = set()

for item in results:
    file_path = item.get("filename", "")
    files_checked.add(file_path)

    # Map Bandit severity to our format
    severity_map = {
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "info",
    }
    bandit_severity = item.get("issue_severity", "MEDIUM")

    issues.append({
        "file": file_path,
        "line": item.get("line_number", 0),
        "column": 0,  # Bandit doesn't provide column numbers
        "rule": item.get("test_id", ""),
        "message": item.get("issue_text", ""),
        "severity": severity_map.get(bandit_severity, "warning"),
        "confidence": item.get("issue_confidence", ""),
    })

for scan_error in scan_errors:
    issues.append({
        "file": scan_error.get("filename", ""),
        "line": 0,
        "column": 0,
        "rule": "bandit-scan-error",
        "message": "bandit could NOT check this file: "
        + str(scan_error.get("reason", "")),
        "severity": "error",
        "confidence": "",
    })

# Calculate total files checked from metrics (if available)
total_files = len(files_checked)
if "_totals" in metrics:
    # Use Bandit's file count if available
    total_files = max(total_files, metrics["_totals"].get("loc", 0) // 100)  # Rough estimate

# Build summary - FAIL on ANY issue (HIGH, MEDIUM, or LOW) or scan error
summary = {
    "total_files_checked": total_files,
    "total_issues": len(issues),
    "errors": sum(1 for i in issues if i["severity"] == "error"),
    "warnings": sum(1 for i in issues if i["severity"] == "warning"),
    "info": sum(1 for i in issues if i["severity"] == "info"),
    "passed": len(issues) == 0,  # ZERO TOLERANCE - any issue or scan error fails
}
if scan_errors:
    summary["error"] = (
        f"bandit could not check {len(scan_errors)} file(s); a file that "
        "could not be scanned has checked nothing, so the gate fails closed"
    )

# Output final JSON
output = {
    "tool": "bandit",
    "summary": summary,
    "issues": issues,
    "files": sorted(list(files_checked)),
}

output_path.write_text(json.dumps(output, indent=2) + "\n")
PYEOF

# Clean up raw file
rm -f "${OUTPUT_FILE}.raw"

# Print summary and determine final exit code based on HIGH severity errors
echo ""
echo "Security Check Results:"
"${VENV_PYTHON}" -c "
import json
import sys
with open('${OUTPUT_FILE}') as f:
    data = json.load(f)
    summary = data['summary']
    print(f\"  Files checked: {summary['total_files_checked']}\")
    print(f\"  Total issues: {summary['total_issues']}\")
    print(f\"  Errors (HIGH): {summary['errors']}\")
    print(f\"  Warnings (MEDIUM): {summary['warnings']}\")
    print(f\"  Info (LOW): {summary['info']}\")
    print(f\"  Status: {'✅ PASSED' if summary['passed'] else '❌ FAILED'}\")
    # Exit 0 if passed (no HIGH severity), exit 1 if failed
    sys.exit(0 if summary['passed'] else 1)
"
