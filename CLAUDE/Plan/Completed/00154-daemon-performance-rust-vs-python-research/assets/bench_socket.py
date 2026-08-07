#!/usr/bin/env python3
"""Socket round-trip benchmark for the hooks daemon (Plan 00154).

Drives the LIVE daemon's Unix socket directly with newline-terminated JSON
requests (the same wire protocol send_request_stdin uses) and records
per-request wall-clock latency. This isolates the daemon-side cost
(socket accept + JSON parse + pydantic validation + dispatch + JSON encode)
from the bash-forwarder cost measured separately by bench_forwarder.sh.

Usage:
    $PYTHON assets/bench_socket.py --socket /workspace/untracked/daemon-<host>.sock \
        --iterations 300 --out assets/results/socket_bench.json

All events use benign inputs with no filesystem side effects beyond what the
production handlers themselves do on every real event (e.g. the status-line
context sidecar write, which is part of the production render cost and is
therefore deliberately included).
"""

import argparse
import json
import socket
import statistics
import sys
import time
from typing import Any

WARMUP_ITERATIONS = 20

# Benign synthetic source content: no security antipatterns, no QA
# suppressions, no error hiding. Cost of the content scanners is driven by
# content LENGTH (every regex runs over the full text either way).
_CONTENT_LINE = "def fn_{i}(x: int) -> int:\n    return x + {i}\n"


def make_content(target_bytes: int) -> str:
    """Build benign Python-ish content of approximately target_bytes."""
    lines = []
    i = 0
    size = 0
    while size < target_bytes:
        line = _CONTENT_LINE.format(i=i)
        lines.append(line)
        size += len(line)
        i += 1
    return "".join(lines)


def build_events(session_id: str) -> dict[str, dict[str, Any]]:
    """Return {name: request_dict} for each benchmarked event."""
    base = {
        "session_id": session_id,
        "transcript_path": "/nonexistent/bench-transcript.jsonl",
        "cwd": "/workspace",
    }
    events: dict[str, dict[str, Any]] = {}

    # Floor: system health request — socket + JSON + event loop, no dispatch,
    # no executor hop, no pydantic validation.
    events["system_health"] = {"event": "_system", "hook_input": {"action": "health"}}

    # PreToolUse: safe Bash command — full 37-handler chain, no terminal match.
    events["pre_bash_safe"] = {
        "event": "PreToolUse",
        "hook_input": {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la /workspace"},
        },
    }

    # PreToolUse: blocked git command — early terminal deny at priority 10.
    events["pre_bash_denied_early"] = {
        "event": "PreToolUse",
        "hook_input": {
            **base,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
        },
    }

    # PreToolUse: Write of a TEST file (passes tdd_enforcement) — the full
    # chain runs including all three content scanners over the payload.
    for label, size in (("1k", 1_000), ("10k", 10_000), ("100k", 100_000), ("1m", 1_000_000)):
        events[f"pre_write_test_{label}"] = {
            "event": "PreToolUse",
            "hook_input": {
                **base,
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/workspace/tests/unit/handlers/test_bench_dummy.py",
                    "content": make_content(size),
                },
            },
        }

    # PostToolUse: Bash with benign output — bash_error_detector scans output.
    events["post_bash"] = {
        "event": "PostToolUse",
        "hook_input": {
            **base,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls /workspace"},
            "tool_response": {"stdout": "file_a\nfile_b\n", "stderr": "", "interrupted": False},
        },
    }

    # UserPromptSubmit — git_context_injector spawns `git status` per prompt.
    events["user_prompt_submit"] = {
        "event": "UserPromptSubmit",
        "hook_input": {
            **base,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "benchmark prompt (plan 00154)",
        },
    }

    # Stop with stop_hook_active false — auto_continue_stop path.
    # transcript_path intentionally nonexistent; see RESEARCH.md caveat.
    events["stop"] = {
        "event": "Stop",
        "hook_input": {
            **base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        },
    }

    # Status (status line render) — full status_line chain incl. git
    # subprocesses and the context sidecar write. This IS the production
    # per-render cost.
    events["status_line"] = {
        "event": "Status",
        "hook_input": {
            "hook_event_name": "Status",
            "session_id": session_id,
            "workspace": {"current_dir": "/workspace", "project_dir": "/workspace"},
            "model": {"id": "claude-fable-5", "display_name": "Fable"},
            "version": "bench",
        },
    }

    return events


def roundtrip(sock_path: str, payload: bytes, timeout: float = 30.0) -> tuple[float, bytes]:
    """One request/response round-trip. Returns (elapsed_ms, response_bytes)."""
    start = time.perf_counter()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(sock_path)
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms, b"".join(chunks)


def summarise(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    n = len(ordered)

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, round(p / 100.0 * (n - 1))))
        return ordered[idx]

    return {
        "n": n,
        "min_ms": round(ordered[0], 3),
        "p50_ms": round(pct(50), 3),
        "p90_ms": round(pct(90), 3),
        "p95_ms": round(pct(95), 3),
        "p99_ms": round(pct(99), 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="Path to live daemon socket")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument(
        "--status-iterations",
        type=int,
        default=100,
        help="Fewer iterations for subprocess-heavy events",
    )
    parser.add_argument("--out", required=True, help="JSON results output path")
    args = parser.parse_args()

    session_id = f"bench-00154-{int(time.time())}"
    events = build_events(session_id)
    results: dict[str, Any] = {
        "socket": args.socket,
        "session_id": session_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "events": {},
    }

    for name, request in events.items():
        payload = (json.dumps(request) + "\n").encode("utf-8")
        iterations = (
            args.status_iterations
            if name in ("status_line", "user_prompt_submit")
            else args.iterations
        )

        # Warmup (not recorded)
        for _ in range(WARMUP_ITERATIONS):
            roundtrip(args.socket, payload)

        samples: list[float] = []
        last_response: bytes = b""
        for _ in range(iterations):
            elapsed_ms, last_response = roundtrip(args.socket, payload)
            samples.append(elapsed_ms)

        summary = summarise(samples)
        summary["request_bytes"] = len(payload)
        summary["response_bytes"] = len(last_response)
        try:
            decoded = json.loads(last_response)
            summary["response_keys"] = sorted(decoded.keys())
        except json.JSONDecodeError as exc:
            summary["response_decode_error"] = str(exc)
        results["events"][name] = summary
        print(
            f"{name:28s} n={summary['n']:4d} req={len(payload):8d}B "
            f"p50={summary['p50_ms']:8.2f}ms p95={summary['p95_ms']:8.2f}ms "
            f"p99={summary['p99_ms']:8.2f}ms max={summary['max_ms']:8.2f}ms"
        )

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
