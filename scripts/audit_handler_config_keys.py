#!/usr/bin/env python3
"""Audit script to compare HandlerID constants vs auto-generated config keys.

This script identifies mismatches between:
- HandlerID.*.config_key (what constants claim)
- _to_snake_case(class_name) (what registry actually uses)
"""

import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from claude_code_hooks_daemon.constants.handlers import HandlerID


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case (matches registry.py logic).

    Args:
        name: CamelCase string

    Returns:
        snake_case string with _handler suffix stripped
    """
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Strip _handler suffix to match config keys
    if snake.endswith("_handler"):
        snake = snake[:-8]  # Remove "_handler"

    return snake


def audit_handler_keys() -> dict[str, dict[str, str]]:
    """Audit all HandlerID constants vs auto-generated keys.

    Returns:
        Dict with keys: 'matches', 'mismatches'
        Each containing handler_name -> {constant, auto_generated, status}
    """
    results = {
        "matches": {},
        "mismatches": {},
    }

    # Get all HandlerID constants
    for attr_name in dir(HandlerID):
        if attr_name.startswith("_"):
            continue

        attr = getattr(HandlerID, attr_name)
        if not hasattr(attr, "class_name"):
            continue

        # Get constant config key
        constant_key = attr.config_key

        # Generate auto-generated key (what registry actually uses)
        auto_generated_key = to_snake_case(attr.class_name)

        handler_info = {
            "constant": constant_key,
            "auto_generated": auto_generated_key,
            "class_name": attr.class_name,
            "display_name": attr.display_name,
        }

        if constant_key == auto_generated_key:
            results["matches"][attr_name] = handler_info
        else:
            results["mismatches"][attr_name] = handler_info

    return results


def main() -> None:
    """Run audit and print results."""
    print("=" * 80)
    print("Handler Config Key Audit")
    print("=" * 80)
    print()

    results = audit_handler_keys()

    # Print mismatches first (critical)
    if results["mismatches"]:
        print("🚨 MISMATCHES FOUND (constant != auto-generated):")
        print("-" * 80)
        for handler_name, info in sorted(results["mismatches"].items()):
            print(f"\n{handler_name}:")
            print(f"  Class:         {info['class_name']}")
            print(f"  Constant:      {info['constant']}")
            print(f"  Auto-gen:      {info['auto_generated']} ← ACTUALLY USED")
            print(f"  Display:       {info['display_name']}")
        print()
        print(f"Total mismatches: {len(results['mismatches'])}")
    else:
        print("✅ No mismatches found - all constants match auto-generated keys")

    print()
    print("-" * 80)

    # Summary
    total = len(results["matches"]) + len(results["mismatches"])
    match_count = len(results["matches"])
    mismatch_count = len(results["mismatches"])

    print(f"\nSummary:")
    print(f"  Total handlers:     {total}")
    print(f"  Matches:            {match_count}")
    print(f"  Mismatches:         {mismatch_count}")

    if mismatch_count > 0:
        print(f"\n⚠️  {mismatch_count} handler(s) have config key mismatches!")
        print("   Configs must use auto-generated keys (constants are ignored)")
        sys.exit(1)
    else:
        print("\n✅ All handlers have consistent config keys")
        sys.exit(0)


if __name__ == "__main__":
    main()
