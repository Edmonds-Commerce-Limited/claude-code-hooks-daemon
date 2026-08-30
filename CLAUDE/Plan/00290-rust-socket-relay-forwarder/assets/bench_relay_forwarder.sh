#!/bin/bash
#
# End-to-end forwarder benchmark for Plan 00290 (relay/nc/python3 rungs).
#
# Same method as Plan 00154's bench_forwarder.sh: times the PRODUCTION
# .claude/hooks/pre-tool-use wrapper exactly as Claude Code invokes it (fresh
# bash per iteration, stdin JSON, stdout discarded), for a single typical
# PreToolUse event. Run this script once PER RUNG, after configuring the
# daemon/forwarders for that rung (see MEASUREMENT-relay.md for the exact
# sequence) — the rung label just tags which result file gets written so all
# three runs land side by side for comparison.
#
# Usage: bash assets/bench_relay_forwarder.sh <rung_label> <results_dir> [iterations]
#   rung_label:   short tag, e.g. "python3", "nc", "relay" — used as the
#                 output filename stem.
#   results_dir:  directory the raw .us file is written into.
#   iterations:   recorded iterations after 3 warmups (default 60).

set -euo pipefail

RUNG_LABEL="${1:?usage: bench_relay_forwarder.sh <rung_label> <results_dir> [iterations]}"
RESULTS_DIR="${2:?usage: bench_relay_forwarder.sh <rung_label> <results_dir> [iterations]}"
ITERATIONS="${3:-60}"
HOOKS_DIR="/workspace/.claude/hooks"
mkdir -p "$RESULTS_DIR"

now_ns() { date +%s%N; }

TMP_DIR="$RESULTS_DIR/tmp"
mkdir -p "$TMP_DIR"

PRE_JSON="$TMP_DIR/pre_tool_use.json"
cat > "$PRE_JSON" <<'EOF'
{"hook_event_name":"PreToolUse","session_id":"bench-relay-00290","transcript_path":"/nonexistent/bench.jsonl","cwd":"/workspace","tool_name":"Bash","tool_input":{"command":"ls -la /workspace"}}
EOF

OUT="$RESULTS_DIR/${RUNG_LABEL}.us"
: > "$OUT"

# Warmup x3 (not recorded) — primes bash's own page cache and, on the relay
# rung, confirms the guard path is actually reachable before timing begins.
for _ in 1 2 3; do
    bash "$HOOKS_DIR/pre-tool-use" < "$PRE_JSON" > /dev/null \
        || echo "warmup exit $? (${RUNG_LABEL})" >&2
done

for ((i = 0; i < ITERATIONS; i++)); do
    t0=$(now_ns)
    bash "$HOOKS_DIR/pre-tool-use" < "$PRE_JSON" > /dev/null \
        || echo "iteration exit $? (${RUNG_LABEL})" >&2
    t1=$(now_ns)
    echo $(( (t1 - t0) / 1000 )) >> "$OUT"
done

echo "recorded $ITERATIONS iterations: rung=${RUNG_LABEL} -> $OUT"
