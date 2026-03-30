#!/bin/bash
#
# Run live daemon smoke tests - probe the running daemon via hook scripts
#
# Sends 3 known inputs to hook scripts and verifies expected responses.
# Catches the "#1 dogfooding failure mode": daemon running stale code.
#
# Probes:
#   1. Stop (no explanation)         → must return decision=block
#   2. Stop (stop_hook_active=true)  → must NOT block (loop guard check)
#   3. PreToolUse (destructive git)  → must return decision=block
#
# Exit codes:
#   0 - All 3 probes passed
#   1 - One or more probes failed (or daemon not running)
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_FILE="${PROJECT_ROOT}/untracked/qa/smoke_test.json"
HOOK_STOP="${PROJECT_ROOT}/.claude/hooks/stop"
HOOK_PRE="${PROJECT_ROOT}/.claude/hooks/pre-tool-use"

# Source venv management for VENV_PYTHON
# shellcheck source=../venv-include.bash
source "${PROJECT_ROOT}/scripts/venv-include.bash"
ensure_venv || exit 1

mkdir -p "$(dirname "${OUTPUT_FILE}")"

# ── Socket check ───────────────────────────────────────────────────────────────

# Find daemon socket (env override or discover by glob)
SOCKET_PATH="${CLAUDE_HOOKS_SOCKET_PATH:-}"
if [[ -z "${SOCKET_PATH}" ]]; then
    for _candidate in "${PROJECT_ROOT}/untracked/"daemon-*.sock; do
        if [[ -S "${_candidate}" ]]; then
            SOCKET_PATH="${_candidate}"
            break
        fi
    done
fi

if [[ -z "${SOCKET_PATH}" ]] || [[ ! -S "${SOCKET_PATH}" ]]; then
    "${VENV_PYTHON}" - << 'PYEOF' > "${OUTPUT_FILE}"
import json, sys
result = {
    "tool": "smoke_test",
    "summary": {"total_probes": 3, "passed_probes": 0, "failed_probes": 3, "passed": False},
    "probes": [],
    "error": "Daemon not running — no socket found. Run: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart",
}
json.dump(result, sys.stdout, indent=2)
print()
PYEOF
    echo "❌ SMOKE TEST FAILED: Daemon not running"
    echo "   Run: \$PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
    exit 1
fi

echo "Running smoke test probes (socket: ${SOCKET_PATH})..."

# ── Probes ─────────────────────────────────────────────────────────────────────

PROBE1='{"hook_event_name":"Stop","stop_hook_active":false,"session_id":"smoke-test-probe"}'
PROBE2='{"hook_event_name":"Stop","stop_hook_active":true,"session_id":"smoke-test-probe"}'
PROBE3='{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git reset --hard HEAD"},"session_id":"smoke-test-probe"}'

RESPONSE1=$(echo "${PROBE1}" | "${HOOK_STOP}" 2>/dev/null || echo "{}")
RESPONSE2=$(echo "${PROBE2}" | "${HOOK_STOP}" 2>/dev/null || echo "{}")
RESPONSE3=$(echo "${PROBE3}" | "${HOOK_PRE}" 2>/dev/null || echo "{}")

# ── Analyse and write JSON ─────────────────────────────────────────────────────

"${VENV_PYTHON}" - "${RESPONSE1}" "${RESPONSE2}" "${RESPONSE3}" << 'PYEOF' > "${OUTPUT_FILE}"
import json
import sys

raw_responses = sys.argv[1:]

def _stop_decision(d: dict) -> str:
    """Stop: top-level decision field."""
    return d.get("decision", "(none)")

def _pre_tool_decision(d: dict) -> str:
    """PreToolUse: hookSpecificOutput.permissionDecision."""
    return d.get("hookSpecificOutput", {}).get("permissionDecision", "(none)")

probe_defs = [
    {
        "name": "stop_no_explanation",
        "description": "Stop without explanation should be blocked",
        "expected": "decision=block",
        "check": lambda d: d.get("decision") == "block",
        "get_decision": _stop_decision,
    },
    {
        "name": "stop_loop_guard",
        "description": "stop_hook_active=true should allow through (infinite loop prevention)",
        "expected": "decision!=block",
        "check": lambda d: d.get("decision") != "block",
        "get_decision": _stop_decision,
    },
    {
        "name": "pre_tool_use_destructive_git",
        "description": "Destructive git command should be blocked",
        "expected": "permissionDecision=deny",
        "check": lambda d: d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny",
        "get_decision": _pre_tool_decision,
    },
]

probes = []
for defn, raw in zip(probe_defs, raw_responses):
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        response = {}
    passed = defn["check"](response)
    probes.append({
        "name": defn["name"],
        "description": defn["description"],
        "expected": defn["expected"],
        "actual_decision": defn["get_decision"](response),
        "passed": passed,
    })

passed_count = sum(1 for p in probes if p["passed"])
failed_count = len(probes) - passed_count

result = {
    "tool": "smoke_test",
    "summary": {
        "total_probes": len(probes),
        "passed_probes": passed_count,
        "failed_probes": failed_count,
        "passed": failed_count == 0,
    },
    "probes": probes,
}
json.dump(result, sys.stdout, indent=2)
print()
PYEOF

# ── Print results ──────────────────────────────────────────────────────────────

echo ""
echo "Smoke Test Results:"
"${VENV_PYTHON}" - << PYEOF
import json, sys
with open("${OUTPUT_FILE}") as f:
    data = json.load(f)
summary = data["summary"]
for probe in data["probes"]:
    icon = "✅" if probe["passed"] else "❌"
    print(f"  {icon} {probe['name']}: {probe['description']}")
    if not probe["passed"]:
        print(f"      Expected: {probe['expected']}")
        print(f"      Got:      decision={probe['actual_decision']}")
print()
status = "✅ PASSED" if summary["passed"] else "❌ FAILED"
print(f"  Status: {status} ({summary['passed_probes']}/{summary['total_probes']} probes)")
sys.exit(0 if summary["passed"] else 1)
PYEOF
