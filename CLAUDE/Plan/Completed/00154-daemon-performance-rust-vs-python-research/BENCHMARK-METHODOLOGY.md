# Plan 00154 — Benchmark Methodology

How to reproduce every number in [RESEARCH.md](RESEARCH.md). Harness scripts live in [assets/](assets/); raw per-iteration data and JSON summaries in [assets/results/](assets/results/).

## Prerequisites

```bash
# Resolve the project venv Python (self-install mode; see CLAUDE.md "Self-Install Mode")
PYTHON=/workspace/untracked/venv-py311-66bbc57c/bin/python   # or resolve via init.sh
PLAN=/workspace/CLAUDE/Plan/00154-daemon-performance-rust-vs-python-research

# Daemon must be RUNNING; note the socket path from:
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
SOCK=/workspace/untracked/daemon-<hostname>.sock
```

Environment for the recorded runs: Linux 7.0.13-200.fc44.x86_64 container, 22 CPUs, 98 GB RAM, Python 3.11.2, daemon v3.36.0. Tools NOT available in this container (fallbacks used): `hyperfine` (→ bash `date +%s%N` loops), GNU `/usr/bin/time` (→ `/proc/<pid>/status` for RSS), `bc` (→ bash integer µs arithmetic).

## 1. Daemon-side socket round-trips (§4.2)

`assets/bench_socket.py` opens a fresh AF_UNIX connection per request (exactly like the production transport), sends newline-terminated `{"event": …, "hook_input": …}` JSON, reads to EOF, and records wall time. 20 warmups per event, then 200 recorded iterations (100 for the subprocess-heavy Status / UserPromptSubmit). Percentiles are computed from raw samples (nearest-rank).

```bash
$PYTHON $PLAN/assets/bench_socket.py \
    --socket "$SOCK" --iterations 200 --status-iterations 100 \
    --out $PLAN/assets/results/socket_bench.json
```

Notes:

- Event payloads are defined in `build_events()`. Content for Write events is benign generated Python (`def fn_N…`) so no scanner matches — the scan still traverses the full content, which is what costs.
- The Write path targets `tests/unit/handlers/test_bench_dummy.py` so `tdd_enforcement` does not terminate the chain early. **No file is ever written** — PreToolUse dispatch only *decides*.
- The Stop event uses a nonexistent `transcript_path` (realism caveat: RESEARCH.md §6.2).
- Sequential single client; concurrency was not benchmarked (production load is effectively sequential per session).

## 2. End-to-end production wrappers + client floors (§4.1)

`assets/bench_forwarder.sh` times `bash /workspace/.claude/hooks/<event>` with stdin JSON exactly as Claude Code invokes it (fresh bash per iteration, 3 warmups, 50 recorded), plus the isolated floors (bare bash spawn, `source init.sh`, `python3 -c 'import json, socket, sys'`, `jq` spawn). Timing is `date +%s%N` around the process; raw integer microseconds land in one `.us` file per scenario.

```bash
bash $PLAN/assets/bench_forwarder.sh $PLAN/assets/results/forwarder 50

# Summarise percentiles into summary.json:
python3 - <<'EOF'
import json, statistics, glob, os
d = "/workspace/CLAUDE/Plan/00154-daemon-performance-rust-vs-python-research/assets/results/forwarder"
summary = {}
for f in sorted(glob.glob(d + "/*.us")):
    xs = sorted(int(x) for x in open(f).read().split())
    n = len(xs)
    pct = lambda p: xs[min(n - 1, round(p / 100 * (n - 1)))]
    summary[os.path.basename(f)[:-3]] = {
        "n": n, "p50_ms": pct(50) / 1000, "p95_ms": pct(95) / 1000,
        "p99_ms": pct(99) / 1000, "mean_ms": round(statistics.fmean(xs) / 1000, 3)}
print(json.dumps(summary, indent=2))
json.dump(summary, open(d + "/summary.json", "w"), indent=2)
EOF
```

Interpretation note: the floors sum to more than the wrapper total because `jq | send_request_stdin` is a concurrent pipeline — spawn costs overlap.

## 3. In-process component micro-benchmarks (§4.3, §4.4)

`assets/bench_components.py` runs inside the project venv, imports the daemon's own modules warm, and times: JSON encode/decode, pydantic validate/dump, the three content scanners across 1 KB-1 MB, and every discoverable PreToolUse handler's `matches()` on two representative inputs. Adaptive loop: ≥ 20 reps and ≥ 0.2 s per subject.

```bash
$PYTHON $PLAN/assets/bench_components.py --out $PLAN/assets/results/components.json
```

Two deliberate design points:

- It does **not** call `DaemonController.initialise()` — that would run the `ClaudeMdInjector` side effect (rewrites the project CLAUDE.md). Handlers are constructed no-arg, so registry-injected options (language filters, exclude paths) are absent → scanner numbers are **upper bounds** (RESEARCH.md §6.3).
- Any handler whose construction or `matches()` raises is recorded with the error, never guessed.

## 4. Whole-daemon CPU profile (§4.5)

py-spy is not in the project venv and must not be added to it (research plan forbids dependency changes). It was installed into a scratch venv and attached to the live daemon (ptrace works in this container):

```bash
python3 -m venv /tmp/<scratch>/pyspy-venv
/tmp/<scratch>/pyspy-venv/bin/pip install py-spy          # 0.4.2 used

# Generate load in the background, then sample 45 s @ 200 Hz:
$PYTHON $PLAN/assets/bench_socket.py --socket "$SOCK" \
    --iterations 120 --status-iterations 60 --out /tmp/<scratch>/load.json &
/tmp/<scratch>/pyspy-venv/bin/py-spy record --pid <daemon-pid> \
    --duration 45 --rate 200 --subprocesses --format speedscope \
    -o $PLAN/assets/results/pyspy_profile.speedscope.json
```

Self-time aggregation over the speedscope JSON (top frames, busy-seconds) is a ~25-line script shown in RESEARCH.md §4.5's analysis; the raw profile is committed so it can be re-analysed or loaded at speedscope.app. A `py-spy dump` snapshot is in `assets/results/pyspy_dump.txt`.

## 5. Memory (§4.7)

```bash
PID=$($PYTHON -m claude_code_hooks_daemon.daemon.cli status | awk '/^PID:/{print $2}')
awk '/VmRSS|VmHWM|Threads/{print}' /proc/$PID/status
```

Captured three times: pre-benchmark (62.9 MB — daemon had already served this session), post-benchmark (76.1 MB RSS / 299.7 MB HWM), and freshly restarted (51.3 MB). GNU time was unavailable; `/proc` is the source.

## 6. Cold start, CLI cost, no-daemon counterfactual (§4.6)

```bash
# Cold restart wall time ×3 (this BOUNCES the shared daemon — do it at a quiet moment)
for i in 1 2 3; do
  t0=$(date +%s%N); $PYTHON -m claude_code_hooks_daemon.daemon.cli restart >/tmp/r.log 2>&1
  t1=$(date +%s%N); echo "$(( (t1-t0)/1000000 )) ms"
done

# CLI one-shot cost and import cost
t0=$(date +%s%N); $PYTHON -m claude_code_hooks_daemon.daemon.cli status >/dev/null 2>&1; t1=$(date +%s%N); echo $(( (t1-t0)/1000000 ))ms
t0=$(date +%s%N); $PYTHON -c "import claude_code_hooks_daemon"; t1=$(date +%s%N); echo $(( (t1-t0)/1000000 ))ms
$PYTHON -X importtime -c "from claude_code_hooks_daemon.daemon import cli" 2> $PLAN/assets/results/importtime_cli.txt

# No-daemon counterfactual (LOWER BOUND — the legacy entry crashes after
# imports+construction; see RESEARCH.md §6.4):
IN='{"hook_event_name":"PreToolUse","session_id":"bench","transcript_path":"/nonexistent/b.jsonl","cwd":"/workspace","tool_name":"Bash","tool_input":{"command":"ls -la /workspace"}}'
for i in $(seq 1 20); do
  t0=$(date +%s%N); echo "$IN" | $PYTHON -m claude_code_hooks_daemon.hooks.pre_tool_use >/dev/null 2>&1
  t1=$(date +%s%N); echo $(( (t1-t0)/1000 ))
done
```

## 7. Live daemon health / request stats (§4.8)

```bash
echo '{"event":"_system","hook_input":{"action":"health"}}' | python3 -c '
import json, socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(10)
s.connect("'"$SOCK"'"); s.sendall(sys.stdin.read().encode()); s.shutdown(socket.SHUT_WR)
buf = b""
while True:
    c = s.recv(65536)
    if not c: break
    buf += c
print(json.dumps(json.loads(buf), indent=1))'
```

## Rigour rules applied

- p50/p95/p99 from raw samples, nearest-rank; warmups always discarded.
- Warm-daemon and cold-start measured separately and never mixed.
- Heavy benches run **sequentially**, never concurrently with each other.
- Every number that could not be measured cleanly is labelled *estimate* or *lower bound* in RESEARCH.md with the reason (§6).
- Nothing in the harness mutates production code, config, or the plan's PLAN.md; the only daemon interaction is the documented wire protocol plus three intentional restarts.
