#!/usr/bin/env bash
# /acceptance-test skill - Automated acceptance testing orchestration

set -euo pipefail

FILTER="${1:-all}"

cat <<PROMPT
# Acceptance Testing Orchestration - Filter: ${FILTER}

Execute automated acceptance tests for hooks daemon handlers in parallel batches.

**CRITICAL**: You (main Claude) will orchestrate this workflow. Agents cannot spawn nested agents.

## Step 1: Restart Daemon

Ensure latest code is loaded:

\`\`\`bash
\$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
\`\`\`

**Expected**: "Daemon started successfully"

If daemon fails to start, ABORT and report error.

## Step 2: Generate Test Playbook (JSON)

Generate tests based on filter:

**Filter: ${FILTER}**

\`\`\`bash
# Determine filter flags based on input
FILTER_TYPE=""
FILTER_HANDLER=""

case "${FILTER}" in
    "all")
        # No filters - all tests
        ;;
    "blocking-only")
        FILTER_TYPE="--filter-type blocking"
        ;;
    "advisory-only")
        FILTER_TYPE="--filter-type advisory"
        ;;
    "context-only")
        FILTER_TYPE="--filter-type context"
        ;;
    *)
        # Handler name substring
        FILTER_HANDLER="--filter-handler ${FILTER}"
        ;;
esac

# Generate JSON playbook
\$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook --format json \$FILTER_TYPE \$FILTER_HANDLER > /tmp/acceptance_tests.json
\`\`\`

**Expected**: Valid JSON array of test objects

Verify JSON is valid:
\`\`\`bash
python3 -m json.tool /tmp/acceptance_tests.json > /dev/null && echo "✓ Valid JSON"
\`\`\`

Count total tests:
\`\`\`bash
TOTAL_TESTS=\$(cat /tmp/acceptance_tests.json | python3 -c "import json, sys; print(len(json.load(sys.stdin)))")
echo "Total tests: \$TOTAL_TESTS"
\`\`\`

**If TOTAL_TESTS = 0**:
- Report: "No tests match filter: ${FILTER}"
- Suggest: Try different filter or check handler names
- STOP (don't spawn agents for empty test list)

## Step 3: Group Tests into Batches

Batch size: 3-5 tests per batch (balances parallelism overhead vs throughput)

\`\`\`bash
# Calculate batches (5 tests each)
BATCH_SIZE=5
NUM_BATCHES=\$(( (\$TOTAL_TESTS + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "Batches: \$NUM_BATCHES (size: \$BATCH_SIZE)"
\`\`\`

Split JSON into batch files:
\`\`\`bash
python3 << 'EOF'
import json
import sys

with open("/tmp/acceptance_tests.json") as f:
    tests = json.load(f)

batch_size = 5
for i in range(0, len(tests), batch_size):
    batch = tests[i:i+batch_size]
    batch_num = (i // batch_size) + 1
    with open(f"/tmp/batch_{batch_num}.json", "w") as bf:
        json.dump(batch, bf, indent=2)
    print(f"Batch {batch_num}: {len(batch)} tests")
EOF
\`\`\`

## Step 4: Spawn Parallel Test Runner Agents

**For each batch**, spawn an acceptance-test-runner agent (Haiku model) in parallel:

**IMPORTANT**: Use Task tool to spawn agents. Send all agent spawns in a **single message** for true parallelism.

**Agent specification**: \`.claude/agents/acceptance-test-runner.md\`

**Task for each agent**:
\`\`\`
Execute acceptance test batch {batch_num}.

Read test batch from: /tmp/batch_{batch_num}.json

For each test in the batch:
1. Check if requires_event is a lifecycle event (SessionStart/SessionEnd/PreCompact)
   - If yes: Mark as "skip" with reason "Lifecycle event cannot be triggered by subagent"
   - If no: Execute test

2. For non-lifecycle tests:
   - Run setup commands (if any)
   - Execute test command
   - Check expected behavior based on test_type:
     * BLOCKING: Command should be blocked/denied
     * ADVISORY: Command succeeds, check system-reminder for advisory
     * CONTEXT: Check system-reminder for context injection
   - Match expected_message_patterns in output/system-reminder
   - Run cleanup commands (if any)

3. Record result for each test:
   - "pass": Expected behavior observed
   - "fail": Unexpected behavior (handler bug)
   - "skip": Lifecycle event (expected)
   - "error": Test couldn't execute (setup failure, etc.)

Return structured JSON:
{
  "batch_results": [...],
  "summary": {"total": N, "passed": X, "failed": Y, "skipped": Z, "errors": E}
}

Write output to: /tmp/batch_{batch_num}_results.json
\`\`\`

**Example parallel agent invocation**:

If you have 3 batches, send **one message** with 3 Task tool calls:

- Task 1: acceptance-test-runner for batch 1
- Task 2: acceptance-test-runner for batch 2
- Task 3: acceptance-test-runner for batch 3

This achieves true parallelism (all batches run simultaneously).

## Step 5: Collect Results

After all agents complete, aggregate results:

\`\`\`bash
python3 << 'EOF'
import json
import glob

all_results = []
total_summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}

# Read all batch result files
for result_file in sorted(glob.glob("/tmp/batch_*_results.json")):
    with open(result_file) as f:
        batch_data = json.load(f)
        all_results.extend(batch_data["batch_results"])

        # Aggregate summary
        summary = batch_data["summary"]
        for key in total_summary:
            total_summary[key] += summary.get(key, 0)

# Write aggregated results
with open("/tmp/acceptance_test_results.json", "w") as f:
    json.dump({
        "results": all_results,
        "summary": total_summary
    }, f, indent=2)

print(json.dumps(total_summary, indent=2))
EOF
\`\`\`

## Step 6: Report Results

**Read aggregated results**:
\`\`\`bash
cat /tmp/acceptance_test_results.json
\`\`\`

**Generate user-friendly summary**:

If all tests passed (failed=0, errors=0):
\`\`\`
✅ Acceptance Tests Complete!

📊 Results Summary:
   Total tests: {total}
   Passed: {passed}
   Failed: {failed}
   Skipped: {skipped} (lifecycle events)

⏱️  Execution time: {duration}
🔧 Parallel batches: {num_batches}

All tests passed! Handlers working correctly.
\`\`\`

If any tests failed (failed>0 or errors>0):
\`\`\`
❌ Acceptance Tests Failed!

📊 Results Summary:
   Total tests: {total}
   Passed: {passed}
   Failed: {failed}
   Skipped: {skipped} (lifecycle events)
   Errors: {errors}

❌ Failed Tests:
   {list each failed test with handler name, title, expected vs actual}

🔍 Investigation needed - fix handler bugs before release.
\`\`\`

**Include detailed failure information**:
- Handler name
- Test title
- Expected behavior
- Actual behavior
- Test number for reference

## Error Handling

**Daemon fails to start**:
- ABORT immediately
- Report error from daemon logs
- User must fix daemon issue

**JSON generation fails**:
- ABORT immediately
- Check if config file exists
- Check if handlers are loaded

**No tests match filter**:
- Report friendly message
- Suggest alternative filters
- Don't spawn agents

**Agent batch failure**:
- Report which batch failed
- Include agent error message
- Suggest re-running that specific batch

## Cleanup

After reporting results:
\`\`\`bash
rm -f /tmp/acceptance_tests.json /tmp/batch_*.json /tmp/batch_*_results.json /tmp/acceptance_test_results.json
\`\`\`

---

**Documentation**: SKILL.md for complete spec, CLAUDE/development/RELEASING.md for release integration

Begin Step 1 now (restart daemon).
PROMPT
