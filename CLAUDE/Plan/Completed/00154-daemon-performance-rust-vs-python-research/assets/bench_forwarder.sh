#!/bin/bash
#
# End-to-end forwarder benchmark for the hooks daemon (Plan 00154).
#
# Times the PRODUCTION bash wrappers (.claude/hooks/*) exactly as Claude Code
# invokes them: fresh bash process, stdin JSON, stdout JSON. This captures the
# full client-side hot path: bash startup + init.sh sourcing + jq spawn +
# python3 transport spawn + socket round-trip + daemon dispatch.
#
# Also times the client-side floors in isolation (bash+init.sh only,
# python3 -c interpreter spawn, jq spawn) so the wrapper overhead can be
# decomposed. Results are written as one file of per-iteration milliseconds
# per scenario, plus a summary JSON.
#
# Usage: bash assets/bench_forwarder.sh <results_dir> [iterations]

set -euo pipefail

RESULTS_DIR="${1:?usage: bench_forwarder.sh <results_dir> [iterations]}"
ITERATIONS="${2:-50}"
HOOKS_DIR="/workspace/.claude/hooks"
mkdir -p "$RESULTS_DIR"

# now_ns: nanosecond wall clock
now_ns() { date +%s%N; }

# run_scenario <name> <iterations> <command...>  — stdin fed from $STDIN_FILE
run_scenario() {
    local name="$1"; shift
    local iters="$1"; shift
    local out="$RESULTS_DIR/${name}.us"
    : > "$out"
    # Warmup x3 (not recorded)
    local i
    for i in 1 2 3; do
        "$@" < "$STDIN_FILE" > /dev/null || echo "warmup exit $? ($name)" >&2
    done
    for ((i = 0; i < iters; i++)); do
        local t0 t1
        t0=$(now_ns)
        "$@" < "$STDIN_FILE" > /dev/null || echo "iteration exit $? ($name)" >&2
        t1=$(now_ns)
        # integer microseconds (no bc in this container)
        echo $(( (t1 - t0) / 1000 )) >> "$out"
    done
    echo "recorded $iters iterations: $name"
}

TMP_DIR="$RESULTS_DIR/tmp"
mkdir -p "$TMP_DIR"

# --- Scenario stdin payloads -------------------------------------------------

PRE_JSON="$TMP_DIR/pre_tool_use.json"
cat > "$PRE_JSON" <<'EOF'
{"hook_event_name":"PreToolUse","session_id":"bench-forwarder-00154","transcript_path":"/nonexistent/bench.jsonl","cwd":"/workspace","tool_name":"Bash","tool_input":{"command":"ls -la /workspace"}}
EOF

STATUS_JSON="$TMP_DIR/status.json"
cat > "$STATUS_JSON" <<'EOF'
{"session_id":"bench-forwarder-00154","workspace":{"current_dir":"/workspace","project_dir":"/workspace"},"model":{"id":"claude-fable-5","display_name":"Fable"},"version":"bench"}
EOF

EMPTY_JSON="$TMP_DIR/empty.json"
echo '{}' > "$EMPTY_JSON"

# 1MB Write payload — exercises jq + python3 transport + daemon scanners on a
# large hook input (a Write of a big file sends the full content in the event)
PRE_1M_JSON="$TMP_DIR/pre_tool_use_1m.json"
python3 - "$PRE_1M_JSON" <<'PYEOF'
import json, sys
lines = []
i = 0
size = 0
while size < 1_000_000:
    line = f"def fn_{i}(x: int) -> int:\n    return x + {i}\n"
    lines.append(line)
    size += len(line)
    i += 1
payload = {
    "hook_event_name": "PreToolUse",
    "session_id": "bench-forwarder-00154",
    "transcript_path": "/nonexistent/bench.jsonl",
    "cwd": "/workspace",
    "tool_name": "Write",
    "tool_input": {
        "file_path": "/workspace/tests/unit/handlers/test_bench_dummy.py",
        "content": "".join(lines),
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
PYEOF

# --- Production wrappers ------------------------------------------------------

STDIN_FILE="$PRE_JSON"
run_scenario "wrapper_pre_tool_use" "$ITERATIONS" bash "$HOOKS_DIR/pre-tool-use"

STDIN_FILE="$STATUS_JSON"
run_scenario "wrapper_status_line" "$ITERATIONS" bash "$HOOKS_DIR/status-line"

STDIN_FILE="$PRE_1M_JSON"
run_scenario "wrapper_pre_tool_use_1m" "$ITERATIONS" bash "$HOOKS_DIR/pre-tool-use"

# --- Client-side floors -------------------------------------------------------

# Floor 1: bash spawn + init.sh sourcing only (no daemon traffic)
STDIN_FILE="$EMPTY_JSON"
run_scenario "floor_bash_init_source" "$ITERATIONS" \
    bash -c 'source /workspace/.claude/init.sh'

# Floor 2: python3 interpreter spawn with the transport's stdlib imports
run_scenario "floor_python3_spawn" "$ITERATIONS" \
    python3 -c 'import json, socket, sys'

# Floor 3: jq spawn
run_scenario "floor_jq_spawn" "$ITERATIONS" \
    jq -c '{event: "PreToolUse", hook_input: .}'

# Floor 4: bare bash spawn
run_scenario "floor_bash_spawn" "$ITERATIONS" bash -c 'exit 0'

echo "done: raw per-iteration data (integer microseconds, one per line) in $RESULTS_DIR/*.us"
