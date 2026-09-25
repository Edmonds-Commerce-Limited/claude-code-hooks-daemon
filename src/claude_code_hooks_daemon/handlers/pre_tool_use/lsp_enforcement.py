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

LSP counts as available only where an enabled Claude Code plugin declares a
language server for the searched file type (Plan 00468 P5): Claude Code keeps
the LSP tool inactive until a code intelligence plugin for the language is
installed. The file type comes from the Grep ``glob``/``type``/``path`` or a
grep/rg command's ``--include``/``-g``/``-t`` flags and file targets; when
none names one, any enabled server counts.

No-LSP modes (when no enabled plugin serves the searched file type):
    advisory (default): Allow, and advise installing a code intelligence plugin
    block: Block anyway, with the same advice
    disable: Handler doesn't match
"""

import logging
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

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
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.claude_plugins import resolve_enabled_plugins

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


# --- Which file types a search covers ---

_GREP_GLOB_KEY: Final[str] = "glob"
_GREP_TYPE_KEY: Final[str] = "type"
_GREP_PATH_KEY: Final[str] = "path"

#: ripgrep ``--type`` names (``rg --type-list``) for languages that code
#: intelligence plugins serve. An unlisted type names no file type.
_RG_TYPE_EXTENSIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "c": (".c", ".h"),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"),
    "cs": (".cs",),
    "go": (".go",),
    "java": (".java",),
    "js": (".js", ".jsx", ".mjs", ".cjs"),
    "kotlin": (".kt", ".kts"),
    "lua": (".lua",),
    "php": (".php",),
    "py": (".py", ".pyi"),
    "ruby": (".rb",),
    "rust": (".rs",),
    "swift": (".swift",),
    "ts": (".ts", ".tsx", ".mts", ".cts"),
}

# A glob or path ending in one suffix (``*.ts``, ``src/a.py``) or a brace set
# of them (``*.{ts,tsx}``).
_BRACE_SUFFIXES = re.compile(r"\.\{([^{}]+)\}$")
_ONE_SUFFIX = re.compile(r"\.([A-Za-z0-9_+-]+)$")

# grep/rg options whose value names the searched files, and whether it is a
# glob or an rg type name.
_GLOB_OPTIONS: Final[frozenset[str]] = frozenset({"--include", "--glob", "-g"})
_TYPE_OPTIONS: Final[frozenset[str]] = frozenset({"--type", "-t"})
_REDIRECT_PREFIXES: Final[tuple[str, ...]] = (">", "<", "1>", "2>", "&>")

_CODE_INTELLIGENCE_ADVICE = (
    "Install a code intelligence plugin for the language (`/plugin`, Discover tab; "
    "https://code.claude.com/docs/en/discover-plugins#code-intelligence) and its "
    "language server binary."
)


def _suffixes(glob_or_path: str) -> frozenset[str]:
    """The file suffixes a glob or path ends in, lower-cased; empty if none."""
    braces = _BRACE_SUFFIXES.search(glob_or_path)
    if braces:
        return frozenset(
            f".{part.strip().lower()}" for part in braces.group(1).split(",") if part.strip()
        )
    single = _ONE_SUFFIX.search(glob_or_path)
    return frozenset({f".{single.group(1).lower()}"}) if single else frozenset()


def _type_suffixes(type_name: str) -> frozenset[str]:
    return frozenset(_RG_TYPE_EXTENSIONS.get(type_name.strip().lower(), ()))


def _grep_tool_suffixes(tool_input: Mapping[str, Any]) -> frozenset[str]:
    found: set[str] = set()
    for key in (_GREP_GLOB_KEY, _GREP_PATH_KEY):
        value = tool_input.get(key)
        if isinstance(value, str):
            found |= _suffixes(value)
    type_name = tool_input.get(_GREP_TYPE_KEY)
    if isinstance(type_name, str):
        found |= _type_suffixes(type_name)
    return frozenset(found)


def _invocation_suffixes(invocation: str) -> frozenset[str]:
    """File suffixes one grep/rg invocation's options and file targets name."""
    try:
        tokens = shlex.split(invocation)
    except ValueError as exc:
        logger.debug("lsp_enforcement: unquoted split of %r: %s", invocation, exc)
        tokens = invocation.split()
    found: set[str] = set()
    pending: str | None = None
    for token in tokens[1:]:
        if pending is not None:
            found |= _type_suffixes(token) if pending in _TYPE_OPTIONS else _suffixes(token)
            pending = None
            continue
        option, has_value, value = token.partition("=")
        if option in _GLOB_OPTIONS | _TYPE_OPTIONS:
            if not has_value:
                pending = option
            elif option in _TYPE_OPTIONS:
                found |= _type_suffixes(value)
            else:
                found |= _suffixes(value)
        elif token.startswith(_REDIRECT_PREFIXES):
            break
        elif not token.startswith("-"):
            found |= _suffixes(token)
    return frozenset(found)


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

# Single rule: block_once/advisory/strict is a VERBOSITY/CADENCE knob on the
# same concept, "use LSP instead of grep for a symbol lookup" -- not a
# different violation per mode.
_LSP_RULE = Rule(
    rule_id=RuleID.LSP_SYMBOL_LOOKUP,
    blocked="a symbol-like Grep/Bash grep lookup",
    why="LSP tools give semantic ~50ms code intelligence; grep is slow and imprecise",
    fix="Use goToDefinition/findReferences/workspaceSymbol/hover/documentSymbol instead",
    verbose=(
        "Available LSP operations:\n"
        "  - goToDefinition: Find where a symbol is defined\n"
        "  - findReferences: Find all references to a symbol\n"
        "  - workspaceSymbol: Search for symbols across the workspace\n"
        "  - hover: Get type info and documentation for a symbol\n"
        "  - documentSymbol: Get all symbols in a file"
    ),
)


class LspEnforcementHandler(PreToolUseHandlerBase):
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
        self._formatter = RuleFormatter()
        # Claude Code's config and managed-settings dirs; None means the
        # resolver's defaults (test seams).
        self._config_dir: Path | None = None
        self._managed_dir: Path | None = None

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
        return getattr(self, "_no_lsp_mode", NoLspMode.ADVISORY)

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only where an enabled plugin declares a language server."""
        available = bool(self._served_suffixes(context.project_root))
        return Relevance.when(
            available,
            present="an enabled Claude Code plugin provides a language server",
            absent=(
                "no enabled Claude Code plugin provides a language server "
                "(install a code intelligence plugin)"
            ),
        )

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        if root is not None:
            return Path(root)
        try:
            return ProjectContext.project_root()
        except RuntimeError as exc:
            logger.debug("lsp_enforcement: no project context, using cwd: %s", exc)
            return Path.cwd()

    def _served_suffixes(self, project_root: Path) -> frozenset[str]:
        """Every file suffix an enabled plugin's language server declares."""
        inventory = resolve_enabled_plugins(
            project_root, config_dir=self._config_dir, managed_dir=self._managed_dir
        )
        return frozenset(
            suffix.lower() for server in inventory.lsp_servers() for suffix in server.extensions
        )

    @staticmethod
    def _searched_suffixes(hook_input: dict[str, Any]) -> frozenset[str]:
        """The file suffixes this search names; empty when it names none."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.GREP:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT)
            return _grep_tool_suffixes(tool_input) if isinstance(tool_input, dict) else frozenset()
        command = get_bash_command(hook_input) or ""
        found: set[str] = set()
        for match in _BASH_GREP_EXTRACT.finditer(command):
            invocation = command[match.start() :]
            terminator = _SEGMENT_TERMINATOR.search(invocation)
            found |= _invocation_suffixes(
                invocation[: terminator.start()] if terminator else invocation
            )
        return frozenset(found)

    def _lsp_coverage(self, hook_input: dict[str, Any]) -> tuple[bool, frozenset[str]]:
        """Whether an enabled server covers this search, and the suffixes it names.

        A search that names no file type is covered by any enabled server.
        """
        searched = self._searched_suffixes(hook_input)
        served = self._served_suffixes(self._project_root())
        covered = bool(searched & served) if searched else bool(served)
        return covered, searched

    def _get_block_count(self, session_id: str | None = None) -> int:
        """Get number of previous blocks by this handler in ``session_id``.

        A ``None`` session falls back to the daemon-wide count (an
        unattributed event cannot be scoped better than that).

        Returns 0 when the data layer is unavailable (RuntimeError raised by
        ProjectContext resolution). The failure is logged rather than silently
        swallowed so a persistently unavailable/corrupt history is observable.
        Unexpected exceptions propagate (FAIL FAST) instead of degrading the
        block_once gate to permanently-allow.
        """
        try:
            return get_data_layer().history.count_blocks_by_handler(
                self.name, session_id=session_id
            )
        except RuntimeError as exc:
            logger.warning("LSP enforcement could not read block history: %s", exc)
            return 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a symbol-like grep that LSP could handle better."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Only intercept Grep and Bash tools
        if tool_name not in (ToolName.GREP, ToolName.BASH):
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
        if not pattern or not self._is_symbol_like(pattern):
            return False

        # Last, because it reads the plugin inventory: with no_lsp_mode=disable,
        # stay out of a search no enabled language server covers.
        if self._get_no_lsp_mode() == NoLspMode.DISABLE:
            return self._lsp_coverage(hook_input)[0]
        return True

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

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_LSP_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Handle a symbol-like grep, steering toward LSP tools.

        block_once/advisory/strict is a cadence knob on ONE concept, so the
        rule ID is fixed regardless of mode -- unlike destructive_git's
        DisclosureTracker ladder, this handler already self-limits its own
        way (block_once's session-scoped block count), which this migration
        preserves unchanged; only the surrounding message now leads with
        the rule ID via RuleFormatter.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        pattern = self._extract_search_pattern(hook_input, tool_name) or ""
        lsp_available, searched = self._lsp_coverage(hook_input)
        mode = self._get_mode()
        no_lsp_mode = self._get_no_lsp_mode()

        # If LSP not available and no_lsp_mode=advisory, downgrade to advisory
        if not lsp_available and no_lsp_mode == NoLspMode.ADVISORY:
            mode = LspEnforcementMode.ADVISORY

        suggested_op = self._suggest_lsp_operation(pattern)
        dynamic_detail = self._build_dynamic_detail(pattern, suggested_op, lsp_available, searched)

        # Determine decision based on mode
        if mode == LspEnforcementMode.ADVISORY:
            return GatingResult(decision=Decision.ALLOW, context=[dynamic_detail])

        deny_reason = f"{self._formatter.verbose(_LSP_RULE)}\n\n{dynamic_detail}"

        if mode == LspEnforcementMode.STRICT:
            return GatingResult(decision=Decision.DENY, reason=deny_reason)

        # block_once: deny first time IN THIS SESSION, allow subsequent.
        # The daemon is shared across sessions (Plan 00127), so the count
        # must be session-scoped or one session's block consumes every
        # other session's one-time deny (Plan 00277 Task 2.1).
        block_count = self._get_block_count(hook_input.get(HookInputField.SESSION_ID))
        if block_count == 0:
            return GatingResult(decision=Decision.DENY, reason=deny_reason)
        return GatingResult(decision=Decision.ALLOW, context=[dynamic_detail])

    @staticmethod
    def _build_dynamic_detail(
        pattern: str, suggested_op: str, lsp_available: bool, searched: frozenset[str]
    ) -> str:
        """Build the per-invocation guidance (pattern, suggestion, availability)."""
        if lsp_available:
            return (
                f"LSP tool available for this lookup: pattern '{pattern}' looks like a "
                f"symbol search.\n\nSuggested LSP operation: {suggested_op}"
            )
        files = f"{', '.join(sorted(searched))} files" if searched else "this project"
        return (
            f"Pattern '{pattern}' looks like a symbol search, but no enabled Claude Code "
            f"plugin provides a language server for {files}, so the LSP tool cannot "
            f"answer it.\n\n{_CODE_INTELLIGENCE_ADVICE}"
        )

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
            "is denied with guidance; subsequent retries are allowed.\n\n"
            "It enforces only where an enabled Claude Code plugin provides a language "
            "server for the searched file type (from the glob, type or path). "
            "Elsewhere the default `no_lsp_mode: advisory` only suggests installing "
            "a code intelligence plugin."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for LSP enforcement handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        # Stated once; the prose is rendered from it (Plan 00243).
        class_lookup_probe = ToolPayload(
            tool_name=ToolName.GREP,
            tool_input={"pattern": "class FrontController"},
        )
        regex_search_probe = ToolPayload(
            tool_name=ToolName.GREP,
            tool_input={"pattern": "log.*Error"},
        )

        return [
            AcceptanceTest(
                title="Block Grep for class definition",
                command=class_lookup_probe.as_instruction(),
                tool_payload=class_lookup_probe,
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
                safety_notes=(
                    "Uses Grep tool - safe, read-only operation. A project denying "
                    'Grep at source (`permissions.deny: ["Grep"]` in '
                    "`.claude/settings.json` -- the same generic mechanism "
                    "artifact_publish_blocker documents for Artifact/enableArtifact) "
                    "removes the tool entirely; a runner without it available "
                    "records a valid SKIP rather than attempting this test."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Allow Grep for regex pattern",
                command=regex_search_probe.as_instruction(),
                tool_payload=regex_search_probe,
                description=(
                    "When using Grep to search for a regex pattern like "
                    "'log.*Error', the handler should NOT trigger because "
                    "this is a legitimate text search that LSP cannot do."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Uses Grep tool - safe, read-only operation. A project denying "
                    'Grep at source (`permissions.deny: ["Grep"]` in '
                    "`.claude/settings.json` -- the same generic mechanism "
                    "artifact_publish_blocker documents for Artifact/enableArtifact) "
                    "removes the tool entirely; a runner without it available "
                    "records a valid SKIP rather than attempting this test."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Block Bash rg for function definition",
                command='rg "def get_bash_command" src/',
                dispatch_as_bash=True,
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
                dispatch_as_bash=True,
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
