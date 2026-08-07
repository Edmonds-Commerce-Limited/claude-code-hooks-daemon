#!/usr/bin/env python3
"""In-process component micro-benchmarks for the hooks daemon (Plan 00154).

Runs INSIDE the project venv, importing the daemon's own modules to time
individual pipeline components with everything already warm (imports done,
regexes compiled). This attributes the daemon-side dispatch cost measured by
bench_socket.py to specific stages:

  1. JSON decode/encode of representative request payloads
  2. Pydantic HookEvent.model_validate + model_dump (per-request cost in
     DaemonController.process_request / process_event)
  3. Content-scanner handlers' matches() on benign content of varying size
     (security_antipattern, error_hiding_blocker, qa_suppression)
  4. Every discoverable PreToolUse handler's matches() on two representative
     inputs (safe Bash command; 10KB Write), to find chain hot spots

Deliberately does NOT call DaemonController.initialise() — that would run the
ClaudeMdInjector side effect (rewrites the project CLAUDE.md guidance block).
Handlers are instantiated directly; any handler whose no-arg construction or
matches() raises is reported as NOT MEASURED with the error, never guessed.

Usage:
    $PYTHON assets/bench_components.py --out assets/results/components.json
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from typing import Any

MIN_DURATION_SEC = 0.2
MIN_REPS = 20

_CONTENT_LINE = "def fn_{i}(x: int) -> int:\n    return x + {i}\n"


def make_content(target_bytes: int) -> str:
    lines = []
    i = 0
    size = 0
    while size < target_bytes:
        line = _CONTENT_LINE.format(i=i)
        lines.append(line)
        size += len(line)
        i += 1
    return "".join(lines)


def bench(fn: Callable[[], Any]) -> dict[str, float]:
    """Adaptive timing loop: repeat until MIN_DURATION_SEC, report per-call cost."""
    # Warmup
    for _ in range(3):
        fn()
    reps = 0
    samples: list[float] = []
    total = 0.0
    while total < MIN_DURATION_SEC or reps < MIN_REPS:
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        samples.append(dt)
        total += dt
        reps += 1
        if reps >= 100_000:
            break
    samples.sort()
    n = len(samples)
    return {
        "reps": n,
        "min_us": round(samples[0] * 1e6, 2),
        "p50_us": round(samples[n // 2] * 1e6, 2),
        "mean_us": round(sum(samples) / n * 1e6, 2),
        "max_us": round(samples[-1] * 1e6, 2),
    }


def make_write_input(content: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "bench-components",
        "transcript_path": "/nonexistent/bench.jsonl",
        "cwd": "/workspace",
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/workspace/tests/unit/handlers/test_bench_dummy.py",
            "content": content,
        },
    }


def make_bash_input() -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "bench-components",
        "transcript_path": "/nonexistent/bench.jsonl",
        "cwd": "/workspace",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la /workspace"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    results: dict[str, Any] = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # ------------------------------------------------------------------
    # 0. ProjectContext init (some handlers consult it via utils)
    # ------------------------------------------------------------------
    from pathlib import Path

    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not ProjectContext._initialized:
        ProjectContext.initialize(Path("/workspace/.claude/hooks-daemon.yaml"))

    # ------------------------------------------------------------------
    # 1. JSON decode/encode
    # ------------------------------------------------------------------
    json_results: dict[str, Any] = {}
    for label, size in (("1k", 1_000), ("10k", 10_000), ("100k", 100_000), ("1m", 1_000_000)):
        request = {"event": "PreToolUse", "hook_input": make_write_input(make_content(size))}
        encoded = json.dumps(request)
        json_results[f"decode_{label}"] = bench(lambda enc=encoded: json.loads(enc))
        json_results[f"encode_{label}"] = bench(lambda req=request: json.dumps(req))
    results["json"] = json_results

    # ------------------------------------------------------------------
    # 2. Pydantic validation + dump (as done per-request in controller)
    # ------------------------------------------------------------------
    pydantic_results: dict[str, Any] = {}
    try:
        from claude_code_hooks_daemon.core.event import HookEvent

        for label, size in (("1k", 1_000), ("100k", 100_000), ("1m", 1_000_000)):
            request = {"event": "PreToolUse", "hook_input": make_write_input(make_content(size))}
            pydantic_results[f"model_validate_{label}"] = bench(
                lambda req=request: HookEvent.model_validate(req)
            )
            event = HookEvent.model_validate(request)
            pydantic_results[f"model_dump_{label}"] = bench(
                lambda ev=event: ev.hook_input.model_dump(by_alias=False)
            )
    except Exception as exc:  # report, never guess
        pydantic_results["error"] = f"{type(exc).__name__}: {exc}"
    results["pydantic"] = pydantic_results

    # ------------------------------------------------------------------
    # 3. Content scanners at increasing content size
    # ------------------------------------------------------------------
    scanner_results: dict[str, Any] = {}
    scanner_classes = {}
    try:
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            SecurityAntipatternHandler,
        )

        scanner_classes["security_antipattern"] = SecurityAntipatternHandler
    except Exception as exc:
        scanner_results["security_antipattern"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        from claude_code_hooks_daemon.handlers.pre_tool_use import error_hiding_blocker as ehb

        for attr_name in dir(ehb):
            attr = getattr(ehb, attr_name)
            if (
                isinstance(attr, type)
                and attr_name.endswith("Handler")
                and attr.__module__ == ehb.__name__
            ):
                scanner_classes["error_hiding_blocker"] = attr
                break
    except Exception as exc:
        scanner_results["error_hiding_blocker"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        from claude_code_hooks_daemon.handlers.pre_tool_use import qa_suppression as qas

        for attr_name in dir(qas):
            attr = getattr(qas, attr_name)
            if (
                isinstance(attr, type)
                and attr_name.endswith("Handler")
                and attr.__module__ == qas.__name__
            ):
                scanner_classes["qa_suppression"] = attr
                break
    except Exception as exc:
        scanner_results["qa_suppression"] = {"error": f"{type(exc).__name__}: {exc}"}

    for name, cls in scanner_classes.items():
        per_size: dict[str, Any] = {}
        try:
            handler = cls()
            for label, size in (
                ("1k", 1_000),
                ("10k", 10_000),
                ("100k", 100_000),
                ("1m", 1_000_000),
            ):
                hook_input = make_write_input(make_content(size))
                per_size[label] = bench(lambda h=handler, hi=hook_input: h.matches(hi))
        except Exception as exc:
            per_size["error"] = f"{type(exc).__name__}: {exc}"
        scanner_results[name] = per_size
    results["scanners"] = scanner_results

    # ------------------------------------------------------------------
    # 4. Every PreToolUse handler's matches() on two representative inputs
    # ------------------------------------------------------------------
    chain_results: dict[str, Any] = {}
    try:
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        registry = HandlerRegistry()
        discovered = registry.discover()
        chain_results["_discovered_total"] = discovered

        bash_input = make_bash_input()
        write_input = make_write_input(make_content(10_000))

        for class_name in sorted(registry.list_handlers()):
            cls = registry.get_handler_class(class_name)
            if cls is None or "pre_tool_use" not in cls.__module__:
                continue
            entry: dict[str, Any] = {"module": cls.__module__}
            try:
                handler = cls()
                entry["bash_matches"] = bench(lambda h=handler, hi=bash_input: h.matches(hi))
                entry["write10k_matches"] = bench(lambda h=handler, hi=write_input: h.matches(hi))
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            chain_results[class_name] = entry
    except Exception as exc:
        chain_results["error"] = f"{type(exc).__name__}: {exc}"
    results["pre_tool_use_chain"] = chain_results

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"Wrote {args.out}")

    # Console summary of the biggest chain costs
    print("\nTop PreToolUse matches() costs (bash input, p50 us):")
    rows = []
    for name, entry in chain_results.items():
        if isinstance(entry, dict) and "bash_matches" in entry:
            rows.append((entry["bash_matches"]["p50_us"], name))
    for cost, name in sorted(rows, reverse=True)[:12]:
        print(f"  {cost:12.1f} us  {name}")
    print("\nTop PreToolUse matches() costs (write 10k input, p50 us):")
    rows = []
    for name, entry in chain_results.items():
        if isinstance(entry, dict) and "write10k_matches" in entry:
            rows.append((entry["write10k_matches"]["p50_us"], name))
    for cost, name in sorted(rows, reverse=True)[:12]:
        print(f"  {cost:12.1f} us  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
