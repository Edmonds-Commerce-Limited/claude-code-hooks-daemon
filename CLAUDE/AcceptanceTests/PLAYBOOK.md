# Acceptance Testing Playbook

**Version**: 1.0
**Purpose**: Validate hooks daemon handlers work correctly in real Claude Code sessions
**Target**: Claude Code AI Agent & Human Developers

---

## Overview

This playbook provides step-by-step instructions for running acceptance tests on the hooks daemon. Unlike unit and integration tests which use mocked hook inputs, these tests validate handlers against **real Claude Code events**.

### What Gets Tested

- **15 Critical Handlers** (Tier 1: ~15-20 minutes)
- **50+ All Handlers** (Tier 2: ~1.5-2 hours)
- Real hook event formats from Claude Code CLI
- Handler blocking behavior (deny/allow decisions)
- Context injection and workflow management
- Advisory warnings and status line updates

### Test Tiers

**Tier 1: Quick Smoke Test**
- Safety blockers (destructive git, sed, pipes, absolute paths)
- QA enforcement (TDD, ESLint, Python/Go suppressions)
- Workflow handlers (planning, git context)
- Advisory handlers (British English, web search year, bash errors)
- **Time**: 15-20 minutes
- **Coverage**: 15 critical handlers

**Tier 2: Comprehensive Suite**
- All Tier 1 tests
- Complete workflow scenarios (full TDD cycle, git workflow, planning)
- All 54 handlers across 11 event types
- **Time**: 1.5-2 hours
- **Coverage**: All handlers

---

## Prerequisites

Before running acceptance tests, verify:

### 1. Daemon Status

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING
```

If not running:
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli start
```

### 2. Clean Git Working Tree

```bash
git status
# Expected: nothing to commit, working tree clean
```

If uncommitted changes exist, commit or stash them.

### 3. Python Environment

```bash
$PYTHON --version
# Expected: Python 3.11+ with venv activated
```

### 4. Required Tools

```bash
# Check debug_hooks.sh exists
ls scripts/debug_hooks.sh

# Check validation script exists
ls CLAUDE/AcceptanceTests/validation/validate-logs.py
```

---

## Quick Start

### Run Tier 1 (Recommended)

```bash
cd /workspace
./CLAUDE/AcceptanceTests/run-tier1.sh
```

This will:
1. Verify prerequisites
2. Start daemon debug logging
3. Display test instructions for manual execution
4. Wait for you to complete tests in Claude Code session
5. Stop debug logging
6. Validate results against expected responses
7. Generate summary report

### Run Tier 2 (Comprehensive)

```bash
cd /workspace
./CLAUDE/AcceptanceTests/run-tier2.sh
```

Same as Tier 1 but includes complete workflow scenarios.

---

## Manual Execution Workflow

Since these tests require real Claude Code interaction, you'll manually perform actions while debug logging captures events.

### Step 1: Start Test Session

```bash
./CLAUDE/AcceptanceTests/run-tier1.sh
```

The script will:
- Start daemon debug logging
- Display test scenarios to execute
- Pause and wait for you to complete tests

### Step 2: Execute Test Scenarios

Open a **new Claude Code session** and perform the test actions listed by the script.

#### Example Test Actions (Tier 1)

**Safety Blockers:**
1. Ask Claude Code to run: `git reset --hard` (should be blocked)
2. Ask Claude Code to run: `sed -i 's/foo/bar/' file.txt` (should be blocked)
3. Ask Claude Code to run: `npm test | tail` (should be blocked)
4. Ask Claude Code to Read a file using relative path like `src/file.py` (should be blocked)

**QA Enforcement:**
1. Ask Claude Code to create a new handler WITHOUT creating test file first (should be blocked)
2. Ask Claude Code to write `// eslint-disable` in TypeScript file (should be blocked)
3. Ask Claude Code to write `# noqa` in Python file (should be blocked)

**Workflow Handlers:**
1. Submit any user prompt (should inject git context)
2. Write to a PLAN.md file (should trigger plan workflow handler)

**Advisory Handlers:**
1. Write "color" in markdown file (should suggest "colour")
2. Use WebSearch with "2023" in query (should suggest "2026")
3. Run a bash command that fails (should detect error)

### Step 3: Finish Test Session

After completing test actions:

1. Press Enter in the terminal where `run-tier1.sh` is waiting
2. The script will:
   - Stop debug logging
   - Copy logs to results directory
   - Run validation script
   - Display summary report

### Step 4: Review Results

```bash
# View summary
cat CLAUDE/AcceptanceTests/results/latest/summary.md

# View full report
cat CLAUDE/AcceptanceTests/results/latest/validation-report.txt

# View daemon logs
cat CLAUDE/AcceptanceTests/results/latest/daemon-logs.txt
```

---

## Test Scenarios Detail

### Scenario 01: Safety Blockers

**Purpose**: Verify handlers block dangerous operations

**Tests**:
- DestructiveGitHandler blocks `git reset --hard`, `git clean -f`, `git push --force`
- SedBlockerHandler blocks `sed -i` commands
- PipeBlockerHandler blocks expensive command pipes (`npm test | tail`)
- AbsolutePathHandler blocks Read/Write/Edit with relative paths

**Expected Behavior**:
- Operations are **blocked** (decision: deny)
- Clear error messages explain why
- Suggestions for safe alternatives provided

**Manual Actions**:
```
1. In Claude Code session:
   User: "Run git reset --hard"
   Expected: Claude Code shows error from daemon blocking this

2. User: "Use sed -i to replace 'foo' with 'bar' in file.txt"
   Expected: Claude Code shows error suggesting Edit tool instead

3. User: "Run npm test | tail -20"
   Expected: Claude Code shows error about needing complete output

4. User: "Read the file src/handler.py"
   Expected: Claude Code shows error requiring absolute path
```

### Scenario 02: QA Enforcement

**Purpose**: Verify TDD and QA suppression blocking

**Tests**:
- TddEnforcementHandler blocks handler creation without test file
- EslintDisableHandler blocks ESLint suppression comments
- PythonQaSuppressionBlocker blocks `# noqa`, `# type: ignore`
- GoQaSuppressionBlocker blocks `// nolint`

**Expected Behavior**:
- Suppressions are **blocked** (decision: deny)
- Messages explain proper fix approach
- TDD workflow enforced

**Manual Actions**:
```
1. User: "Create a new PreToolUse handler called TestHandler"
   Expected: Blocked with TDD message to write test first

2. User: "Add // eslint-disable to this TypeScript file"
   Expected: Blocked with message to fix linting issue

3. User: "Add # noqa comment to suppress this warning"
   Expected: Blocked with message to fix the issue instead
```

### Scenario 03: Workflow Handlers

**Purpose**: Verify workflow and context injection

**Tests**:
- PlanWorkflowHandler validates plan workflow
- GitContextInjectorHandler adds git status to user prompts
- WorkflowStateRestorationHandler restores state on session start

**Expected Behavior**:
- Operations are **allowed** (decision: allow)
- Additional context injected into responses
- Non-blocking advisories provided

**Manual Actions**:
```
1. User: "What's the current git status?"
   Expected: Claude Code response includes git context from handler

2. User: "Create a new plan in CLAUDE/Plan/"
   Expected: Plan workflow handler provides guidance

3. Start new session after conversation compaction
   Expected: Workflow state restored automatically
```

### Scenario 04: Advisory Handlers

**Purpose**: Verify non-blocking advisory warnings

**Tests**:
- BritishEnglishHandler suggests British spellings
- WebSearchYearHandler suggests current year (2026)
- BashErrorDetectorHandler detects command failures

**Expected Behavior**:
- Operations are **allowed** (decision: allow)
- Helpful suggestions provided
- No blocking of user actions

**Manual Actions**:
```
1. User: "Write a markdown file with the word 'color'"
   Expected: Claude Code suggests using "colour" instead

2. User: "Search the web for 'React documentation 2023'"
   Expected: Claude Code suggests using 2026 instead

3. User: "Run this command: ls /nonexistent/path"
   Expected: After failure, handler detects error and suggests investigation
```

---

## Validation Process

### Automated Validation

The `validate-logs.py` script:

1. **Parses daemon debug logs** to extract handler execution events
2. **Compares against expected responses** from `expected-responses.yaml`
3. **Validates**:
   - Handler executed for matching pattern
   - Decision matches expected (deny/allow)
   - Reason message contains expected keywords
   - Handler priority correct
   - Terminal flag respected

### Manual Validation

While automated validation checks logs, you should also observe:

- **Blocked commands actually fail** (not executed)
- **Warning messages are clear and helpful**
- **Status line displays expected information**
- **Context injection appears in Claude Code responses**
- **Workflow state restoration works correctly**

### Pass Criteria

A handler **passes** if:
- ✓ All test patterns trigger the handler
- ✓ Decisions match expected (deny/allow)
- ✓ Reason messages contain expected keywords
- ✓ No false positives (handler doesn't trigger incorrectly)
- ✓ No false negatives (handler triggers when it should)

A handler **fails** if:
- ✗ Handler doesn't execute for matching pattern
- ✗ Wrong decision (deny instead of allow, or vice versa)
- ✗ Missing expected keywords in reason message
- ✗ False positive (triggers on non-matching pattern)
- ✗ False negative (doesn't trigger on matching pattern)

---

## Results Interpretation

### Success Output

```
==========================================
ACCEPTANCE TEST VALIDATION REPORT
==========================================

Summary:
  Total handlers tested: 15
  Handlers passed: 15
  Handlers failed: 0

Handler Results:
--------------------------------------------------------------------------------
✓ PASS destructive-git (4/4 tests passed)
✓ PASS sed-blocker (2/2 tests passed)
✓ PASS pipe-blocker (3/3 tests passed)
✓ PASS absolute-path (3/3 tests passed)
✓ PASS tdd-enforcement (2/2 tests passed)
✓ PASS eslint-disable (3/3 tests passed)
✓ PASS python-qa-suppression (3/3 tests passed)
✓ PASS go-qa-suppression (2/2 tests passed)
✓ PASS plan-workflow (2/2 tests passed)
✓ PASS git-context (2/2 tests passed)
✓ PASS workflow-state (2/2 tests passed)
✓ PASS british-english (3/3 tests passed)
✓ PASS web-search-year (3/3 tests passed)
✓ PASS bash-error-detector (2/2 tests passed)
✓ PASS daemon-stats (1/1 tests passed)

==========================================
✓ ALL TESTS PASSED
==========================================
```

### Failure Output

```
Handler Results:
--------------------------------------------------------------------------------
✓ PASS destructive-git (4/4 tests passed)
✗ FAIL pipe-blocker (2/3 tests passed)
    Test 2:
      Pattern: find . -name '*.py' | head
      Reason: Handler did not execute for this pattern

✓ PASS absolute-path (3/3 tests passed)
...

==========================================
✗ 1 HANDLER(S) FAILED
==========================================
```

### Debugging Failures

When a handler fails:

1. **Check daemon logs**:
   ```bash
   grep "pipe-blocker" CLAUDE/AcceptanceTests/results/latest/daemon-logs.txt
   ```

2. **Verify handler is enabled**:
   ```bash
   grep "pipe-blocker" .claude/hooks-daemon.yaml
   ```

3. **Check handler matches() logic**:
   ```bash
   cat src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py
   ```

4. **Re-run specific test** with debug logging to capture event format

5. **Update handler or test** based on findings

---

## Troubleshooting

### Daemon Not Running

**Symptom**: `run-tier1.sh` fails with "Daemon is not running"

**Solution**:
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli start
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```

### Debug Logging Not Capturing Events

**Symptom**: Daemon logs are empty or missing handler events

**Solution**:
1. Verify daemon is running during test execution
2. Check log level in config: `.claude/hooks-daemon.yaml`
3. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
4. Verify debug_hooks.sh is using correct log path

### Validation Script Errors

**Symptom**: `validate-logs.py` fails with parsing errors

**Solution**:
1. Check log file exists and is readable
2. Verify expected-responses.yaml is valid YAML
3. Run with `--json` flag to see raw validation data
4. Check for log format changes (update parser if needed)

### Handler Not Executing

**Symptom**: Handler doesn't trigger for matching pattern

**Possible Causes**:
1. Handler disabled in config
2. Handler matches() logic incorrect
3. Event type mismatch (PreToolUse vs PostToolUse)
4. Priority conflict with terminal handler
5. Hook input format different than expected

**Debug Steps**:
1. Enable handler in `.claude/hooks-daemon.yaml`
2. Check handler registration in config
3. Review handler matches() logic
4. Capture actual event format with debug_hooks.sh
5. Compare actual vs expected hook_input structure

### False Positives

**Symptom**: Handler triggers when it shouldn't

**Solution**:
1. Review handler matches() conditions
2. Make pattern matching more specific
3. Add negative test cases to prevent regression
4. Update expected-responses.yaml with correct patterns

---

## Adding New Test Scenarios

To add a new test scenario:

### 1. Create Scenario Script

```bash
cd CLAUDE/AcceptanceTests/test-scenarios
touch 06-my-new-scenario.sh
chmod +x 06-my-new-scenario.sh
```

### 2. Follow Template Structure

```bash
#!/usr/bin/env bash
# Test [scenario name]
# Tests: [handler names]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCEPTANCE_ROOT="$(dirname "$SCRIPT_DIR")"

source "$ACCEPTANCE_ROOT/validation/test-helpers.sh"

echo "========================================"
echo "Test Scenario: [Name]"
echo "========================================"

log_info "Test 1: [Description]"
log_info "Expected: [Expected behavior]"

# Add more tests...

echo "Scenario complete"
```

### 3. Update expected-responses.yaml

Add handler expectations:

```yaml
handlers:
  my-new-handler:
    event_type: PreToolUse
    priority: 50
    terminal: true
    tests:
      - pattern: "test pattern"
        decision: deny
        reason_contains: ["keyword1", "keyword2"]
```

### 4. Update Orchestration Scripts

Add to `run-tier1.sh` or `run-tier2.sh`:

```bash
echo "Running scenario 06: My New Scenario"
bash "$SCENARIOS_DIR/06-my-new-scenario.sh"
```

### 5. Document in PLAYBOOK.md

Add scenario description and manual test actions.

---

## Best Practices

### For Test Execution

1. **Start with clean state**: Commit or stash changes before testing
2. **Run Tier 1 first**: Quick validation before comprehensive testing
3. **Document anomalies**: Note unexpected behavior for investigation
4. **Save logs**: Results are timestamped for historical comparison
5. **Test incrementally**: Add one handler test at a time

### For Test Development

1. **Debug events first**: Use `debug_hooks.sh` to capture real event formats
2. **Test positive and negative**: Both matching and non-matching patterns
3. **Validate keywords**: Use specific reason keywords in expected-responses.yaml
4. **Keep scenarios focused**: One handler category per scenario script
5. **Document expected behavior**: Clear descriptions in test scripts

### For Debugging

1. **Check logs first**: Most failures have clear log evidence
2. **Isolate the problem**: Test one handler at a time
3. **Compare events**: Actual vs expected hook_input structure
4. **Validate config**: Ensure handler is enabled and priority is correct
5. **Ask for help**: Include logs and config in issue reports

---

## Integration with Development Workflow

### Pre-Commit Checks

Run Tier 1 before committing handler changes:

```bash
# Make handler changes
vim src/claude_code_hooks_daemon/handlers/pre_tool_use/my_handler.py

# Run unit tests
./scripts/qa/run_all.sh

# Run acceptance tests (Tier 1)
./CLAUDE/AcceptanceTests/run-tier1.sh

# Commit if all pass
git add src/claude_code_hooks_daemon/handlers/
git commit -m "Add my-handler with acceptance tests"
```

### Release Validation

Run Tier 2 before releases:

```bash
# Before tagging release
./CLAUDE/AcceptanceTests/run-tier2.sh

# Only proceed if all tests pass
git tag -a v1.2.0 -m "Release 1.2.0"
```

### Continuous Integration

Future enhancement: Run acceptance tests in CI/CD pipeline with headless Claude Code sessions.

---

## Results Directory Structure

```
CLAUDE/AcceptanceTests/results/
├── latest -> 2026-01-30-14-30-00/    # Symlink to latest run
├── 2026-01-30-14-30-00/              # Timestamped run
│   ├── execution.log                 # Full execution log
│   ├── daemon-logs.txt               # Daemon debug logs
│   ├── validation-report.txt         # Human-readable report
│   ├── validation-results.json       # Machine-readable results
│   └── summary.md                    # Quick summary
└── 2026-01-29-10-15-00/              # Previous run
    └── ...
```

---

## Summary

This playbook provides:

- ✓ Step-by-step test execution workflow
- ✓ Automated validation of handler behavior
- ✓ Manual verification checklist
- ✓ Debugging guidance for failures
- ✓ Integration with development workflow
- ✓ Extensible framework for new tests

**Key Takeaway**: Acceptance tests validate that handlers work correctly in **real Claude Code sessions**, catching integration issues that unit tests miss.

---

**Next Steps**:
1. Run Tier 1 acceptance tests to establish baseline
2. Fix any failures identified
3. Document baseline results
4. Integrate into regular development workflow
5. Expand Tier 2 coverage to all 54 handlers

For questions or issues, see:
- `CLAUDE/DEBUGGING_HOOKS.md` - Hook debugging workflow
- `CLAUDE/HANDLER_DEVELOPMENT.md` - Handler creation guide
- `CLAUDE/ARCHITECTURE.md` - System design documentation
