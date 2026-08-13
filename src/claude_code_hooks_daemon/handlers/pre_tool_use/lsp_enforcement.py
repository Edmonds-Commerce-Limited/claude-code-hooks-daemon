"""LspEnforcementHandler - steers LLMs toward LSP tools instead of Grep/Bash grep.

Claude Code has LSP tools (goToDefinition, findReferences, hover, documentSymbol,
workspaceSymbol) providing semantic ~50ms code intelligence. But LLMs default to
Grep/Glob/Bash(grep/rg) for code navigation — slow, imprecise text searches.

This handler detects Grep and Bash(grep/rg) patterns that look like symbol lookups
and steers the LLM toward LSP tools instead.

Modes:
    block_once (default): Block first symbol grep with DENY, allow retries
    advisory: Always ALLOW with LSP guidance
    strict: Always DENY

No-LSP modes (when ENABLE_LSP_TOOL env var not set):
    block (default): Block anyway, include LSP setup guidance
    advisory: Downgrade to advisory when LSP not available
    disable: Handler doesn't match when LSP not available
"""

import logging
import os
import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer
from claude_code_hooks_daemon.core.utils import get_bash_command

logger = logging.getLogger(__name__)

# --- Mode constants ---


class LspEnforcementMode:
    """Handler mode options."""

    BLOCK_ONCE = "block_once"
    ADVISORY = "advisory"
    STRICT = "strict"


class NoLspMode:
    """Behavior when LSP is not configured."""

    BLOCK = "block"
    ADVISORY = "advisory"
    DISABLE = "disable"


# --- Environment variable ---

_LSP_ENV_VAR = "ENABLE_LSP_TOOL"

# --- Pattern detection constants ---

# Definition keywords that precede a symbol name
_DEFINITION_KEYWORDS = re.compile(
    r"^(class|def|function|interface|struct|enum|type|trait|impl)\s+[A-Za-z_]\w*$"
)

# Import pattern: 'import SomeSymbol' or 'from X import Y'
_IMPORT_PATTERN = re.compile(r"^(import|from)\s+\w+")

# PascalCase identifier (at least two capital segments, e.g., FrontController)
_PASCAL_CASE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+$")

# snake_case identifier with at least one underscore (e.g., get_bash_command)
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

# Regex metacharacters that indicate a regex pattern rather than a symbol
_REGEX_METACHAR_PATTERN = re.compile(r"[.*+?{}()|\\^\[\]$]")

# Comment markers / annotation patterns (not symbols)
_COMMENT_MARKERS = frozenset(
    {
        "TODO",
        "FIXME",
        "HACK",
        "XXX",
        "NOTE",
        "WARN",
        "WARNING",
        "DEPRECATED",
        "BUG",
        "REVIEW",
    }
)

# Single-segment capitalised identifier (e.g. 'Path', 'HandlerID') used to
# classify a name imported via 'import X'. Distinct from _PASCAL_CASE, which
# requires at least two capitalised segments; a one-word capitalised import
# target (e.g. 'import Path') is still a symbol lookup worth steering to LSP.
_IMPORTED_SYMBOL = re.compile(r"^[A-Z][a-zA-Z0-9]+$")

# Bash grep/rg command pattern
_BASH_GREP_PATTERN = re.compile(r"(?:^|\s|&&|\|\||;)\s*(?:grep|rg)\s+")

# Flag-skip group consumed before the search pattern in a grep/rg command.
# Handles, in priority order:
#   - long flag with attached value:   --type=py
#   - long flag with separate value:   --type py   (value skipped, not the symbol)
#   - clustered/short flag(s):         -rn  -e  -r
# The negative lookahead on the separate-value branch stops the flag-skip from
# swallowing a quoted search term as if it were a flag value.
_FLAG_SKIP = (
    r"(?:" r"--[A-Za-z][\w-]*=\S+\s+" r"|--[A-Za-z][\w-]*\s+(?![\"'])\S+\s+" r"|-[A-Za-z]+\s+" r")*"
)

# Extract the search pattern from a bash grep/rg command. Group 1 captures a
# quoted pattern, group 2 captures an unquoted token.
_BASH_GREP_EXTRACT = re.compile(
    rf"(?:grep|rg)\s+{_FLAG_SKIP}[\"']([^\"']+)[\"']" rf"|(?:grep|rg)\s+{_FLAG_SKIP}(\S+)"
)

# Recursive-scan indicators for a Bash grep/rg command. Only the SHORT-flag
# branch admits any cluster containing r/R (grep's only letter meaning
# "recursive" — no other GNU grep short option overlaps with it); the
# negative lookahead after the leading '-' stops that branch from reaching
# into a LONG flag name that merely happens to contain the letter (e.g.
# --color). Long flags are matched by exact name only.
_RECURSIVE_SCAN_FLAG = re.compile(r"(?<![\w-])-(?:-recursive\b|(?!-)[A-Za-z]*[rR][A-Za-z]*\b)")

# Shell segment terminators — a Bash grep/rg invocation's positional
# arguments stop at the first one of these (or end of string).
#
# A NEWLINE belongs here for the same reason ``;`` does: bash treats both as
# top-level command separators. Omitting it (Plan 00234/00236) meant every
# subsequent LINE of a multi-line script was counted as another positional
# argument to the grep, so the single-file exemption survived only in
# one-liners.
_SEGMENT_TERMINATOR = re.compile(r"&&|\|\||[;|\n]")

# --- LSP operation mapping ---

_LSP_OP_DEFINITION = "goToDefinition"
_LSP_OP_REFERENCES = "findReferences"
_LSP_OP_WORKSPACE_SYMBOL = "workspaceSymbol"


class LspEnforcementHandler(Handler):
    """Enforce LSP tool usage instead of Grep/Bash grep for symbol lookups.

    Detects patterns like 'class ClassName', 'def func_name', PascalCase identifiers,
    and snake_case identifiers in Grep tool and Bash grep/rg commands.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LSP_ENFORCEMENT,
            priority=Priority.LSP_ENFORCEMENT,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def get_default_enabled(self) -> bool:
        """Opt-in handler — off by default (Plan 00133).

        LSP enforcement steers agents toward LSP tools instead of Grep, but
        many projects have no LSP configured, so it ships disabled and clients
        opt in. Must stay consistent with the ``enabled: false`` flag in the
        config template (enforced by ``test_default_enabled_template_consistency``).
        """
        return False

    def _get_mode(self) -> str:
        """Get configured mode (set by registry via setattr)."""
        return getattr(self, "_mode", LspEnforcementMode.BLOCK_ONCE)

    def _get_no_lsp_mode(self) -> str:
        """Get configured no_lsp_mode (set by registry via setattr)."""
        return getattr(self, "_no_lsp_mode", NoLspMode.BLOCK)

    def _is_lsp_available(self) -> bool:
        """Check if LSP is configured via environment variable."""
        return bool(os.environ.get(_LSP_ENV_VAR))

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler.

        Returns 0 when the data layer is unavailable (RuntimeError raised by
        ProjectContext resolution). The failure is logged rather than silently
        swallowed so a persistently unavailable/corrupt history is observable.
        Unexpected exceptions propagate (FAIL FAST) instead of degrading the
        block_once gate to permanently-allow.
        """
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except RuntimeError as exc:
            logger.warning("LSP enforcement could not read block history: %s", exc)
            return 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a symbol-like grep that LSP could handle better."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Only intercept Grep and Bash tools
        if tool_name not in (ToolName.GREP, ToolName.BASH):
            return False

        # If no_lsp_mode=disable and LSP not available, skip
        if self._get_no_lsp_mode() == NoLspMode.DISABLE and not self._is_lsp_available():
            return False

        # A Bash grep/rg already scoped to ONE named file is a literal-string
        # check on a file the caller already knows about, not a project-wide
        # symbol lookup — LSP's goToDefinition/findReferences/workspaceSymbol
        # have nothing extra to offer over just reading that one file.
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command and self._is_single_file_bash_grep(command):
                return False

        # Extract the search pattern
        pattern = self._extract_search_pattern(hook_input, tool_name)
        if not pattern:
            return False

        return self._is_symbol_like(pattern)

    def _is_single_file_bash_grep(self, command: str) -> bool:
        """True when EVERY grep/rg invocation in the command names one file.

        The exemption describes the whole command, so one narrow grep must not
        buy cover for a project-wide one later in the same call — with only the
        first invocation inspected, ``grep -n x a.py`` followed by
        ``grep -rn x src/`` was exempt on the strength of its first line.
        """
        matches = list(_BASH_GREP_EXTRACT.finditer(command))
        if not matches:
            return False
        return all(self._invocation_targets_one_file(command, match) for match in matches)

    def _invocation_targets_one_file(self, command: str, match: re.Match[str]) -> bool:
        """True when a single grep/rg invocation's target is exactly one named file.

        False (i.e. "still enforce") whenever the scan could plausibly touch
        more than one file: a recursive flag, a directory-looking target
        (trailing ``/``, ``.``/``..``), a glob, more than one positional
        argument, or NO target at all (defaults to the whole cwd/stdin).
        """
        invocation = command[match.start() : match.end()]
        if _RECURSIVE_SCAN_FLAG.search(invocation):
            return False

        tail = command[match.end() :]
        terminator = _SEGMENT_TERMINATOR.search(tail)
        if terminator:
            tail = tail[: terminator.start()]
        targets = tail.split()

        if len(targets) != 1:
            return False
        target = targets[0]
        if target in (".", ".."):
            return False
        if target.endswith("/"):
            return False
        if any(glob_char in target for glob_char in ("*", "?", "[")):
            return False
        return True

    def _extract_search_pattern(
        self, hook_input: dict[str, Any], tool_name: str | None
    ) -> str | None:
        """Extract the search pattern from Grep tool or Bash grep/rg command."""
        if tool_name == ToolName.GREP:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT)
            if not isinstance(tool_input, dict):
                return None
            return tool_input.get("pattern")

        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if not command:
                return None
            # Only match if this is a grep/rg command
            if not _BASH_GREP_PATTERN.search(command):
                return None
            return self._extract_bash_grep_pattern(command)

        return None

    def _extract_bash_grep_pattern(self, command: str) -> str | None:
        """Extract the search pattern from a bash grep/rg command string."""
        match = _BASH_GREP_EXTRACT.search(command)
        if not match:
            return None
        # Group 1 is quoted pattern, group 2 is unquoted
        return match.group(1) or match.group(2)

    def _is_symbol_like(self, pattern: str) -> bool:
        """Determine if a search pattern looks like a symbol lookup vs text search.

        Returns True if pattern appears to be a symbol name (identifier).
        Returns False if pattern appears to be a regex/text search.
        """
        pattern = pattern.strip()
        if not pattern:
            return False

        # Comment markers are not symbols
        if pattern in _COMMENT_MARKERS:
            return False

        # Definition keywords: 'class Foo', 'def bar', 'interface Baz'
        if _DEFINITION_KEYWORDS.match(pattern):
            return True

        # Import pattern: 'import X'
        if _IMPORT_PATTERN.match(pattern):
            # Only if the imported name looks like a symbol
            parts = pattern.split()
            if len(parts) >= 2:
                last_part = parts[-1]
                if _PASCAL_CASE.match(last_part) or _SNAKE_CASE.match(last_part):
                    return True
                # Short single-segment capitalised import target is still a symbol
                if _IMPORTED_SYMBOL.match(last_part):
                    return True
            return False

        # If pattern contains regex metacharacters, it's a regex search
        if _REGEX_METACHAR_PATTERN.search(pattern):
            return False

        # PascalCase identifier (e.g., FrontController, HookResult)
        if _PASCAL_CASE.match(pattern):
            return True

        # snake_case identifier with underscores (e.g., get_bash_command)
        if _SNAKE_CASE.match(pattern):
            return True

        # Anything else (multi-word text, bare lowercase words, etc.) is a text
        # search, not a symbol lookup.
        return False

    def _suggest_lsp_operation(self, pattern: str) -> str:
        """Map a grep pattern to the most appropriate LSP operation."""
        pattern = pattern.strip()

        # Definition patterns -> goToDefinition + workspaceSymbol
        if _DEFINITION_KEYWORDS.match(pattern):
            return _LSP_OP_DEFINITION

        # Import patterns -> findReferences
        if _IMPORT_PATTERN.match(pattern):
            return _LSP_OP_REFERENCES

        # Plain identifiers -> workspaceSymbol (broad search) or findReferences
        return _LSP_OP_WORKSPACE_SYMBOL

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle a symbol-like grep, steering toward LSP tools."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        pattern = self._extract_search_pattern(hook_input, tool_name) or ""
        lsp_available = self._is_lsp_available()
        mode = self._get_mode()
        no_lsp_mode = self._get_no_lsp_mode()

        # If LSP not available and no_lsp_mode=advisory, downgrade to advisory
        if not lsp_available and no_lsp_mode == NoLspMode.ADVISORY:
            mode = LspEnforcementMode.ADVISORY

        suggested_op = self._suggest_lsp_operation(pattern)
        reason = self._build_reason(pattern, suggested_op, lsp_available)

        # Determine decision based on mode
        if mode == LspEnforcementMode.ADVISORY:
            return HookResult(decision=Decision.ALLOW, context=[reason])

        if mode == LspEnforcementMode.STRICT:
            return HookResult(decision=Decision.DENY, reason=reason)

        # block_once: deny first time, allow subsequent
        block_count = self._get_block_count()
        if block_count == 0:
            return HookResult(decision=Decision.DENY, reason=reason)
        return HookResult(decision=Decision.ALLOW, context=[reason])

    def _build_reason(self, pattern: str, suggested_op: str, lsp_available: bool) -> str:
        """Build the guidance message for the LLM."""
        lines = [
            f"LSP tool available for this lookup: pattern '{pattern}' looks like a symbol search.",
            "",
            f"Suggested LSP operation: {suggested_op}",
            "",
            "Available LSP operations:",
            "  - goToDefinition: Find where a symbol is defined",
            "  - findReferences: Find all references to a symbol",
            "  - workspaceSymbol: Search for symbols across the workspace",
            "  - hover: Get type info and documentation for a symbol",
            "  - documentSymbol: Get all symbols in a file",
        ]

        if not lsp_available:
            lines.extend(
                [
                    "",
                    "NOTE: LSP is not currently configured.",
                    f"Set {_LSP_ENV_VAR}=1 in your environment to enable LSP tools.",
                ]
            )

        return "\n".join(lines)

    def get_claude_md(self) -> str | None:
        return (
            "## lsp_enforcement — use LSP tools for code symbol lookups\n\n"
            "Using `Grep` or `Bash` (grep/rg) to find class definitions, function "
            "signatures, or symbol references is blocked or redirected to LSP tools, "
            "which are faster and semantically accurate.\n\n"
            "**Prefer LSP tools for**:\n"
            "- Finding where a class or function is defined → `goToDefinition`\n"
            "- Finding all usages of a symbol → `findReferences`\n"
            "- Getting type information or documentation → `hover`\n"
            "- Listing all symbols in a file → `documentSymbol`\n"
            "- Searching symbols across the project → `workspaceSymbol`\n\n"
            "**Grep/Bash grep is still appropriate for**: text patterns in content, "
            "log searching, finding strings in config files.\n\n"
            "Default mode (`block_once`): the first symbol-lookup grep in a session "
            "is denied with guidance; subsequent retries are allowed."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for LSP enforcement handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block Grep for class definition",
                command='Use Grep tool with pattern "class FrontController"',
                description=(
                    "When using Grep to search for a class definition like "
                    "'class FrontController', the handler should block and suggest "
                    "using LSP goToDefinition or workspaceSymbol instead."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"LSP",
                    r"goToDefinition|workspaceSymbol",
                ],
                safety_notes="Uses Grep tool - safe, read-only operation",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Allow Grep for regex pattern",
                command='Use Grep tool with pattern "log.*Error"',
                description=(
                    "When using Grep to search for a regex pattern like "
                    "'log.*Error', the handler should NOT trigger because "
                    "this is a legitimate text search that LSP cannot do."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses Grep tool - safe, read-only operation",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Block Bash rg for function definition",
                command='rg "def get_bash_command" src/',
                description=(
                    "When using Bash to run rg searching for a function definition, "
                    "the handler should block and suggest LSP tools instead."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"LSP",
                    r"goToDefinition|workspaceSymbol",
                ],
                safety_notes="Uses rg - safe, read-only operation",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Allow Bash grep scoped to one named file",
                command='grep -n "hook_input" src/claude_code_hooks_daemon/core/hook_result.py',
                description=(
                    "A grep already scoped to a single named file is a literal-"
                    "string check on a file the caller already knows about, not "
                    "a project-wide symbol lookup — must NOT be blocked. "
                    "Regression test for a dogfooding false positive (Plan 00200)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses grep - safe, read-only operation",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
