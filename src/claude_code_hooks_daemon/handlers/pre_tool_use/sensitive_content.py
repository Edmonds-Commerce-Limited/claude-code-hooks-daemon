"""SensitiveContentHandler - block Write/Edit content matching configured
sensitive patterns or a gitignored secret word list (Plan 00201).

Two independent sources:

- **Public patterns** (``options.public_patterns``): named regexes declared
  in ``.claude/hooks-daemon.yaml``, safe to name in the deny reason (paths,
  non-placeholder home dirs, session UUIDs, profanity, ...). The reason
  SHOULD say what matched — that is what makes it fixable.
- **Secret word list** (``options.secret_word_list_path``, default
  ``.claude/block-words.secret``): plain text, one gitignored term per line.
  A match here must NEVER reveal the term or its surrounding context — only
  a 1-based index into the (gitignored, hence meaningless-without-it) file.
  All loading/matching for this source is delegated to
  ``utils/secret_redaction.py``, the ONE place the raw terms are ever read.

Threat model: a deny ``reason`` is shown to the user, written to the session
transcript, and may be pasted into a bug report — so it is exactly as public
as this repo's own source code.
"""

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils import secret_redaction as sr
from claude_code_hooks_daemon.utils.path_exclusion import (
    is_path_excluded,
    merge_exclude_patterns,
    resolve_project_root,
)

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"

_PATTERN_KEY_NAME: Final[str] = "name"
_PATTERN_KEY_PATTERN: Final[str] = "pattern"
_PATTERN_KEY_DESCRIPTION: Final[str] = "description"

# Compiled-pattern cache: the same handful of client public_patterns are
# matched on every Write/Edit, so translating + compiling once is worth it.
# An invalid regex is cached as None so it is never re-attempted per event.
_COMPILED_PATTERN_CACHE: dict[str, "re.Pattern[str] | None"] = {}


def _compiled_public_pattern(pattern: str) -> "re.Pattern[str] | None":
    """Compile ``pattern`` (case-insensitive), caching by source string.

    A pattern that fails to compile is a documented no-match (never crashes
    the handler) — cached as ``None`` so a broken client config is not
    re-attempted on every event.
    """
    if pattern in _COMPILED_PATTERN_CACHE:
        return _COMPILED_PATTERN_CACHE[pattern]
    try:
        compiled: re.Pattern[str] | None = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = None
    _COMPILED_PATTERN_CACHE[pattern] = compiled
    return compiled


class SensitiveContentHandler(Handler):
    """Block Write/Edit content matching configured public patterns or a secret word list.

    Configuration options (``handlers.pre_tool_use.sensitive_content.options``):
        public_patterns: list of ``{name, pattern, description}`` dicts —
            safe-to-name regexes. Default empty (config is truth; no
            hardcoded patterns ship for client projects).
        secret_word_list_path: path to the gitignored secret word list,
            relative to the project root unless absolute. Default
            ``.claude/block-words.secret``. Missing file = feature inert.
        exclude_paths: glob patterns exempted from scanning, additive with
            the project-wide ``daemon.exclude_paths``.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SENSITIVE_CONTENT,
            priority=Priority.SENSITIVE_CONTENT,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
                HandlerTag.CONTENT_QUALITY,
            ],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        self._public_patterns: list[dict[str, str]] = []
        self._secret_word_list_path: str | None = None
        self._exclude_paths: list[str] | None = None

    def _get_content(self, hook_input: dict[str, Any]) -> str:
        """Content to check: full content for Write, only the ADDED text for Edit.

        Edit's ``old_string`` is deliberately never checked — removing
        sensitive text must never itself be blocked.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.EDIT:
            return str(tool_input.get(_FIELD_NEW_STRING, ""))
        return str(tool_input.get(_FIELD_CONTENT, ""))

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if file_path matches a client-configured exclude glob."""
        patterns = merge_exclude_patterns(
            getattr(self, "_project_exclude_paths", None),
            self._exclude_paths,
        )
        return bool(patterns) and is_path_excluded(
            file_path, patterns, project_root=resolve_project_root()
        )

    def _find_public_pattern_match(self, content: str) -> dict[str, str] | None:
        """First configured public pattern whose regex matches ``content``, else None.

        Returns the ORIGINAL pattern dict (with the actual matched substring
        attached under a synthetic ``_matched`` key) so the caller can build
        an exact, fixable deny reason.
        """
        for entry in self._public_patterns:
            pattern = entry.get(_PATTERN_KEY_PATTERN, "")
            if not pattern:
                continue
            compiled = _compiled_public_pattern(pattern)
            if compiled is None:
                continue
            match = compiled.search(content)
            if match:
                return {**entry, "_matched": match.group(0)}
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = str(tool_input.get(_FIELD_FILE_PATH, ""))
        if not file_path or self._is_excluded(file_path):
            return False

        content = self._get_content(hook_input)
        if not content:
            return False

        if self._find_public_pattern_match(content) is not None:
            return True

        terms = self._secret_terms()
        return sr.find_first_match_index(content, terms) is not None

    def _secret_terms(self) -> tuple[str, ...]:
        """Terms from this handler's configured secret word list.

        A handler-level ``secret_word_list_path`` override always wins over
        the daemon-wide resolution in ``secret_redaction.get_active_secret_terms``
        (which has no handler-option visibility) so unit tests and per-handler
        overrides never depend on ``ProjectContext``/daemon config being
        initialised.
        """
        if self._secret_word_list_path:
            path = Path(self._secret_word_list_path)
            if not path.is_absolute():
                project_root = resolve_project_root()
                if project_root is not None:
                    path = Path(project_root) / path
            return sr.get_cached_secret_terms(path)
        return sr.get_active_secret_terms()

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = str(tool_input.get(_FIELD_FILE_PATH, ""))
        content = self._get_content(hook_input)

        public_match = self._find_public_pattern_match(content)
        if public_match is not None:
            return self._deny_public_pattern(file_path, public_match)

        terms = self._secret_terms()
        index = sr.find_first_match_index(content, terms)
        if index is not None:
            return self._deny_secret_term(file_path, index, len(terms))

        return HookResult(decision=Decision.ALLOW)

    @staticmethod
    def _deny_public_pattern(file_path: str, match: dict[str, str]) -> HookResult:
        name = match.get(_PATTERN_KEY_NAME, "unnamed")
        description = match.get(_PATTERN_KEY_DESCRIPTION, "")
        matched_text = match.get("_matched", "")
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "SENSITIVE CONTENT BLOCKED: content matches a configured public pattern\n\n"
                f"File: {file_path}\n"
                f"Pattern: {name}" + (f" — {description}" if description else "") + "\n"
                f"Matched: {matched_text}\n\n"
                "Remove or replace the matched text before retrying."
            ),
        )

    @staticmethod
    def _deny_secret_term(file_path: str, index: int, total: int) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "SENSITIVE CONTENT BLOCKED: content matches a configured blocked term "
                f"(entry {index} of {total} in the secret word list).\n\n"
                f"File: {file_path}\n\n"
                "The term is deliberately not shown. Check "
                f"`{sr.DEFAULT_SECRET_WORD_LIST_PATH}` to see what is blocked, "
                "then remove it from the content."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## sensitive_content — blocked patterns and secret terms are never written\n\n"
            "Writing content that matches a configured public pattern or a gitignored "
            "secret word list is blocked. Two sources, two different disclosure rules:\n\n"
            "**Public patterns** (`handlers.pre_tool_use.sensitive_content.options."
            "public_patterns`): named regexes safe to name — the deny reason shows the "
            "pattern name and the exact matched text so you can fix it.\n\n"
            "**Secret word list** (`options.secret_word_list_path`, default "
            "`.claude/block-words.secret`, gitignored): a term never appears anywhere — "
            "not in the deny reason, not in any log, not in payload capture, not in a "
            "transcript archive. The deny reason names only an index "
            "(`entry N of M in the secret word list`), which is meaningless without the "
            "gitignored file. **Do NOT try to guess or work around the block** — open "
            "the secret word list file (if you have access) to see what matched, or ask "
            "the user. Only the ADDED text is checked on `Edit` (`new_string`) — removing "
            "sensitive content is never blocked.\n\n"
            "Missing/empty/comments-only secret file = this source is silently inert."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="sensitive_content - blocks a configured public pattern",
                command=(
                    "Use the Write tool to write content containing "
                    "`/var/www/vhosts/example` to a scratch file, with "
                    "public_patterns configured to match `/var/www/vhosts`"
                ),
                description=(
                    "Content matching a configured public pattern is denied with a "
                    "reason naming the pattern and the matched text."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"SENSITIVE CONTENT BLOCKED", r"Pattern:"],
                safety_notes="Deny path — no file is written",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a secret-list term without revealing it",
                command=(
                    "Use the Write tool to write content containing a term from "
                    "`.claude/block-words.secret` to a scratch file"
                ),
                description=(
                    "Content matching a secret-list term is denied with a reason "
                    "naming only an entry index — never the term itself."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"entry \d+ of \d+", r"deliberately not shown"],
                safety_notes=(
                    "Deny path — no file is written. Verify manually that the deny "
                    "reason does not contain the actual secret term."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - allows clean content",
                command="Use the Write tool to write plain, unremarkable content to a scratch file",
                description="Content matching neither source passes silently.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Allow path",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
