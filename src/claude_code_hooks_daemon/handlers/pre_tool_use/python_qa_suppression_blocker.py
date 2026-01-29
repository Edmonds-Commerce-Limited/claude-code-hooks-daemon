"""PythonQaSuppressionBlocker - blocks QA suppression comments in Python code."""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path


class PythonQaSuppressionBlocker(Handler):
    """Block QA suppression comments in Python code."""

    FORBIDDEN_PATTERNS: ClassVar[list[str]] = [
        r"#\s*type:\s*ignore",  # MyPy
        r"#\s*noqa",  # Ruff/Flake8
        r"#\s*pylint:\s*disable",  # Pylint
        r"#\s*pyright:\s*ignore",  # Pyright
        r"#\s*mypy:\s*ignore-errors",  # MyPy module-level
    ]

    CHECK_EXTENSIONS: ClassVar[list[str]] = [".py"]

    def __init__(self) -> None:
        super().__init__(
            name="python-qa-suppression-blocker",
            priority=Priority.PYTHON_QA_SUPPRESSION,
            tags=[
                HandlerTag.PYTHON,
                HandlerTag.QA_SUPPRESSION_PREVENTION,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing Python QA suppression comments."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Case-insensitive extension check
        file_path_lower = file_path.lower()
        if not any(file_path_lower.endswith(ext) for ext in self.CHECK_EXTENSIONS):
            return False

        # Skip test fixtures, migrations, vendor directories
        if any(
            skip in file_path
            for skip in ["tests/fixtures/", "migrations/", "vendor/", ".venv/", "venv/"]
        ):
            return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # Check for forbidden patterns
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block Python QA suppressions."""
        file_path = get_file_path(hook_input)
        content = get_file_content(hook_input)
        if hook_input.get(HookInputField.TOOL_NAME) == "Edit":
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return HookResult(decision=Decision.ALLOW)

        # Find which pattern matched
        issues = []
        for pattern in self.FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                issues.append(match.group(0))

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: Python QA suppression comments are not allowed\n\n"
                f"File: {file_path}\n\n"
                f"Found {len(issues)} suppression comment(s):\n"
                + "\n".join(f"  - {issue}" for issue in issues[:5])
                + "\n\n"
                "WHY: Suppression comments hide real problems and create technical debt.\n"
                "Type errors, style violations, and complexity warnings exist for good reason.\n\n"
                "✅ CORRECT APPROACH:\n"
                "  1. Fix the underlying issue (don't suppress)\n"
                "  2. Add proper type annotations instead of using # type: ignore\n"
                "  3. Refactor code to meet quality standards (complexity, naming, etc.)\n"
                "  4. If rule is genuinely wrong for your project, update pyproject.toml\n"
                "  5. For test-specific code, ensure file is in tests/ directory\n"
                "  6. For legacy code requiring suppression:\n"
                "     - Add detailed comment explaining WHY suppression is needed\n"
                "     - Create ticket to fix properly\n"
                "     - Link ticket in comment\n\n"
                "Quality tools exist to prevent bugs. Fix the code, don't silence the tool.\n\n"
                "Resources:\n"
                "  - MyPy: https://mypy.readthedocs.io/\n"
                "  - Ruff: https://docs.astral.sh/ruff/\n"
                "  - Pylint: https://pylint.readthedocs.io/"
            ),
        )
