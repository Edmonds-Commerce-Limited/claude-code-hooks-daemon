#!/usr/bin/env bash
# /optimise skill - Analyse hooks daemon configuration and recommend improvements

set -euo pipefail

# Detect Python path
if [ -f "/workspace/untracked/venv/bin/python" ]; then
    PYTHON="/workspace/untracked/venv/bin/python"
elif [ -f "$(git rev-parse --show-toplevel 2>/dev/null)/.claude/hooks-daemon/untracked/venv/bin/python" ]; then
    PYTHON="$(git rev-parse --show-toplevel)/.claude/hooks-daemon/untracked/venv/bin/python"
else
    PYTHON="python3"
fi

# Detect config and project root
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
CONFIG="${PROJECT_ROOT}/.claude/hooks-daemon.yaml"

# Print dynamic environment values so Claude sees them before the static instructions
echo "## Detected Environment"
echo ""
echo "- Python:       ${PYTHON}"
echo "- Config:       ${CONFIG}"
echo "- Project root: ${PROJECT_ROOT}"
echo ""

# The rest of the instructions are static — quoted heredoc suppresses variable expansion
# and shellcheck parsing of the instruction body
cat <<'SKILL_INSTRUCTIONS'
# Hooks Daemon Configuration Optimiser

You are now running the /optimise skill. Follow these instructions precisely and completely.

The environment values (Python path, config path, project root) are printed above.
Use those exact values throughout these instructions wherever PYTHON, CONFIG, and
PROJECT_ROOT are referenced.

---

## Step 1: Load Configuration

Read the config file at the CONFIG path printed above.

If the file does not exist, output:
  ERROR: Config file not found at <CONFIG>
  Is the hooks daemon installed? See CLAUDE/LLM-INSTALL.md
Then stop.

Parse the YAML to understand which handlers are enabled under each event type section
(pre_tool_use, post_tool_use, session_start, stop, user_prompt_submit, etc.) and whether
the top-level plan_workflow section exists and has enabled: true.

For each handler: the YAML path is handlers.<event_type>.<handler_name>.enabled: true/false

For plan_workflow:
  plan_workflow.enabled: true/false
  plan_workflow.directory: "CLAUDE/Plan"   (or custom path)

---

## Step 2: Profile the Project

Run these checks on the filesystem at the PROJECT_ROOT printed above:

### Languages detected
Check for files (use Glob, not find). Limit to first 3 matches per language for speed:
- Python:     **/*.py
- JavaScript: **/*.js or **/*.jsx
- TypeScript: **/*.ts or **/*.tsx
- PHP:        **/*.php
- Ruby:       **/*.rb
- Go:         **/*.go
- Java:       **/*.java
- Rust:       **/*.rs
- C#:         **/*.cs
- Swift:      **/*.swift
- Dart:       **/*.dart

### Test directory
Check if any of these exist: tests/, spec/, test/, __tests__/
Report which one(s) are present, or "none detected".

### CI config
Check if any of these exist: .github/workflows/, .gitlab-ci.yml, Jenkinsfile, .circleci/
Report which one(s) are present, or "none detected".

### Plan directory
Read plan_workflow.directory from the config (default: CLAUDE/Plan).
Check if that directory exists under PROJECT_ROOT.
If it exists, count:
  - Active plans: folders at depth 1 that are NOT named Completed/, Cancelled/, Archive/
    and NOT named README.md or CLAUDE.md
  - Completed plans: count entries in Completed/ subdirectory (if it exists)

---

## Step 3: Analyse Five Areas

For each area, check whether specific handlers are enabled. Score each area:
- PASS: all handlers enabled
- WARN: 1 or more items missing but more than half present
- FAIL: half or fewer items present

### Area 1: Safety (Critical)

Check handlers.pre_tool_use.<name>.enabled for each:

  destructive_git        - blocks git reset --hard, force push
  sed_blocker            - prevents inplace file edit destruction
  security_antipattern   - blocks hardcoded secrets, eval, innerHTML
  error_hiding_blocker   - blocks swallowed exceptions and silent errors
  absolute_path          - requires absolute file paths
  curl_pipe_shell        - blocks curl piped to shell attacks
  dangerous_permissions  - blocks chmod 777

Score: count enabled / 7

### Area 2: Stop Quality

Check handlers.stop.<name>.enabled for each:

  auto_continue_stop          - prevents Claude stopping without explanation
  task_completion_checker     - verifies work done before stopping
  hedging_language_detector   - catches guessing instead of researching
  dismissive_language_detector - catches avoiding-work, out-of-scope deflection

Score: count enabled / 4

### Area 3: Plan Workflow

Check these items:

  plan_workflow.enabled                              - plan tracking config present
  handlers.pre_tool_use.plan_number_helper           - gives correct next plan number
  handlers.pre_tool_use.validate_plan_number         - ensures sequential plan numbering
  handlers.pre_tool_use.plan_workflow                - guides plan creation workflow
  handlers.pre_tool_use.plan_completion_advisor      - reminds to archive completed plans
  handlers.pre_tool_use.plan_time_estimates          - blocks time estimates (anti-pattern)
  (filesystem) plan directory has at least 1 plan    - confirms workflow actively used

For "plans in use": PASS if the plan directory exists and has at least 1 plan (active or completed).
Score: count of enabled/present items / 7

### Area 4: Code Quality

Check these handlers:

  handlers.pre_tool_use.tdd_enforcement        - tests written before production code
  handlers.pre_tool_use.qa_suppression         - blocks inline QA suppression comments
  handlers.post_tool_use.lint_on_edit          - linting after every file edit
  handlers.post_tool_use.bash_error_detector   - detects errors in bash output
  handlers.pre_tool_use.lsp_enforcement        - LSP tools instead of grep for symbols
  handlers.pre_tool_use.daemon_restart_verifier - verifies daemon restart before commits

Score: count enabled / 6

### Area 5: Daemon Settings

Check these handlers:

  handlers.session_start.version_check             - notifies when daemon updates available
  handlers.session_start.optimal_config_checker    - checks Claude Code env on startup
  handlers.session_start.yolo_container_detection  - detects container environments
  handlers.user_prompt_submit.git_context_injector - injects git status into prompts
  handlers.user_prompt_submit.critical_thinking_advisory - periodic critical thinking nudge

Score: count enabled / 5

---

## Step 4: Output the Scored Report

Format the report using Unicode box-drawing characters as shown. Use the actual values
from your analysis. Use the check mark character (✓) for enabled/present items and
the cross character (✗) for disabled/missing items.

  ╔══════════════════════════════════════════════════════════════╗
  ║           Hooks Daemon Configuration Optimiser               ║
  ╚══════════════════════════════════════════════════════════════╝

  Project Profile:
    Languages detected: <comma-separated list or "none detected">
    Test directory:     <directory name ✓, or "none detected">
    CI config:          <ci system ✓, or "none detected">
    Plan directory:     <path> (<N active, N completed> or "exists, no plans yet" or "not found")

  ━━━ Area 1: Safety ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PASS|WARN|FAIL (N/7)
    ✓|✗ destructive_git          enabled: blocks force push + reset --hard  |  DISABLED
    ✓|✗ sed_blocker              enabled: prevents inplace file edit destruction  |  DISABLED
    ✓|✗ security_antipattern     enabled: blocks hardcoded secrets + injection  |  DISABLED
    ✓|✗ error_hiding_blocker     enabled: blocks swallowed exceptions + silent errors  |  DISABLED
    ✓|✗ absolute_path            enabled: requires absolute file paths  |  DISABLED
    ✓|✗ curl_pipe_shell          enabled: blocks curl piped to shell  |  DISABLED
    ✓|✗ dangerous_permissions    enabled: blocks chmod 777  |  DISABLED

  ━━━ Area 2: Stop Quality ━━━━━━━━━━━━━━━━━━━━━━━━ PASS|WARN|FAIL (N/4)
    ✓|✗ auto_continue_stop           enabled: prevents unexplained stops  |  DISABLED
    ✓|✗ task_completion_checker      enabled: verifies work done before stopping  |  DISABLED
    ✓|✗ hedging_language_detector    enabled: catches guessing language  |  DISABLED
    ✓|✗ dismissive_language_detector enabled: catches avoiding-work language  |  DISABLED

  ━━━ Area 3: Plan Workflow ━━━━━━━━━━━━━━━━━━━━━━━ PASS|WARN|FAIL (N/7)
    ✓|✗ plan_workflow (config)        enabled + directory set  |  DISABLED or missing
    ✓|✗ plan_number_helper            enabled: gives correct next plan number  |  DISABLED
    ✓|✗ validate_plan_number          enabled: ensures sequential numbering  |  DISABLED
    ✓|✗ plan_workflow (handler)       enabled: guides plan creation  |  DISABLED
    ✓|✗ plan_completion_advisor       enabled: reminds to archive completed plans  |  DISABLED
    ✓|✗ plan_time_estimates           enabled: blocks time estimates (anti-pattern)  |  DISABLED
    ✓|✗ plans in use                  N plans found - workflow is active  |  no plans found yet

  ━━━ Area 4: Code Quality ━━━━━━━━━━━━━━━━━━━━━━━ PASS|WARN|FAIL (N/6)
    ✓|✗ tdd_enforcement           enabled: tests before production code  |  DISABLED
    ✓|✗ qa_suppression            enabled: blocks inline QA suppression comments  |  DISABLED
    ✓|✗ lint_on_edit              enabled: lints after every file edit  |  DISABLED
    ✓|✗ bash_error_detector       enabled: detects errors in bash output  |  DISABLED
    ✓|✗ lsp_enforcement           enabled: LSP tools over grep for symbols  |  DISABLED
    ✓|✗ daemon_restart_verifier   enabled: verifies daemon restart before commits  |  DISABLED

  ━━━ Area 5: Daemon Settings ━━━━━━━━━━━━━━━━━━━━ PASS|WARN|FAIL (N/5)
    ✓|✗ version_check              enabled: notifies when updates available  |  DISABLED
    ✓|✗ optimal_config_checker     enabled: checks Claude Code env on startup  |  DISABLED
    ✓|✗ yolo_container_detection   enabled: detects container environments  |  DISABLED
    ✓|✗ git_context_injector       enabled: injects git status into prompts  |  DISABLED
    ✓|✗ critical_thinking_advisory enabled: periodic critical thinking nudge  |  DISABLED

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Overall Score: TOTAL/29 (PCT%)

Where TOTAL = sum of all ✓ items, PCT = TOTAL*100/29 rounded to nearest integer.

---

## Step 5: Generate Recommendations

After the score line, list each disabled handler as a numbered recommendation.
Group by area. Only list items that are currently disabled/missing.

Example format:

  Recommendations (N improvements available):
    [1] Safety: Enable error_hiding_blocker — catches swallowed exceptions and silent errors
    [2] Stop Quality: Enable hedging_language_detector — catches guessing instead of researching
    [2] Stop Quality: Enable dismissive_language_detector — catches avoiding-work deflection
    [3] Plan Workflow: Enable plan_completion_advisor — reminds to archive completed plans

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Apply recommendations?
    - Type "apply all" to enable all recommended handlers
    - Type "apply 1,3" to apply specific recommendations by number
    - Type "skip" to view report only
    - Use /configure to make targeted changes

If score = 29/29 with no disabled items, output instead:
  No recommendations — configuration is fully optimised.

---

## Step 6: Apply Recommendations (if requested)

Wait for the user's response. Then:

### If "skip" or no response
Output: "Report complete. Use /configure to make targeted changes."

### If "apply all" or "apply N,M,..."

For each handler to enable, use the Edit tool to modify the config file (CONFIG path
printed at the top of this output):

1. Find the handler's YAML block:
     handler_name:
       enabled: false
       priority: N

2. Change "enabled: false" to "enabled: true".

3. If the handler block uses compact inline YAML such as {enabled: false, priority: N},
   expand it to block syntax first:
     handler_name:
       enabled: true
       priority: N

4. For the plan_workflow config section: if it is missing entirely, add this block at the
   end of the config file (before the plugins section if present):

     plan_workflow:
       enabled: true
       directory: "CLAUDE/Plan"
       workflow_docs: "CLAUDE/PlanWorkflow.md"
       enforce_claude_code_sync: false

After all edits are applied, restart the daemon using the PYTHON path printed above:

  PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  PYTHON -m claude_code_hooks_daemon.daemon.cli status

(Replace PYTHON with the actual path printed at the top.)

Then output a summary:

  Applied N changes:
    ✓ Enabled: handler_name
    ✓ Enabled: handler_name
    ...

  Daemon restarted successfully. Status: RUNNING

  Run /optimise again to verify the updated score.

If the daemon fails to restart, output:

  WARNING: Daemon failed to restart after changes.
  Check logs: PYTHON -m claude_code_hooks_daemon.daemon.cli logs
  The config changes were saved but may have a syntax error.

---

## Important Notes

- Preserve YAML comments when editing the config — do not strip them
- Only recommend enabling handlers — never recommend disabling them
- Plan workflow area: if plan_workflow.enabled is already true but some handlers
  (plan_number_helper, validate_plan_number, etc.) are disabled, recommend enabling those
  handlers specifically rather than changing the plan_workflow section
- "plans in use" check: this is informational only — it cannot be fixed by enabling a
  handler. Note it in the report but do not include it in the recommendations list
- Area scoring thresholds:
    PASS: all items enabled/present
    WARN: 1 or more items missing but more than half present
    FAIL: half or fewer items present

Begin by reading the config file, then profile the project, then output the full report.
SKILL_INSTRUCTIONS
