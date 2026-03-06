"""SecurityAntipatternHandler - blocks security antipatterns in written code.

Prevents Write/Edit of files containing hardcoded secrets, dangerous functions,
or unsafe DOM manipulation patterns. This is a real-time defence layer that
complements static analysis rules (PHPStan/ESLint).

OWASP coverage: A02 (Cryptographic Failures), A03 (Injection).
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path

# Directories to skip (vendor code, test fixtures, documentation)
_SKIP_PATTERNS: tuple[str, ...] = (
    "/vendor/",
    "/node_modules/",
    "/tests/fixtures/",
    "/tests/assets/",
    ".env.example",
    "/docs/",
    "/CLAUDE/",
    "/eslint-rules/",  # ESLint rule files legitimately reference banned patterns
    "/tests/PHPStan/",  # PHPStan rule files legitimately reference banned patterns
)

# Hardcoded secret patterns (OWASP A02)
_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"sk_live_[a-zA-Z0-9]{24,}", "Stripe Secret Key"),
    (r"pk_live_[a-zA-Z0-9]{24,}", "Stripe Publishable Key (live)"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token"),
    (r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "Private Key"),
)

# PHP dangerous function patterns (OWASP A03)
_PHP_DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\beval\s*\(", "eval() - code injection risk"),
    (r"\bexec\s*\(", "exec() - command injection risk"),
    (r"\bshell_exec\s*\(", "shell_exec() - command injection risk"),
    (r"\bsystem\s*\(", "system() - command injection risk"),
    (r"\bpassthru\s*\(", "passthru() - command injection risk"),
    (r"\bproc_open\s*\(", "proc_open() - command injection risk"),
    (r"\bunserialize\s*\(", "unserialize() - object injection risk"),
)

# TypeScript/JavaScript dangerous patterns (OWASP A03)
_TS_DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\beval\s*\(", "eval() - code injection risk"),
    (r"\bnew\s+Function\s*\(", "new Function() - code injection risk"),
    (r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML - XSS risk"),
    (r"\.innerHTML\s*=", "innerHTML assignment - XSS risk"),
    (r"\bdocument\.write\s*\(", "document.write() - XSS risk"),
)


def _is_php_file(path: str) -> bool:
    """Check if file is a PHP file."""
    return path.endswith(".php")


def _is_ts_or_js_file(path: str) -> bool:
    """Check if file is a TypeScript or JavaScript file."""
    return any(path.endswith(ext) for ext in (".ts", ".tsx", ".js", ".jsx"))


def _should_skip(path: str) -> bool:
    """Check if file should be excluded from scanning."""
    return any(skip in path for skip in _SKIP_PATTERNS)


class SecurityAntipatternHandler(Handler):
    """Block Write/Edit of files containing security antipatterns.

    Scans content being written for:
    - Hardcoded secrets (AWS keys, Stripe keys, GitHub tokens, private keys)
    - PHP dangerous functions (eval, exec, shell_exec, system, passthru, etc.)
    - TypeScript/JS unsafe patterns (eval, new Function, dangerouslySetInnerHTML)

    Excludes vendor code, test fixtures, documentation, and rule definition files.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SECURITY_ANTIPATTERN,
            priority=Priority.SECURITY_ANTIPATTERN,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
            ],
        )

    def _get_content(self, hook_input: dict[str, Any]) -> str:
        """Extract content from hook input, handling Write vs Edit."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.EDIT:
            tool_input: dict[str, str] = hook_input.get(HookInputField.TOOL_INPUT, {})
            return tool_input.get("new_string", "")
        content = get_file_content(hook_input)
        return content or ""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing security antipatterns to a source file."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        if _should_skip(file_path):
            return False

        content = self._get_content(hook_input)
        if not content:
            return False

        # Check for hardcoded secrets in any file type
        for pattern, _ in _SECRET_PATTERNS:
            if re.search(pattern, content):
                return True

        # Check PHP-specific patterns
        if _is_php_file(file_path):
            for pattern, _ in _PHP_DANGEROUS_PATTERNS:
                if re.search(pattern, content):
                    return True

        # Check TS/JS-specific patterns
        if _is_ts_or_js_file(file_path):
            for pattern, _ in _TS_DANGEROUS_PATTERNS:
                if re.search(pattern, content):
                    return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the write with details of what was detected."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        content = self._get_content(hook_input)
        if not content:
            return HookResult(decision=Decision.ALLOW)

        issues: list[str] = []

        # Check secrets
        for pattern, label in _SECRET_PATTERNS:
            if re.search(pattern, content):
                issues.append(f"[A02] {label}")

        # Check PHP patterns
        if _is_php_file(file_path):
            for pattern, label in _PHP_DANGEROUS_PATTERNS:
                if re.search(pattern, content):
                    issues.append(f"[A03] {label}")

        # Check TS/JS patterns
        if _is_ts_or_js_file(file_path):
            for pattern, label in _TS_DANGEROUS_PATTERNS:
                if re.search(pattern, content):
                    issues.append(f"[A03] {label}")

        if not issues:
            return HookResult(decision=Decision.ALLOW)

        issues_text = "\n".join(f"  - {issue}" for issue in issues)

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"SECURITY ANTIPATTERN BLOCKED\n\n"
                f"File: {file_path}\n\n"
                f"Issues detected ({len(issues)}):\n"
                f"{issues_text}\n\n"
                "These patterns indicate security vulnerabilities (OWASP A02/A03).\n\n"
                "CORRECT APPROACH:\n"
                "  - Secrets: Use environment variables, never hardcode credentials\n"
                "  - eval/exec: Use safe alternatives (JSON.parse, Symfony Process)\n"
                "  - innerHTML/dangerouslySetInnerHTML: Use React JSX or sanitise input\n"
                "  - unserialize: Use json_decode() instead\n\n"
                "If this is test fixture code, place it in tests/fixtures/ or tests/assets/.\n"
                "If this is rule documentation, place it in docs/ or eslint-rules/."
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for security antipattern handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block PHP eval in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.php' "
                    "with content '<?php eval($userInput);'"
                ),
                description="Blocks writing PHP file with eval() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"eval\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Block hardcoded AWS key",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/config.ts' "
                    "with content 'const key = \"AKIAIOSFODNN7EXAMPLE1\";'"
                ),
                description="Blocks writing file with hardcoded AWS access key",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"AWS Access Key",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow test fixture files",
                command=(
                    "Use the Write tool to write file_path='/workspace/tests/fixtures/security_test.php' "
                    "with content '<?php eval($testInput);'"
                ),
                description="Allows writing eval in test fixture files (excluded path)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Test fixtures are excluded from security scanning.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
