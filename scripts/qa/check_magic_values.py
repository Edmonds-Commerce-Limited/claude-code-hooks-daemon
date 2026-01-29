#!/usr/bin/env python3
"""AST-based magic value detector for the Claude Code Hooks Daemon codebase.

Detects hardcoded strings and numbers that should use constants from
the constants module. Checks 8 categories:

1. Magic handler names (name="string" in Handler.__init__)
2. Magic tags (tags=["string", ...])
3. Magic tool names (tool_name == "Bash")
4. Magic config keys (config["enabled"])
5. Magic priorities (priority=10)
6. Magic timeouts (timeout=30)
7. Magic decisions (decision="allow")
8. Magic event types (event_type == "pre_tool_use")

Usage:
    python scripts/qa/check_magic_values.py
    python scripts/qa/check_magic_values.py --json  # JSON output

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Violation:
    """A single magic value violation."""

    file: str
    line: int
    column: int
    rule: str
    message: str


# Known config keys that should use ConfigKey constants
CONFIG_KEYS: frozenset[str] = frozenset({
    "enabled",
    "priority",
    "options",
    "enable_tags",
    "disable_tags",
    "idle_timeout_seconds",
    "log_level",
    "socket_path",
    "pid_file_path",
    "log_buffer_size",
    "request_timeout_seconds",
    "self_install_mode",
    "enable_hello_world_handlers",
    "input_validation",
})

# Known decision strings
DECISION_STRINGS: frozenset[str] = frozenset({
    "allow",
    "deny",
    "ask",
    "continue",
})

# Known event type strings
EVENT_TYPE_STRINGS: frozenset[str] = frozenset({
    "pre_tool_use",
    "post_tool_use",
    "session_start",
    "session_end",
    "stop",
    "subagent_stop",
    "pre_compact",
    "notification",
    "permission_request",
    "user_prompt_submit",
})


class MagicValueChecker(ast.NodeVisitor):
    """AST visitor that detects magic values in Python source."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[Violation] = []
        self._in_handler_init = False
        self._current_class_bases: list[str] = []

    def _add(self, node: ast.AST, rule: str, message: str) -> None:
        self.violations.append(
            Violation(
                file=str(self.filepath),
                line=node.lineno,
                column=node.col_offset,
                rule=rule,
                message=message,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class bases to know if we're in a Handler subclass."""
        old_bases = self._current_class_bases
        self._current_class_bases = [
            _get_name(b) for b in node.bases
        ]
        self.generic_visit(node)
        self._current_class_bases = old_bases

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track if we're inside __init__ of a Handler subclass."""
        is_handler_init = (
            node.name == "__init__"
            and "Handler" in " ".join(self._current_class_bases)
        )
        old = self._in_handler_init
        self._in_handler_init = is_handler_init
        self.generic_visit(node)
        self._in_handler_init = old

    def visit_Call(self, node: ast.Call) -> None:
        """Detect magic values in function/constructor calls."""
        # Check super().__init__() calls inside Handler subclasses
        if self._in_handler_init and _is_super_init(node):
            self._check_handler_init_keywords(node)

        # Check HookResult() calls for magic decisions
        func_name = _get_name(node.func)
        if func_name == "HookResult":
            self._check_hook_result_keywords(node)

        self.generic_visit(node)

    def _check_handler_init_keywords(self, node: ast.Call) -> None:
        """Check Handler.__init__ keyword args for magic values."""
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                self._add(
                    kw.value,
                    "magic-handler-name",
                    f'Magic handler name "{kw.value.value}" - use handler_id=HandlerID.XXX',
                )

            elif kw.arg == "priority" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                self._add(
                    kw.value,
                    "magic-priority",
                    f"Magic priority {kw.value.value} - use Priority.XXX constant",
                )

            elif kw.arg == "tags" and isinstance(kw.value, (ast.List, ast.Tuple)):
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        self._add(
                            elt,
                            "magic-tag",
                            f'Magic tag "{elt.value}" - use HandlerTag.XXX constant',
                        )

    def _check_hook_result_keywords(self, node: ast.Call) -> None:
        """Check HookResult() for magic decision strings."""
        for kw in node.keywords:
            if kw.arg == "decision" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                val = kw.value.value
                if val in DECISION_STRINGS:
                    self._add(
                        kw.value,
                        "magic-decision",
                        f'Magic decision "{val}" - use Decision.{val.upper()} enum',
                    )

    def visit_Compare(self, node: ast.Compare) -> None:
        """Detect magic tool name and event type comparisons."""
        if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            left_name = _get_name(node.left)

            # tool_name == "Bash"
            if left_name == "tool_name":
                for comp in node.comparators:
                    self._check_magic_tool_comparator(comp)

            # event_type == "pre_tool_use" or similar
            if left_name in ("event_type", "event_name", "hook_event"):
                for comp in node.comparators:
                    self._check_magic_event_comparator(comp)

            # "Bash" == tool_name (reversed)
            if len(node.comparators) == 1:
                comp_name = _get_name(node.comparators[0])
                if comp_name == "tool_name" and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    self._add(
                        node.left,
                        "magic-tool-name",
                        f'Magic tool name "{node.left.value}" - use ToolName.XXX constant',
                    )
                if comp_name in ("event_type", "event_name", "hook_event") and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    val = node.left.value
                    if val in EVENT_TYPE_STRINGS:
                        self._add(
                            node.left,
                            "magic-event-type",
                            f'Magic event type "{val}" - use EventID.XXX constant',
                        )

        self.generic_visit(node)

    def _check_magic_tool_comparator(self, node: ast.expr) -> None:
        """Check a comparator node for magic tool name strings."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self._add(
                node,
                "magic-tool-name",
                f'Magic tool name "{node.value}" - use ToolName.XXX constant',
            )
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    self._add(
                        elt,
                        "magic-tool-name",
                        f'Magic tool name "{elt.value}" - use ToolName.XXX constant',
                    )

    def _check_magic_event_comparator(self, node: ast.expr) -> None:
        """Check a comparator node for magic event type strings."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if val in EVENT_TYPE_STRINGS:
                self._add(
                    node,
                    "magic-event-type",
                    f'Magic event type "{val}" - use EventID.XXX constant',
                )
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value in EVENT_TYPE_STRINGS:
                    self._add(
                        elt,
                        "magic-event-type",
                        f'Magic event type "{elt.value}" - use EventID.XXX constant',
                    )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Detect magic config keys like config["enabled"]."""
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            key = node.slice.value
            if key in CONFIG_KEYS:
                # Check if the subscripted object looks config-like
                obj_name = _get_name(node.value)
                if obj_name in (
                    "config",
                    "handler_config",
                    "daemon_config",
                    "cfg",
                    "raw_config",
                    "handler_cfg",
                ):
                    self._add(
                        node.slice,
                        "magic-config-key",
                        f'Magic config key "{key}" - use ConfigKey.XXX constant',
                    )

        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        """Detect magic timeout keyword arguments."""
        if (
            node.arg == "timeout"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
            and not self._in_handler_init
        ):
            self._add(
                node.value,
                "magic-timeout",
                f"Magic timeout {node.value.value} - use Timeout.XXX constant",
            )
        self.generic_visit(node)


def _get_name(node: ast.AST) -> str:
    """Extract a simple name from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant):
        return str(node.value)
    return ""


def _is_super_init(node: ast.Call) -> bool:
    """Check if a Call node is super().__init__(...)."""
    if isinstance(node.func, ast.Attribute) and node.func.attr == "__init__":
        inner = node.func.value
        if isinstance(inner, ast.Call):
            return _get_name(inner.func) == "super"
    return False


def check_source(source: str, filepath: str = "<string>") -> list[Violation]:
    """Check a source string for magic values.

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

    checker = MagicValueChecker(Path(filepath))
    checker.visit(tree)
    return checker.violations


def check_file(filepath: Path) -> list[Violation]:
    """Check a single Python file for magic values.

    Args:
        filepath: Path to the Python file

    Returns:
        List of violations found
    """
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    return check_source(source, str(filepath))


def main() -> int:
    """Check all Python files in src/ directory for magic values.

    Returns:
        0 if no violations, 1 if violations found
    """
    json_output = "--json" in sys.argv

    # Find project root (where src/ is)
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent.parent
    src_dir = project_root / "src" / "claude_code_hooks_daemon"

    if not src_dir.exists():
        print(f"ERROR: Source directory not found: {src_dir}", file=sys.stderr)
        return 1

    violations: list[Violation] = []

    for pyfile in sorted(src_dir.rglob("*.py")):
        # Skip constants module itself (it defines the constants)
        if "constants" in pyfile.parts:
            continue
        violations.extend(check_file(pyfile))

    violations.sort(key=lambda v: (v.file, v.line, v.column))

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
        json_path = qa_dir / "magic_values.json"
        json_path.write_text(json.dumps(output, indent=2))
        print(f"Results written to {json_path}")
    else:
        if violations:
            print(f"Found {len(violations)} magic value violation(s):\n")
            for v in violations:
                print(f"{v.file}:{v.line}:{v.column}: {v.rule}: {v.message}")
            print(f"\nTotal: {len(violations)} violations")
            print("\nViolations by rule:")
            for rule, count in sorted(_count_by_rule(violations).items()):
                print(f"  {rule}: {count}")
        else:
            print("No magic value violations found.")

    return 1 if violations else 0


def _count_by_rule(violations: list[Violation]) -> dict[str, int]:
    """Count violations grouped by rule name."""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v.rule] = counts.get(v.rule, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
