#!/bin/bash
#
# Run ALL QA checks in sequence
#
# Exit codes:
#   0 - All checks passed
#   1 - At least one check failed
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Resolve venv python via SSOT so fingerprint-keyed (v3.7.0+) and legacy
# (pre-v3.7.0) layouts are both honoured.
if [ -f "${PROJECT_ROOT}/scripts/install/venv_resolver.sh" ]; then
    # shellcheck source=../install/venv_resolver.sh
    source "${PROJECT_ROOT}/scripts/install/venv_resolver.sh"
fi
if declare -F resolve_existing_venv_python > /dev/null; then
    VENV_PYTHON="$(resolve_existing_venv_python "${PROJECT_ROOT}")"
else
    # FAIL FAST. Was: ${PROJECT_ROOT}/untracked/venv/bin/python  # python-var-guidance-exempt: names the retired path to explain its removal
    # — the pre-v3.7.0 layout, which exists on no install since venvs became
    # fingerprint-keyed. The fallback could therefore never succeed; it only
    # turned "the resolver is missing" into a confusing "no such file".
    echo "ERROR: venv resolver not available at ${PROJECT_ROOT}/scripts/install/venv_resolver.sh" >&2
    echo "       Cannot resolve the daemon virtualenv; reinstall or repair the daemon." >&2
    exit 2
fi

cd "${PROJECT_ROOT}"

echo "========================================"
echo "Running ALL QA Checks"
echo "========================================"
echo ""

# Track overall status
OVERALL_EXIT_CODE=0

# Run each check, capturing exit codes
echo "1. Running Magic Value Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_magic_values.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Magic value check FAILED"
else
    echo "✅ Magic value check PASSED"
fi
echo ""

echo "2. Running Format Check..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_format_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Format check FAILED"
else
    echo "✅ Format check PASSED"
fi
echo ""

echo "3. Running Linter..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_lint.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Linter FAILED"
else
    echo "✅ Linter PASSED"
fi
echo ""

echo "4. Running Type Checker..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_type_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Type checker FAILED"
else
    echo "✅ Type checker PASSED"
fi
echo ""

echo "5. Running Tests with Coverage..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_tests.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Tests FAILED"
else
    echo "✅ Tests PASSED"
fi
echo ""

echo "6. Running Security Check..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_security_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Security check FAILED"
else
    echo "✅ Security check PASSED"
fi
echo ""

echo "7. Running Dependency Check..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_dependency_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Dependency check FAILED"
else
    echo "✅ Dependency check PASSED"
fi
echo ""

echo "8. Running Shell Check..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_shell_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Shell check FAILED"
else
    echo "✅ Shell check PASSED"
fi
echo ""

echo "9. Running Error Hiding Audit..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/audit_error_hiding.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Error hiding audit FAILED"
else
    echo "✅ Error hiding audit PASSED"
fi
echo ""

echo "10. Running Skill Reference Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_skill_references.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Skill reference check FAILED"
else
    echo "✅ Skill reference check PASSED"
fi
echo ""

echo "11. Running Shell Audit..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/audit_shell.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Shell audit FAILED"
else
    echo "✅ Shell audit PASSED"
fi
echo ""

echo "12. Running Canonical-Caller Check..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_canonical_callers_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Canonical-caller check FAILED"
else
    echo "✅ Canonical-caller check PASSED"
fi
echo ""

echo "13. Running Capture-Corruption Audit..."
echo "----------------------------------------"
if ! "${SCRIPT_DIR}/run_capture_corruption_check.sh"; then
    OVERALL_EXIT_CODE=1
    echo "❌ Capture-corruption audit FAILED"
else
    echo "✅ Capture-corruption audit PASSED"
fi
echo ""

echo "14. Running Repo-Hygiene Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_repo_hygiene.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Repo-hygiene check FAILED"
else
    echo "✅ Repo-hygiene check PASSED"
fi
echo ""

echo "15. Running Doc-Truth Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_doc_truth.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Doc-truth check FAILED"
else
    echo "✅ Doc-truth check PASSED"
fi
echo ""

echo "16. Running Sensitive Content Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_sensitive_content.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Sensitive content check FAILED"
else
    echo "✅ Sensitive content check PASSED"
fi
echo ""

echo "17. Running Handler-Reference Check..."
echo "----------------------------------------"
if ! "${VENV_PYTHON}" "${SCRIPT_DIR}/check_handler_reference.py" --json; then
    OVERALL_EXIT_CODE=1
    echo "❌ Handler-reference check FAILED"
else
    echo "✅ Handler-reference check PASSED"
fi
echo ""

# Print overall summary
echo "========================================"
echo "QA Summary"
echo "========================================"
python3 << 'EOF'
import json
from pathlib import Path

results = {
    "Magic Values": "untracked/qa/magic_values.json",
    "Format Check": "untracked/qa/format.json",
    "Linter": "untracked/qa/lint.json",
    "Type Check": "untracked/qa/type_check.json",
    "Tests": "untracked/qa/tests.json",
    "Security Check": "untracked/qa/security.json",
    "Dependencies": "untracked/qa/dependencies.json",
    "Shell Check": "untracked/qa/shell_check.json",
    "Error Hiding": "untracked/qa/error_hiding.json",
    "Skill Refs": "untracked/qa/skill_references.json",
    "Shell Audit": "untracked/qa/shell_audit.json",
    "Canonical Callers": "untracked/qa/canonical_callers.json",
    "Capture Corruption": "untracked/qa/capture_corruption.json",
    "Repo Hygiene": "untracked/qa/repo_hygiene.json",
    "Doc Truth": "untracked/qa/doc_truth.json",
    "Sensitive Content": "untracked/qa/sensitive_content.json",
    "Handler Reference": "untracked/qa/handler_reference.json",
}

all_passed = True

for name, file_path in results.items():
    file_obj = Path(file_path)
    if file_obj.exists():
        with open(file_obj) as f:
            data = json.load(f)
            summary = data.get("summary", {})
            # For tests: use "passed_all" boolean. For others: use "passed" boolean
            if "passed_all" in summary:
                passed = summary["passed_all"]
            else:
                passed = summary.get("passed", False)

            status = "✅ PASSED" if passed else "❌ FAILED"
            print(f"  {name:20s}: {status}")

            if not passed:
                all_passed = False
    else:
        print(f"  {name:20s}: ⚠️  NO OUTPUT")
        all_passed = False

print("")
print(f"Overall Status: {'✅ ALL CHECKS PASSED' if all_passed else '❌ SOME CHECKS FAILED'}")

# Add sub-agent QA reminder if automated QA passes
if all_passed:
    print("")
    print("⚠️  IMPORTANT: Automated QA is complete, but full QA requires sub-agent review.")
    print("")
    print("Run QA sub-agents for architecture and quality review.")
    print("See CLAUDE/QA.md for complete workflow.")
EOF

echo ""
echo "Output files written to: untracked/qa/"
echo "========================================"

exit ${OVERALL_EXIT_CODE}
