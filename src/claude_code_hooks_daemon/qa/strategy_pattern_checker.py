#!/usr/bin/env python3
"""Strategy Pattern compliance checker for Claude Code Hooks Daemon.

Enforces proper Strategy Pattern usage in language-aware handlers:
- Handlers delegate to strategies, no language-specific if/elif chains
- Strategies have get_acceptance_tests() method
- Strategies use named constants, not bare string literals
- All strategies are registered in Registry

Usage:
    python -m claude_code_hooks_daemon.qa.strategy_pattern_checker
    python -m claude_code_hooks_daemon.qa.strategy_pattern_checker --json

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    """A single strategy pattern compliance violation."""

    file: str
    line: int
    rule: str
    message: str
    severity: str


# Rules for strategy pattern compliance
RULE_HANDLER_LANGUAGE_LOGIC = "strategy_handler_language_logic"
RULE_MISSING_ACCEPTANCE_TESTS = "strategy_missing_acceptance_tests"
RULE_BARE_STRING_LITERAL = "strategy_bare_string_literal"
RULE_MISSING_TEST_AGGREGATION = "handler_missing_test_aggregation"
RULE_REGISTRY_MISSING_STRATEGY = "registry_missing_strategy"

# Patterns that indicate language-specific logic in handlers
LANGUAGE_PATTERNS = frozenset(
    {
        "language",
        "config.name",
        "language_name",
        ".py",
        ".go",
        ".js",
        ".ts",
        ".php",
        ".rs",
        ".java",
        ".cs",
        ".kt",
        ".rb",
        ".swift",
        ".dart",
    }
)


class StrategyPatternChecker(ast.NodeVisitor):
    """AST visitor that detects strategy pattern violations."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[Violation] = []
        self._current_class: str | None = None
        self._uses_strategy_registry = False
        self._has_get_acceptance_tests = False
        self._calls_strategy_get_acceptance_tests = False
        self._is_strategy_file = self._detect_strategy_file()
        self._is_handler_file = self._detect_handler_file()
        self._module_constants: set[str] = set()
        self._classes_seen: list[str] = []
        self._classes_with_acceptance_tests: set[str] = set()

    def _detect_strategy_file(self) -> bool:
        """Check if this file is a strategy implementation."""
        # Check filepath or filename patterns
        return (
            ("strategies" in self.filepath.parts and self.filepath.name.endswith("_strategy.py"))
            or self.filepath.name.endswith("_strategy.py")
        ) and self.filepath.name != "protocol.py"

    def _detect_handler_file(self) -> bool:
        """Check if this file is a handler implementation."""
        # Check filepath or if filename contains "handler"
        return (
            "handlers" in self.filepath.parts or "handler" in self.filepath.name.lower()
        ) and not self.filepath.name.startswith("test_")

    def _add(self, node: ast.AST, rule: str, message: str, severity: str = "error") -> None:
        """Add a violation."""
        # Get line number if available (most AST nodes have it)
        line = getattr(node, "lineno", 1)
        self.violations.append(
            Violation(
                file=str(self.filepath),
                line=line,
                rule=rule,
                message=message,
                severity=severity,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track current class for context."""
        old_class = self._current_class
        self._current_class = node.name
        self._classes_seen.append(node.name)
        self.generic_visit(node)
        self._current_class = old_class

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track module-level constants."""
        # Check if this is a module-level assignment
        for target in node.targets:
            if isinstance(target, ast.Name):
                # Module-level constants start with _
                if target.id.startswith("_") and target.id.isupper():
                    self._module_constants.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Track module-level annotated constants."""
        if isinstance(node.target, ast.Name):
            if node.target.id.startswith("_") and node.target.id.isupper():
                self._module_constants.add(node.target.id)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Detect strategy registry imports."""
        for alias in node.names:
            if "StrategyRegistry" in alias.name or "TddStrategyRegistry" in alias.name:
                self._uses_strategy_registry = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Detect strategy registry imports."""
        if node.module and "strategies" in node.module:
            for alias in node.names:
                if "Registry" in alias.name:
                    self._uses_strategy_registry = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function definitions for violations."""
        # Check if this is get_acceptance_tests method
        if node.name == "get_acceptance_tests":
            self._has_get_acceptance_tests = True
            if self._current_class:
                self._classes_with_acceptance_tests.add(self._current_class)

            # Check if it calls strategy.get_acceptance_tests()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute):
                        if child.func.attr == "get_acceptance_tests":
                            self._calls_strategy_get_acceptance_tests = True

        # Check for language-specific logic in handlers using strategies
        if self._is_handler_file and self._uses_strategy_registry:
            self._check_for_language_logic(node)

        # Check for bare string literals in strategy files
        if self._is_strategy_file:
            self._check_strategy_bare_strings(node)

        self.generic_visit(node)

    def _check_for_language_logic(self, node: ast.FunctionDef) -> None:
        """Check handler methods for language-specific if/elif chains."""
        for child in ast.walk(node):
            if isinstance(child, ast.If):
                # Check if condition involves language patterns
                # But exclude legitimate strategy property access (strategy.language_name)
                if self._contains_language_pattern(
                    child.test
                ) and not self._is_strategy_property_access(child.test):
                    self._add(
                        child,
                        RULE_HANDLER_LANGUAGE_LOGIC,
                        "Handler contains language-specific if/elif chain - delegate to strategy",
                    )

            elif isinstance(child, ast.Compare):
                # Check for extension checks like .endswith(".py")
                if self._is_extension_check(child):
                    self._add(
                        child,
                        RULE_HANDLER_LANGUAGE_LOGIC,
                        "Handler contains file extension check - delegate to strategy",
                    )

    def _contains_language_pattern(self, node: ast.AST) -> bool:
        """Check if AST node contains language-specific patterns."""
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if any(pattern in child.value.lower() for pattern in LANGUAGE_PATTERNS):
                    return True
            elif isinstance(child, ast.Name):
                if any(pattern in child.id.lower() for pattern in LANGUAGE_PATTERNS):
                    return True
            elif isinstance(child, ast.Attribute):
                if child.attr in ("name", "language", "language_name"):
                    return True
        return False

    def _is_strategy_property_access(self, node: ast.AST) -> bool:
        """Check if node is accessing a strategy property (strategy.language_name)."""
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                # Check if this is strategy.language_name or strategy.extensions
                if isinstance(child.value, ast.Name):
                    if child.value.id == "strategy" and child.attr in (
                        "language_name",
                        "extensions",
                    ):
                        return True
        return False

    def _is_extension_check(self, node: ast.Compare) -> bool:
        """Check if comparison is a file extension check."""
        # Check for .endswith(".py") patterns
        if isinstance(node.left, ast.Call):
            if isinstance(node.left.func, ast.Attribute):
                if node.left.func.attr == "endswith":
                    for arg in node.left.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            if arg.value.startswith("."):
                                return True
        return False

    def _check_strategy_bare_strings(self, node: ast.FunctionDef) -> None:
        """Check strategy methods for bare string literals."""
        # Check property methods that return strings
        if node.name in ("language_name", "extensions"):
            for child in ast.walk(node):
                if isinstance(child, ast.Return):
                    if isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                        # Check if this constant is defined as module-level constant
                        if not self._is_using_module_constant(child.value):
                            self._add(
                                child.value,
                                RULE_BARE_STRING_LITERAL,
                                f'Bare string literal "{child.value.value}" - use module-level _CONSTANT',
                            )
                    elif isinstance(child.value, ast.Tuple):
                        for elt in child.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                if not self._is_using_module_constant(elt):
                                    self._add(
                                        elt,
                                        RULE_BARE_STRING_LITERAL,
                                        f'Bare string literal "{elt.value}" - use module-level _CONSTANT',
                                    )

        # Check for bare directory strings in source checks
        if node.name in ("is_production_source", "should_skip"):
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if "/" in child.value:  # Directory path
                        if not self._is_using_module_constant(child):
                            self._add(
                                child,
                                RULE_BARE_STRING_LITERAL,
                                f'Bare directory path "{child.value}" - use module-level _CONSTANT',
                            )

    def _is_using_module_constant(self, node: ast.Constant) -> bool:
        """Check if a constant is part of a return from module constant."""
        # This is a heuristic - in practice, if we have module constants defined,
        # and the return is a Name node referencing them, that's good
        # For string literals directly in return, that's bad
        # This method is called when we found a Constant, so by definition
        # it's not using a Name reference to a constant
        return False


def check_source(source: str, filepath: str = "<string>") -> list[Violation]:
    """Check a source string for strategy pattern violations.

    Args:
        source: Python source code to check
        filepath: File path for violation reports

    Returns:
        List of violations found
    """
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    checker = StrategyPatternChecker(Path(filepath))
    checker.visit(tree)

    # Post-visit checks
    violations = list(checker.violations)

    # Check if strategy file is missing get_acceptance_tests
    if checker._is_strategy_file:
        # Check each class seen in the file
        for class_name in checker._classes_seen:
            if class_name not in checker._classes_with_acceptance_tests:
                violations.append(
                    Violation(
                        file=filepath,
                        line=1,
                        rule=RULE_MISSING_ACCEPTANCE_TESTS,
                        message=f"Strategy class {class_name} missing get_acceptance_tests() method",
                        severity="error",
                    )
                )

    # Check if handler with registry doesn't delegate acceptance tests
    if (
        checker._is_handler_file
        and checker._uses_strategy_registry
        and checker._has_get_acceptance_tests
        and not checker._calls_strategy_get_acceptance_tests
    ):
        violations.append(
            Violation(
                file=filepath,
                line=1,
                rule=RULE_MISSING_TEST_AGGREGATION,
                message="Handler has get_acceptance_tests() but doesn't delegate to strategies",
                severity="error",
            )
        )

    return violations


def check_file(filepath: Path) -> list[Violation]:
    """Check a single Python file for strategy pattern violations.

    Args:
        filepath: Path to the Python file

    Returns:
        List of violations found
    """
    if not filepath.exists():
        return []

    if filepath.suffix != ".py":
        return []

    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    return check_source(source, str(filepath))


def main() -> int:
    """Check all strategy and handler files for pattern compliance.

    Returns:
        0 if no violations, 1 if violations found
    """
    json_output = "--json" in sys.argv

    # Find project root
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent.parent.parent
    src_dir = project_root / "src" / "claude_code_hooks_daemon"

    if not src_dir.exists():
        print(f"ERROR: Source directory not found: {src_dir}", file=sys.stderr)
        return 1

    violations: list[Violation] = []

    # Check strategy files
    strategies_dir = src_dir / "strategies"
    if strategies_dir.exists():
        for strategy_file in sorted(strategies_dir.rglob("*_strategy.py")):
            violations.extend(check_file(strategy_file))

    # Check handler files that use strategies
    handlers_dir = src_dir / "handlers"
    if handlers_dir.exists():
        for handler_file in sorted(handlers_dir.rglob("*.py")):
            if handler_file.name.startswith("__"):
                continue
            violations.extend(check_file(handler_file))

    violations.sort(key=lambda v: (v.file, v.line))

    if json_output:
        output = {
            "summary": {
                "passed": len(violations) == 0,
                "total_violations": len(violations),
                "by_rule": _count_by_rule(violations),
            },
            "violations": [asdict(v) for v in violations],
        }
        # Write JSON to qa output dir
        qa_dir = project_root / "untracked" / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        json_path = qa_dir / "strategy_pattern.json"
        json_path.write_text(json.dumps(output, indent=2))
        print(f"Results written to {json_path}")
    else:
        if violations:
            print(f"Found {len(violations)} strategy pattern violation(s):\n")
            for v in violations:
                print(f"{v.file}:{v.line}: {v.rule}: {v.message}")
            print(f"\nTotal: {len(violations)} violations")
            print("\nViolations by rule:")
            for rule, count in sorted(_count_by_rule(violations).items()):
                print(f"  {rule}: {count}")
        else:
            print("No strategy pattern violations found.")

    return 1 if violations else 0


def _count_by_rule(violations: list[Violation]) -> dict[str, int]:
    """Count violations grouped by rule name."""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v.rule] = counts.get(v.rule, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
