"""SecurityAntipatternHandler - blocks security antipatterns in written code.

Inspects content written via Write or Edit tools and denies if the new content
contains security antipatterns defined by registered strategies.

Uses Strategy Pattern: all language-specific pattern logic is delegated to
SecurityStrategy implementations.  The handler has ZERO language awareness.

OWASP coverage: A02 (Cryptographic Failures), A03 (Injection).
"""

import re
from typing import Any, cast

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.security.common import should_skip
from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.strategies.security.registry import (
    SecurityStrategyRegistry,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
)

# Config key hint shown in the denial message
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.security_antipattern"

# OWASP category used by the universal secret-detection strategy -- the ONE
# clean signal that separates hardcoded credentials from everything else
# (every other strategy tags its patterns "A03").
_OWASP_CREDENTIALS = "A02"

# Real category structure (Plan 00116): every strategy's ``SecurityPattern.name``
# ends with a mechanism suffix ("code injection", "command injection",
# "(XML) deserialization"/"object injection", "XSS"), which is a cleaner and
# more precise signal than the coarse two-value OWASP code every strategy
# carries. Checked in this order because "object injection" (deserialisation)
# would otherwise also read as a kind of injection.
_XSS_MARKERS: tuple[str, ...] = ("xss",)
_DESERIALISATION_MARKERS: tuple[str, ...] = ("deserialization", "object injection")
_CMD_INJECTION_MARKERS: tuple[str, ...] = ("command injection",)
_CODE_INJECTION_MARKERS: tuple[str, ...] = (
    "code injection",
    "dynamic import injection",
    "code execution",
    "dynamic script execution",
)


def _classify_pattern(pattern: SecurityPattern) -> str:
    """Map a SecurityPattern to its Plan 00116 category RuleID.

    Rust's ``from_raw_parts``/``transmute`` fit none of the five OWASP-named
    mechanisms below (they are memory/type-safety bypasses, not injection,
    deserialisation, XSS or a credential) -- SEC_UNSAFE_MEMORY is the
    fall-through for exactly that outlier pair, not a catch-all.
    """
    if pattern.owasp == _OWASP_CREDENTIALS:
        return RuleID.SEC_HARDCODED_CREDS
    name_lower = pattern.name.lower()
    if any(marker in name_lower for marker in _XSS_MARKERS):
        return RuleID.SEC_XSS
    if any(marker in name_lower for marker in _DESERIALISATION_MARKERS):
        return RuleID.SEC_DESERIALISATION
    if any(marker in name_lower for marker in _CMD_INJECTION_MARKERS):
        return RuleID.SEC_CMD_INJECTION
    if any(marker in name_lower for marker in _CODE_INJECTION_MARKERS):
        return RuleID.SEC_CODE_INJECTION
    return RuleID.SEC_UNSAFE_MEMORY


_RULE_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        RuleID.SEC_CODE_INJECTION,
        "`eval`, `exec`, `new Function`, `__import__`, `instance_eval`, `yaml.load`",
        "Dynamic execution of a string as code",
        "Avoid dynamic code execution; use safe parsing/import alternatives",
    ),
    (
        RuleID.SEC_CMD_INJECTION,
        "`os.system`, `subprocess(..., shell=True)`, `shell_exec`, `proc_open`, "
        "`Runtime.exec`, `Process.Start`, `IO.popen`",
        "Shell command construction from untrusted input enables command injection",
        "Use argument-list APIs (no shell=True) instead of shell string concatenation",
    ),
    (
        RuleID.SEC_DESERIALISATION,
        "`pickle.load`, `Marshal.load`, `unserialize`, `ObjectInputStream`, "
        "`XMLDecoder`, `BinaryFormatter`",
        "Deserialising untrusted data can execute arbitrary code",
        "Use a safe serialisation format (e.g. JSON) instead",
    ),
    (
        RuleID.SEC_XSS,
        "`innerHTML`, `dangerouslySetInnerHTML`, `document.write`, " "`template.HTML`/`JS`/`URL`",
        "Injects unescaped content into the DOM/output, enabling XSS",
        "Use the framework's safe templating/escaping APIs",
    ),
    (
        RuleID.SEC_HARDCODED_CREDS,
        "AWS access keys, GitHub tokens, Stripe keys, private key blocks",
        "Hardcoded credentials leak via source control history and code review",
        "Use environment variables, never hardcode credentials",
    ),
    (
        RuleID.SEC_UNSAFE_MEMORY,
        "Rust `from_raw_parts`, `transmute`",
        "Bypasses Rust's memory/type safety guarantees",
        "Use safe conversions (`as`, `From`/`Into`) or validated slice operations",
    ),
)


def _verbose_content(why: str) -> str:
    """Build the full first-fire teaching content for a rule from its "why"."""
    return (
        f"{why}.\n\n"
        "This is pattern matching on known-dangerous constructs, not analysis -- "
        "it does NOT detect SQL injection, weak hashing, or path traversal (those "
        "are properties of how a value FLOWS, which a regex cannot see). Do not "
        "read a passing write as 'this code is secure'.\n\n"
        "If this is test fixture code, place it in tests/fixtures/ or tests/assets/.\n"
        "If this is rule documentation, place it in docs/ or eslint-rules/.\n\n"
        f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
    )


class SecurityAntipatternHandler(PreToolUseHandlerBase):
    """Block Write/Edit of files containing security antipatterns.

    Scans content being written for security antipatterns defined by
    registered SecurityStrategy implementations.  The handler orchestrates
    without any knowledge of specific languages or pattern types.

    Excludes vendor code, test fixtures, documentation, and rule definition
    files via the shared should_skip() utility.

    Configuration options (set via YAML config):
        languages: list[str] | None — Restrict enforcement to specific languages.
            If unset or empty, ALL registered strategies are enforced (default).
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
        self._registry = SecurityStrategyRegistry.create_default()
        self._languages: list[str] | None = None
        self._languages_applied: bool = False
        # Client-configured exclude globs (Plan 00150), layered on top of the
        # built-in should_skip() defaults; project default injected by registry.
        self._exclude_paths: list[str] | None = None
        self._rules: tuple[Rule, ...] = tuple(
            Rule(
                rule_id=rule_id,
                blocked=blocked,
                why=why,
                fix=fix,
                verbose=_verbose_content(why),
            )
            for rule_id, blocked, why, fix in _RULE_DEFINITIONS
        )
        self._rules_by_id: dict[str, Rule] = {rule.rule_id: rule for rule in self._rules}
        self._formatter = RuleFormatter()

    # ------------------------------------------------------------------
    # Language filter (applied lazily on first use)
    # ------------------------------------------------------------------

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or self._project_languages
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    # ------------------------------------------------------------------
    # Handler interface
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if the content being written contains a security antipattern.

        Only matches Write and Edit tool calls for files not in skip directories.
        Returns False for all other tools or empty content.
        """
        self._apply_language_filter()

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return False

        # Single scan path: _find_all_violations applies the skip-directory guard,
        # so matches() and handle() can never disagree on which files are scanned.
        return bool(self._find_all_violations(content, file_path))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny write if content contains security antipatterns, allow otherwise."""
        file_path = get_file_path(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "")

        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return GatingResult(decision=Decision.ALLOW)

        issues = self._find_all_violations(content, file_path)
        if not issues:
            return GatingResult(decision=Decision.ALLOW)

        return GatingResult(
            decision=Decision.DENY,
            reason=self._format_reason(hook_input, issues, file_path),
        )

    def get_rules(self) -> list[Rule]:
        """Return the 6 Rule objects backing this handler's blocking behaviour."""
        return list(self._rules)

    def get_claude_md(self) -> str | None:
        return (
            "## security_antipattern — OWASP security antipatterns are blocked\n\n"
            "A `Write`/`Edit` of code containing security antipatterns is blocked, "
            "across all "
            "supported languages. Fix the code to use safe patterns instead.\n\n"
            "**Blocked categories**:\n"
            "- Code injection: `eval`, `exec`, `new Function`, `__import__`, "
            "`instance_eval`, `yaml.load` — dynamic execution of a string\n"
            "- Command injection: `os.system`, `subprocess(..., shell=True)`, "
            "`shell_exec`, `proc_open`, `Runtime.exec`, `Process.Start`, `IO.popen`\n"
            "- Unsafe deserialization: `pickle.load`, `Marshal.load`, `unserialize`, "
            "`ObjectInputStream`, `XMLDecoder`, `BinaryFormatter`\n"
            "- XSS: `innerHTML`, `dangerouslySetInnerHTML`, `document.write`, "
            "`template.HTML`/`JS`/`URL`\n"
            "- Hardcoded credentials: AWS access keys, GitHub tokens, Stripe keys, "
            "private key blocks\n\n"
            "**This is pattern matching on known-dangerous constructs, not analysis.** "
            "It does NOT detect SQL injection, weak hashing, or path traversal — those "
            "are properties of how a value FLOWS, which a regex cannot see. Do not read "
            "a passing write as 'this code is secure'.\n\n"
            "**Supported languages**: Python, JavaScript/TypeScript, Go, PHP, Ruby, "
            "Java, Kotlin, C#, Rust, Swift, Dart. Coverage varies by language — a "
            "construct blocked in one is not necessarily blocked in another.\n\n"
            "**Excluded paths**: vendor/, node_modules/, and test fixtures are skipped "
            "by default. Exempt more paths with glob patterns via "
            "`handlers.pre_tool_use.security_antipattern.options.exclude_paths` or the "
            "project-wide `daemon.exclude_paths`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests aggregated from all registered strategies."""
        tests: list[Any] = []
        seen_languages: set[str] = set()
        for strategy in self._registry.all_strategies:
            if strategy.language_name in seen_languages:
                continue
            seen_languages.add(strategy.language_name)
            if hasattr(strategy, "get_acceptance_tests"):
                tests.extend(strategy.get_acceptance_tests())
        return tests

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_new_content(self, hook_input: dict[str, Any], tool_name: str) -> str | None:
        """Extract the new content being written from the hook input.

        For Write: returns the 'content' field.
        For Edit: returns the 'new_string' field.
        """
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.WRITE:
            return cast("str", tool_input.get("content", ""))
        if tool_name == ToolName.EDIT:
            return cast("str", tool_input.get("new_string", ""))
        return None

    def _find_all_violations(self, content: str, file_path: str) -> list[SecurityPattern]:
        """Return all matching security patterns across all applicable strategies.

        Files in skip directories (vendor, node_modules, test fixtures, etc.) are
        never scanned: the skip-directory guard lives HERE so every caller
        (matches() and handle()) applies it, even on a direct handle() call.
        """
        if should_skip(file_path) or self._is_excluded(file_path):
            return []
        violations: list[SecurityPattern] = []
        strategies = self._registry.get_strategies(file_path)
        for strategy in strategies:
            for pattern in strategy.patterns:
                if re.search(pattern.regex, content):
                    violations.append(pattern)
        return violations

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if file_path matches a client-configured exclude glob."""
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
        )

    def _format_reason(
        self, hook_input: dict[str, Any], issues: list[SecurityPattern], file_path: str
    ) -> str:
        """Build a human-readable denial message for matched patterns.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G), keyed on the FIRST
        matched issue's category -- mirroring destructive_git's first-hit
        semantics when multiple categories match in one write. The
        per-invocation diagnostic (file, every matched issue, every
        suggestion) is dynamic and always fully present -- only the
        surrounding category-specific teaching prose goes terse on repeat
        fires.
        """
        issues_text = "\n".join(f"  - [{issue.owasp}] {issue.name}" for issue in issues)

        # Collect unique suggestions
        suggestions = []
        seen_suggestions: set[str] = set()
        for issue in issues:
            if issue.suggestion not in seen_suggestions:
                seen_suggestions.add(issue.suggestion)
                suggestions.append(f"  - {issue.suggestion}")
        suggestions_text = "\n".join(suggestions)

        dynamic_detail = (
            f"File: {file_path}\n\n"
            f"Issues detected ({len(issues)}):\n"
            f"{issues_text}\n\n"
            f"CORRECT APPROACH:\n"
            f"{suggestions_text}"
        )

        rule = self._rules_by_id[_classify_pattern(issues[0])]
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return f"{message}\n\n{dynamic_detail}"
