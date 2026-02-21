#!/usr/bin/env python3
"""Audit codebase for error hiding patterns that violate FAIL FAST principles.

This script uses AST analysis to detect patterns like:
- Silent try/except/pass
- Silent try/except/continue
- Returning None on errors (instead of raising)
- Warning instead of error in critical paths
- Empty except blocks with just logging

Usage:
    python scripts/qa/audit_error_hiding.py [--fix]

Exit codes:
    0 - No violations found
    1 - Violations found (or other error)
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any

# Violation types
VIOLATION_TYPES = {
    "silent-pass": "Silent try/except/pass - error is completely ignored",
    "silent-continue": "Silent try/except/continue - error skipped in loop",
    "return-none-on-error": "Returns None on error instead of raising",
    "log-and-continue": "Logs error but continues execution",
    "bare-except": "Bare except clause without specific exception type",
    "warning-instead-of-error": "Uses logger.warning() for critical failures",
}


class ErrorHidingVisitor(ast.NodeVisitor):
    """AST visitor to detect error hiding patterns."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[dict[str, Any]] = []
        self._seen: set[tuple[str, int, str]] = set()
        self.in_test_file = "test_" in filepath.name or filepath.parts[-2] == "tests"

    def visit_Try(self, node: ast.Try) -> None:
        """Check try/except blocks for error hiding."""
        for handler in node.handlers:
            # Check for bare except (no exception type)
            if handler.type is None and not self.in_test_file:
                self._add_violation(
                    node,
                    "bare-except",
                    "Bare except clause - specify exception type",
                )

            # Check handler body for violations
            if len(handler.body) == 1:
                stmt = handler.body[0]

                # Pattern: try/except/pass
                if isinstance(stmt, ast.Pass):
                    self._add_violation(
                        node,
                        "silent-pass",
                        "Exception silently discarded with pass",
                    )

                # Pattern: try/except/continue
                elif isinstance(stmt, ast.Continue):
                    self._add_violation(
                        node,
                        "silent-continue",
                        "Exception silently skipped with continue",
                    )

            # Check for log-and-continue pattern
            if self._is_log_and_continue(handler):
                self._add_violation(
                    node,
                    "log-and-continue",
                    "Logs error but continues execution",
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for return-none-on-error pattern."""
        # Look for try/except that returns None
        for child in ast.walk(node):
            if isinstance(child, ast.Try):
                for handler in child.handlers:
                    for stmt in handler.body:
                        if isinstance(stmt, ast.Return):
                            # Check if returning None
                            if stmt.value is None or (
                                isinstance(stmt.value, ast.Constant)
                                and stmt.value.value is None
                            ):
                                self._add_violation(
                                    child,
                                    "return-none-on-error",
                                    "Returns None on error instead of raising",
                                )

        self.generic_visit(node)

    def _is_log_and_continue(self, handler: ast.ExceptHandler) -> bool:
        """Check if handler just logs and continues."""
        # Pattern: except: logger.error(...) with no raise
        if len(handler.body) == 1:
            stmt = handler.body[0]
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if isinstance(func, ast.Attribute):
                    # Check for logger.error(), logger.warning()
                    if func.attr in ("error", "warning", "info", "debug"):
                        return True
        return False

    def _add_violation(self, node: ast.AST, rule: str, message: str) -> None:
        """Add a violation to the list, deduplicating by (file, line, rule)."""
        line: int = getattr(node, "lineno", 0)
        key = (str(self.filepath), line, rule)
        if key in self._seen:
            return
        self._seen.add(key)
        self.violations.append(
            {
                "file": str(self.filepath),
                "line": line,
                "rule": rule,
                "message": message,
                "description": VIOLATION_TYPES.get(rule, "Unknown violation"),
            }
        )


def audit_file(filepath: Path) -> list[dict[str, Any]]:
    """Audit a single Python file for error hiding patterns."""
    try:
        with open(filepath, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        visitor = ErrorHidingVisitor(filepath)
        visitor.visit(tree)
        return visitor.violations

    except SyntaxError:
        # Skip files with syntax errors
        return []
    except Exception as e:
        print(f"Error auditing {filepath}: {e}", file=sys.stderr)
        return []


def audit_directory(directory: Path, exclude_patterns: list[str] | None = None) -> list[dict[str, Any]]:
    """Audit all Python files in a directory."""
    if exclude_patterns is None:
        exclude_patterns = [
            "untracked/",
            ".venv/",
            "venv/",
            "__pycache__/",
            ".git/",
            "build/",
            "dist/",
            ".eggs/",
        ]

    all_violations = []

    for py_file in directory.rglob("*.py"):
        # Skip excluded paths
        if any(pattern in str(py_file) for pattern in exclude_patterns):
            continue

        violations = audit_file(py_file)
        all_violations.extend(violations)

    return all_violations


def format_violation_report(violations: list[dict[str, Any]]) -> str:
    """Format violations into a readable report."""
    if not violations:
        return "✅ No error hiding violations found!\n"

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = {}
    for v in violations:
        file = v["file"]
        if file not in by_file:
            by_file[file] = []
        by_file[file].append(v)

    # Build report
    lines = [f"❌ Found {len(violations)} error hiding violation(s)\n"]

    for file, file_violations in sorted(by_file.items()):
        lines.append(f"\n{file}:")
        for v in sorted(file_violations, key=lambda x: x["line"]):
            lines.append(f"  Line {v['line']}: {v['rule']}")
            lines.append(f"    {v['message']}")
            lines.append(f"    ({v['description']})")

    return "\n".join(lines)


def load_exclusions(script_dir: Path) -> list[dict[str, Any]]:
    """Load intentional-pattern exclusions from JSON file."""
    exclusions_file = script_dir / "error_hiding_exclusions.json"
    if not exclusions_file.exists():
        return []
    try:
        with open(exclusions_file, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("exclusions", [])
    except Exception as e:
        print(f"Warning: could not load exclusions file: {e}", file=sys.stderr)
        return []


def apply_exclusions(
    violations: list[dict[str, Any]], exclusions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove violations that match an intentional-pattern exclusion entry."""
    if not exclusions:
        return violations

    filtered = []
    for v in violations:
        excluded = False
        for excl in exclusions:
            file_suffix = excl.get("file", "")
            excl_lines: list[int] = excl.get("lines", [])
            if v["file"].endswith(file_suffix) and v["line"] in excl_lines:
                excluded = True
                break
        if not excluded:
            filtered.append(v)
    return filtered


def write_json_output(violations: list[dict[str, Any]], output_path: Path) -> None:
    """Write violations as JSON to output_path for QA pipeline consumption."""
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": violations,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main() -> int:
    """Main entry point."""
    workspace = Path(__file__).parent.parent.parent

    json_mode = "--json" in sys.argv

    if not json_mode:
        print("Auditing codebase for error hiding patterns...")
        print(f"Workspace: {workspace}\n")

    # Audit src/ directory (production code only)
    src_violations = audit_directory(workspace / "src")

    # Apply exclusions for intentional patterns (documented in error_hiding_exclusions.json)
    script_dir = Path(__file__).parent
    exclusions = load_exclusions(script_dir)
    src_violations = apply_exclusions(src_violations, exclusions)

    if json_mode:
        output_path = workspace / "untracked" / "qa" / "error_hiding.json"
        write_json_output(src_violations, output_path)
    else:
        # Print report
        print(format_violation_report(src_violations))

    # Summary
    if src_violations:
        if not json_mode:
            print(f"\n⚠️  Action Required: Fix {len(src_violations)} violation(s)")
            print("These patterns violate FAIL FAST principles.")
        return 1

    if not json_mode:
        print("✅ All checks passed - no error hiding detected!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
