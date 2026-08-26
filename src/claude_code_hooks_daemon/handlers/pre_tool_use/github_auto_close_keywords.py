"""GithubAutoCloseKeywordsHandler - GitHub auto-closing keyword references.

A commit message containing a closing keyword followed by an issue reference
("Fixes #123", "closes octo-org/octo-repo#42", "Resolved GH-7", or a full
issue URL) AUTO-CLOSES that issue the moment the commit reaches the default
branch. GitHub offers no repository-side switch to disable this, and agents
write the forms accidentally — "Fixes #123" reads as natural changelog prose.
The only reliable guard is at the source: deny the commit before the message
is recorded.

Grammar verified against docs.github.com "Linking a pull request to an
issue" (fetched 2026-08-26): the nine keywords are close/closes/closed/
fix/fixes/fixed/resolve/resolves/resolved, case-insensitive, optionally
followed by a colon. The keyword ALONE never closes anything — "fixes the
race" is prose — so only keyword+reference forms are matched.

Two message routes are covered:

- Inline: the full Bash command string is scanned (the destructive_git
  precedent), which also catches heredoc and ``$(cat ...)`` shapes whose
  text is visible in the command.
- Scratch file: ``git commit -F <file>`` / ``--file=<file>`` has the
  referenced file READ at PreToolUse time. A missing or unreadable file is
  allowed — the commit will fail on its own, and git owns that failure.

``-t``/``--template`` is NOT a message source and is ignored.
"""

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION

# Mode values (mirrors git_stash / ancestry_preserving_merge, Plan 00207).
_MODE_BLOCK: Final[str] = "block"
_MODE_WARN: Final[str] = "warn"

# Hook input field carrying the tool call's working directory, used to
# resolve a relative -F path the way git itself would.
_CWD_FIELD: Final[str] = "cwd"

# The nine closing keywords GitHub documents. Case-insensitivity and the
# optional trailing colon ("Closes: #10") are applied in the pattern.
_CLOSING_KEYWORDS: Final[tuple[str, ...]] = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

# An issue reference in any documented form: #N, owner/repo#N, GH-N, or a
# full issue/PR URL. The owner/repo prefix is optional before #N.
_ISSUE_REFERENCE: Final[str] = (
    r"(?:"
    r"(?:[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+)?#\d+"
    r"|GH-\d+"
    r"|https://github\.com/[^\s/]+/[^\s/]+/(?:issues|pull)/\d+"
    r")"
)

# keyword (word-bounded, so "prefixes" never matches) + optional colon +
# whitespace + reference. IGNORECASE covers FIXES/Fixes/gh-/GH-.
_AUTO_CLOSE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(_CLOSING_KEYWORDS) + r")\b:?\s*" + _ISSUE_REFERENCE,
    re.IGNORECASE,
)

# Only these git subcommands record a message that can reach the default
# branch: commit directly, merge via its merge commit, tag via annotation.
_MESSAGE_BEARING_SUBCOMMANDS: Final[tuple[str, ...]] = ("commit", "merge", "tag")

_GIT_SUBCOMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    GIT_INVOCATION + r"(?:" + "|".join(_MESSAGE_BEARING_SUBCOMMANDS) + r")\b"
)

# git commit -F <file> / --file=<file> / --file <file>. The value may be
# bare, single- or double-quoted; "-" (stdin) is skipped — its body is in
# the command string, which is scanned anyway.
_MESSAGE_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:-F|--file)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

# Escape hatch, matching the daemon's MUST_..._BECAUSE convention: the
# reason must be non-empty.
_ESCAPE_HATCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""MUST_AUTO_CLOSE_BECAUSE=["']([^"']+)["']""",
    re.IGNORECASE,
)

_REWRITE_EXAMPLES: Final[str] = (
    '"Addresses #123", "Refs #123" or "See #123" — GitHub links these but '
    "does not close"
)

_WARN_GUIDANCE_HEADER: Final[str] = (
    "⚠️ GitHub auto-closing keyword reference detected in a git message"
)


class GithubAutoCloseKeywordsHandler(PreToolUseHandlerBase):
    """Deny git messages carrying GitHub auto-closing keyword references.

    Modes:
        - "block" (default): deny unless the escape hatch is declared
        - "warn": allow with advisory context

    Escape hatch:
        MUST_AUTO_CLOSE_BECAUSE="reason"; git commit -m 'Fixes #123'
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GITHUB_AUTO_CLOSE_KEYWORDS,
            priority=Priority.GITHUB_AUTO_CLOSE_KEYWORDS,
            # NOT terminal: `mode: warn` returns ALLOW, and a terminal ALLOW
            # would end dispatch here and silently disable every
            # higher-numbered handler for that command (the Plan 00144
            # regression class). A non-terminal deny still denies.
            terminal=False,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.GIT,
                HandlerTag.GITHUB,
                HandlerTag.BLOCKING,
            ],
        )
        self._mode = _MODE_BLOCK

    def _message_file_texts(self, command: str, hook_input: dict[str, Any]) -> list[str]:
        """Content of every readable -F/--file message file in the command."""
        texts: list[str] = []
        for match in _MESSAGE_FILE_PATTERN.finditer(command):
            raw = next(group for group in match.groups() if group)
            if raw == "-":
                continue
            path = Path(raw)
            if not path.is_absolute():
                cwd = hook_input.get(_CWD_FIELD)
                if isinstance(cwd, str) and cwd:
                    path = Path(cwd) / path
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except OSError:
                # Missing/unreadable file: the commit itself will fail, and
                # that failure belongs to git, not to this guard.
                continue
        return texts

    def _find_match(self, hook_input: dict[str, Any]) -> str | None:
        """Return the first matched keyword+reference span, or None."""
        command = get_bash_command(hook_input)
        if not command:
            return None
        if not _GIT_SUBCOMMAND_PATTERN.search(command):
            return None
        if _ESCAPE_HATCH_PATTERN.search(command):
            return None
        direct = _AUTO_CLOSE_PATTERN.search(command)
        if direct:
            return direct.group(0)
        for text in self._message_file_texts(command, hook_input):
            file_match = _AUTO_CLOSE_PATTERN.search(text)
            if file_match:
                return file_match.group(0)
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a git commit/merge/tag message carries an auto-closing
        keyword reference and no escape hatch is declared."""
        return self._find_match(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny (or, in warn mode, advise), quoting the matched span."""
        matched = self._find_match(hook_input)
        if matched is None:
            return GatingResult(decision=Decision.ALLOW)

        if self._mode == _MODE_WARN:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    _WARN_GUIDANCE_HEADER,
                    f'"{matched}" will auto-close that issue/PR when the commit '
                    "reaches the default branch",
                    f"Prefer a non-closing reference: {_REWRITE_EXAMPLES}",
                ],
            )

        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: GitHub auto-closing keyword reference in a git "
                "message\n\n"
                f'MATCHED: "{matched}"\n\n'
                "WHAT WOULD HAPPEN:\n"
                "  • When this commit reaches the default branch, GitHub "
                "AUTO-CLOSES the referenced issue/PR\n"
                "  • This cannot be disabled repository-side, and closures "
                "triggered this way are easy to miss\n\n"
                "USE A NON-CLOSING REFERENCE INSTEAD:\n"
                f"  {_REWRITE_EXAMPLES}\n"
                '  e.g. git commit -m \'Addresses #123: harden the retry path\'\n\n'
                "ESCAPE HATCH (when auto-closing is genuinely intended):\n"
                '  MUST_AUTO_CLOSE_BECAUSE="explain why"; git commit ...\n\n'
                "To disable: handlers.pre_tool_use.github_auto_close_keywords"
            ),
        )

    def get_claude_md(self) -> str:
        """Resident guidance for the project's CLAUDE.md."""
        return (
            "## github_auto_close_keywords — closing keywords in git messages "
            "are blocked\n\n"
            "A `git commit` (or `git merge -m` / `git tag -m`) whose message "
            "contains a GitHub closing keyword followed by an issue reference "
            "is DENIED. `Fixes #123`, `closes octo-org/octo-repo#42`, "
            "`Resolved GH-7`, or a keyword before a full issue URL all "
            "auto-close that issue the moment the commit reaches the default "
            "branch — GitHub offers no repo-side switch to turn this off. "
            "The nine keywords are close/closes/closed, fix/fixes/fixed, "
            "resolve/resolves/resolved, case-insensitive, with or without a "
            "colon.\n\n"
            "**The keyword alone is fine.** `fixes the race condition` is "
            "prose and never matches; only keyword+reference forms trigger. "
            "A bare `#123` without a keyword is also fine.\n\n"
            "**Both message routes are checked**: an inline `-m` value (any "
            "quoting, any of several `-m` paragraphs) AND the content of a "
            "`-F <file>` / `--file=<file>` scratch file, which is read at "
            "check time. A missing `-F` file is allowed — the commit fails "
            "on its own. `-t`/`--template` is not a message source.\n\n"
            "**Use a non-closing reference instead**: `Addresses #123`, "
            "`Refs #123`, `See #123` — GitHub links these but does not "
            "close.\n\n"
            "**Escape hatch** (when auto-closing is genuinely intended):\n\n"
            "```\n"
            "MUST_AUTO_CLOSE_BECAUSE=\"explain why\"; git commit -m 'Fixes #123'\n"
            "```\n\n"
            "Configure via "
            "`handlers.pre_tool_use.github_auto_close_keywords.options.mode: "
            "warn` for advisory-only mode."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook.

        The DENY cases are safe unwrapped: the handler denies before bash
        runs anything, and the commands would in any case only fail (no
        staged changes named). ALLOW cases use echo.
        """
        from claude_code_hooks_daemon.core.acceptance_test import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        if self._mode == _MODE_WARN:
            return [
                AcceptanceTest(
                    title="auto-close keyword reference (warn mode)",
                    command="git commit -m 'Fixes #123'",
                    description="Warn mode allows with advisory context",
                    expected_decision=Decision.ALLOW,
                    expected_message_patterns=[r"auto-clos"],
                    safety_notes="Allowed with advisory; no auto-close occurs "
                    "unless the commit is completed and pushed.",
                    test_type=TestType.ADVISORY,
                    recommended_model=RecommendedModel.SONNET,
                    requires_main_thread=False,
                ),
            ]

        return [
            AcceptanceTest(
                title="closing keyword with issue reference blocked",
                command="git commit -m 'Fixes #123'",
                description="Keyword+reference auto-closes on the default branch",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"Fixes #123", r"Addresses"],
                safety_notes="Denied before bash runs, so nothing is committed.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="keyword without a reference allowed",
                command="echo \"git commit -m 'fixes the race condition'\"",
                description="The keyword alone is prose and must not match",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="non-closing reference allowed",
                command="echo \"git commit -m 'Addresses #123'\"",
                description="GitHub links but does not close this phrasing",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
