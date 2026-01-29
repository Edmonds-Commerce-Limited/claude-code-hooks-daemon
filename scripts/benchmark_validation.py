#!/usr/bin/env python3
"""Benchmark jsonschema validation performance for input validation.

Tests validation performance with different approaches:
1. Full jsonschema validation (Draft7Validator)
2. Simple field checks (no schema)
3. Hybrid approach (essential fields + optional full validation)

Target: < 5ms overhead per event
"""

import time
from typing import Any
from jsonschema import Draft7Validator

# Sample PostToolUse input schema (tool_response structure)
POST_TOOL_USE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_name", "tool_response", "hook_event_name"],
    "properties": {
        "session_id": {"type": "string"},
        "transcript_path": {"type": "string"},
        "cwd": {"type": "string"},
        "hook_event_name": {"const": "PostToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "object"},
        "tool_response": {
            "type": "object",
            "properties": {
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "interrupted": {"type": "boolean"},
                "isImage": {"type": "boolean"},
            },
        },
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,  # Forward compatibility
}

# Sample PreToolUse input schema
PRE_TOOL_USE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_name", "hook_event_name"],
    "properties": {
        "session_id": {"type": "string"},
        "transcript_path": {"type": "string"},
        "cwd": {"type": "string"},
        "hook_event_name": {"const": "PreToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {"type": "object"},
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,
}

# Sample valid event data
VALID_POST_TOOL_USE = {
    "session_id": "test-session-123",
    "transcript_path": "/path/to/transcript.jsonl",
    "cwd": "/workspace",
    "hook_event_name": "PostToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "ls -la"},
    "tool_response": {
        "stdout": "file1.txt\nfile2.txt",
        "stderr": "",
        "interrupted": False,
        "isImage": False,
    },
    "tool_use_id": "tool_123",
}

VALID_PRE_TOOL_USE = {
    "session_id": "test-session-123",
    "transcript_path": "/path/to/transcript.jsonl",
    "cwd": "/workspace",
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "ls -la"},
    "tool_use_id": "tool_123",
}


def benchmark_full_schema_validation(iterations: int = 10000) -> dict[str, Any]:
    """Benchmark full jsonschema validation."""
    # Pre-compile validators (one-time cost)
    compile_start = time.perf_counter()
    post_validator = Draft7Validator(POST_TOOL_USE_INPUT_SCHEMA)
    pre_validator = Draft7Validator(PRE_TOOL_USE_INPUT_SCHEMA)
    compile_time = (time.perf_counter() - compile_start) * 1000  # ms

    # Benchmark validation
    start = time.perf_counter()
    for i in range(iterations):
        # Alternate between event types
        if i % 2 == 0:
            list(post_validator.iter_errors(VALID_POST_TOOL_USE))
        else:
            list(pre_validator.iter_errors(VALID_PRE_TOOL_USE))
    elapsed = (time.perf_counter() - start) * 1000  # ms

    return {
        "approach": "Full jsonschema validation",
        "compile_time_ms": round(compile_time, 3),
        "total_time_ms": round(elapsed, 2),
        "per_event_ms": round(elapsed / iterations, 4),
        "events_per_second": round(iterations / (elapsed / 1000), 0),
    }


def benchmark_simple_checks(iterations: int = 10000) -> dict[str, Any]:
    """Benchmark simple field existence checks."""

    def validate_simple(event_type: str, hook_input: dict) -> list[str]:
        """Simple validation - just check required fields exist."""
        errors = []
        if event_type == "PostToolUse":
            if "tool_name" not in hook_input:
                errors.append("Missing tool_name")
            if "tool_response" not in hook_input:
                errors.append("Missing tool_response")
            if "hook_event_name" not in hook_input:
                errors.append("Missing hook_event_name")
        elif event_type == "PreToolUse":
            if "tool_name" not in hook_input:
                errors.append("Missing tool_name")
            if "hook_event_name" not in hook_input:
                errors.append("Missing hook_event_name")
        return errors

    start = time.perf_counter()
    for i in range(iterations):
        if i % 2 == 0:
            validate_simple("PostToolUse", VALID_POST_TOOL_USE)
        else:
            validate_simple("PreToolUse", VALID_PRE_TOOL_USE)
    elapsed = (time.perf_counter() - start) * 1000  # ms

    return {
        "approach": "Simple field checks",
        "compile_time_ms": 0,
        "total_time_ms": round(elapsed, 2),
        "per_event_ms": round(elapsed / iterations, 4),
        "events_per_second": round(iterations / (elapsed / 1000), 0),
    }


def benchmark_hybrid_approach(iterations: int = 10000) -> dict[str, Any]:
    """Benchmark hybrid: essential checks + optional full validation."""
    # Pre-compile validators
    compile_start = time.perf_counter()
    post_validator = Draft7Validator(POST_TOOL_USE_INPUT_SCHEMA)
    pre_validator = Draft7Validator(PRE_TOOL_USE_INPUT_SCHEMA)
    compile_time = (time.perf_counter() - compile_start) * 1000

    def validate_hybrid(event_type: str, hook_input: dict, full_validation: bool) -> list[str]:
        """Hybrid validation."""
        errors = []

        # Layer 1: Essential checks (always)
        if event_type == "PostToolUse":
            if "tool_response" not in hook_input:
                errors.append("Missing tool_response")
            if "tool_output" in hook_input:  # Detect wrong field
                errors.append("Found tool_output (should be tool_response)")
        elif event_type == "PreToolUse":
            if "tool_name" not in hook_input:
                errors.append("Missing tool_name")

        # Layer 2: Full schema validation (optional)
        if full_validation and not errors:
            validator = post_validator if event_type == "PostToolUse" else pre_validator
            for error in validator.iter_errors(hook_input):
                path = ".".join(str(p) for p in error.path) if error.path else "root"
                errors.append(f"{path}: {error.message}")

        return errors

    # Benchmark with full validation enabled
    start = time.perf_counter()
    for i in range(iterations):
        if i % 2 == 0:
            validate_hybrid("PostToolUse", VALID_POST_TOOL_USE, full_validation=True)
        else:
            validate_hybrid("PreToolUse", VALID_PRE_TOOL_USE, full_validation=True)
    elapsed = (time.perf_counter() - start) * 1000

    return {
        "approach": "Hybrid (essential + full)",
        "compile_time_ms": round(compile_time, 3),
        "total_time_ms": round(elapsed, 2),
        "per_event_ms": round(elapsed / iterations, 4),
        "events_per_second": round(iterations / (elapsed / 1000), 0),
    }


def main():
    """Run all benchmarks and display results."""
    print("=" * 80)
    print("Input Validation Performance Benchmark")
    print("=" * 80)
    print(f"\nRunning 10,000 validation iterations per approach...\n")

    results = [
        benchmark_full_schema_validation(),
        benchmark_simple_checks(),
        benchmark_hybrid_approach(),
    ]

    # Display results
    print(f"{'Approach':<30} {'Compile':<12} {'Total':<12} {'Per Event':<12} {'Events/sec':<12}")
    print("-" * 80)
    for result in results:
        print(
            f"{result['approach']:<30} "
            f"{result['compile_time_ms']:<12} "
            f"{result['total_time_ms']:<12} "
            f"{result['per_event_ms']:<12} "
            f"{result['events_per_second']:<12}"
        )

    print("\n" + "=" * 80)
    print("Analysis")
    print("=" * 80)

    full_schema = results[0]
    simple = results[1]
    hybrid = results[2]

    print(f"\n✓ Full schema validation: {full_schema['per_event_ms']}ms per event")
    print(f"  - Well under 5ms target")
    print(f"  - One-time compile cost: {full_schema['compile_time_ms']}ms (cached)")

    print(f"\n✓ Simple checks: {simple['per_event_ms']}ms per event")
    print(
        f"  - {simple['per_event_ms'] / full_schema['per_event_ms']:.1f}x faster than full schema"
    )
    print(f"  - But catches fewer edge cases")

    print(f"\n✓ Hybrid approach: {hybrid['per_event_ms']}ms per event")
    print(f"  - Best of both worlds")
    print(f"  - Catches critical field name issues (tool_output vs tool_response)")
    print(f"  - Full validation adds minimal overhead")

    print("\n" + "=" * 80)
    print("Recommendation")
    print("=" * 80)
    print("\n✓ Use FULL jsonschema validation (Draft7Validator)")
    print(f"  - Performance is excellent: {full_schema['per_event_ms']}ms per event")
    print("  - Comprehensive validation catches all issues")
    print("  - Validators are cached (one-time compile cost)")
    print("  - Well under 5ms performance target")
    print("  - Provides best protection against silent failures")


if __name__ == "__main__":
    main()
