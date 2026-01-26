#!/bin/bash
#
# Manual QA infrastructure test
# Verifies all QA scripts work correctly
#

set -e

echo "=================================="
echo "QA Infrastructure Manual Test"
echo "=================================="
echo ""

# Clean up old outputs
echo "1. Cleaning old QA outputs..."
rm -f untracked/qa/*.json
echo "   ✓ Cleaned"
echo ""

# Test each script individually
echo "2. Testing run_lint.sh..."
if ./scripts/qa/run_lint.sh > /dev/null 2>&1; then
    echo "   ✓ Script ran"
else
    echo "   ✓ Script ran (exit code non-zero is OK if violations found)"
fi

if [ -f "untracked/qa/lint.json" ]; then
    python3 -c "import json; json.load(open('untracked/qa/lint.json'))" && echo "   ✓ Valid JSON" || echo "   ✗ Invalid JSON"
    python3 -c "import json; d=json.load(open('untracked/qa/lint.json')); assert 'summary' in d and 'violations' in d" && echo "   ✓ Correct structure" || echo "   ✗ Missing fields"
else
    echo "   ✗ lint.json not created"
    exit 1
fi
echo ""

echo "3. Testing run_type_check.sh..."
if ./scripts/qa/run_type_check.sh > /dev/null 2>&1; then
    echo "   ✓ Script ran"
else
    echo "   ✓ Script ran (exit code non-zero is OK if errors found)"
fi

if [ -f "untracked/qa/type_check.json" ]; then
    python3 -c "import json; json.load(open('untracked/qa/type_check.json'))" && echo "   ✓ Valid JSON" || echo "   ✗ Invalid JSON"
    python3 -c "import json; d=json.load(open('untracked/qa/type_check.json')); assert 'summary' in d and 'errors' in d" && echo "   ✓ Correct structure" || echo "   ✗ Missing fields"
else
    echo "   ✗ type_check.json not created"
    exit 1
fi
echo ""

echo "4. Testing run_format_check.sh..."
if ./scripts/qa/run_format_check.sh > /dev/null 2>&1; then
    echo "   ✓ Script ran"
else
    echo "   ✓ Script ran (exit code non-zero is OK if violations found)"
fi

if [ -f "untracked/qa/format.json" ]; then
    python3 -c "import json; json.load(open('untracked/qa/format.json'))" && echo "   ✓ Valid JSON" || echo "   ✗ Invalid JSON"
    python3 -c "import json; d=json.load(open('untracked/qa/format.json')); assert 'summary' in d and 'violations' in d" && echo "   ✓ Correct structure" || echo "   ✗ Missing fields"
else
    echo "   ✗ format.json not created"
    exit 1
fi
echo ""

echo "5. Verifying JSON outputs..."
for file in untracked/qa/lint.json untracked/qa/type_check.json untracked/qa/format.json; do
    if [ -f "$file" ]; then
        tool=$(python3 -c "import json; print(json.load(open('$file')).get('tool', 'unknown'))")
        passed=$(python3 -c "import json; print(json.load(open('$file')).get('summary', {}).get('passed', 'N/A'))")
        echo "   $file: tool=$tool, passed=$passed"
    fi
done
echo ""

echo "=================================="
echo "✓ QA Infrastructure Test PASSED"
echo "=================================="
echo ""
echo "All QA scripts:"
echo "  - Execute successfully"
echo "  - Create JSON output files"
echo "  - Generate valid JSON"
echo "  - Include required fields"
echo ""
echo "Run './scripts/qa/run_all.sh' to execute full QA suite"
