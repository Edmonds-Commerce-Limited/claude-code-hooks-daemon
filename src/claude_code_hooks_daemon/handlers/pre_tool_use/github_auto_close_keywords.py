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
race" is prose — so only keyword+reference forms are matched, and the
keyword and reference must sit on the SAME line, as GitHub requires.

Coverage is scoped to the MESSAGE-BEARING SEGMENT of the command, not the
whole command string: the command is split on ``&&``/``||``/``;`` and only
the text from a ``git commit|merge|tag`` or ``gh pr create|edit`` token
onward within its segment is scanned. Reading is therefore never blocked —
``grep 'fixes #12' notes.txt && git commit -m 'clean'`` carries the
reference only in a non-message segment and is allowed (the same boundary
``sensitive_content`` draws for its metadata checks).

Message routes covered per segment:

- Inline: ``-m``/``--message`` values (any quoting), ``gh pr`` ``--body``/
  ``-b`` values, and heredoc/``$(cat ...)`` bodies visible in the segment.
- Scratch file: ``git commit -F <file>`` / ``--file=<file>`` and
  ``gh pr ... --body-file <file>`` have the referenced file READ at
  PreToolUse time, decoded with ``errors="replace"`` so a binary file can
  never raise out of ``matches()`` (which would abort the whole PreToolUse
  chain and discard earlier non-terminal denies). A missing or unreadable
  file, or one beyond the byte cap, is skipped — the commit will fail on
  its own, and git owns that failure. No exception path remains: existence
  and readability are probed up-front, and decoding cannot fail.

``-t``/``--template`` is NOT a message source and is ignored.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION

_LOGGER = logging.getLogger(__name__)

# Mode values (mirrors git_stash / ancestry_preserving_merge, Plan 00207).
_MODE_BLOCK: Final[str] = "block"
_MODE_WARN: Final[str] = "warn"

# Hook input field carrying the tool call's working directory, used to
# resolve a relative -F path the way git itself would.
_CWD_FIELD: Final[str] = "cwd"

# Commit messages and PR bodies are small; a message file larger than this
# is skipped rather than read (protects matches() from pathological files).
_MAX_MESSAGE_FILE_BYTES: Final[int] = 65_536

# A message file that is not valid UTF-8 (a binary blob passed to -F by
# mistake) is decoded with replacement so scanning can never raise.
_MESSAGE_FILE_ENCODING: Final[str] = "utf-8"
_MESSAGE_FILE_DECODE_ERRORS: Final[str] = "replace"

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
# same-line spacing + reference. [ \t]* deliberately excludes newlines:
# GitHub does not close across a line break ("Partially fixed\n#456"), so
# neither do we. IGNORECASE covers FIXES/Fixes/gh-/GH-.
_AUTO_CLOSE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(_CLOSING_KEYWORDS) + r")\b:?[ \t]*" + _ISSUE_REFERENCE,
    re.IGNORECASE,
)

# Only these git subcommands record a message that can reach the default
# branch: commit directly, merge via its merge commit, tag via annotation.
_MESSAGE_BEARING_SUBCOMMANDS: Final[tuple[str, ...]] = ("commit", "merge", "tag")

_GIT_SUBCOMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(
    GIT_INVOCATION + r"(?:" + "|".join(_MESSAGE_BEARING_SUBCOMMANDS) + r")\b"
)

# gh pr create/edit carry a PR body — the page's PRIMARY auto-close vector.
# Other gh pr subcommands (view, merge, checkout) take no body and are
# never scanned.
_GH_PR_BODY_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bgh\s+pr\s+(?:create|edit)\b")

# Command separators that bound a message-bearing segment. Newlines are NOT
# separators here, because a heredoc body legitimately follows the command
# across newlines and must stay inside its segment.
_SEGMENT_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"&&|\|\||;")

# git commit -F <file> / --file=<file>, and gh pr --body-file <file>. The
# value may be bare, single- or double-quoted; "-" (stdin) is skipped — its
# heredoc body is in the segment text, which is scanned anyway.
_MESSAGE_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:-F|--file|--body-file)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)
_STDIN_MESSAGE_FILE: Final[str] = "-"

_REWRITE_EXAMPLES: Final[str] = (
    '"Addresses #123", "Refs #123" or "See #123" — GitHub links these but ' "does not close"
)

_WARN_GUIDANCE_HEADER: Final[str] = (
    "⚠️ GitHub auto-closing keyword reference detected in a git message"
)


class GithubAutoCloseKeywordsHandler(PreToolUseHandlerBase):
    """Deny git messages carrying GitHub auto-closing keyword references.

    Modes (normalised with strip/lower; an UNKNOWN mode value fails CLOSED,
    i.e. denies — deliberately stricter than git_stash, because this
    handler's whole purpose is stopping a silent outward-facing side
    effect):
        - "block" (default): deny
        - "warn": allow with advisory context

    There is deliberately NO escape hatch: the only legitimate reason to
    auto-close is a project whose workflow wants closing keywords, and that
    project should disable the handler instead — a per-command hatch would
    just normalise bypassing it.
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
        # Per-dispatch cache: matches() and handle() see the same hook_input,
        # so the -F/--body-file content is stat'd and read ONCE (avoids a
        # read-twice TOCTOU between the two calls).
        self._cached_command: str | None = None
        self._cached_span: str | None = None

    def _message_segments(self, command: str) -> list[str]:
        """The message-bearing slices of ``command``.

        The command is split on ``&&``/``||``/``;``; within each piece, only
        the text from a ``git commit|merge|tag`` or ``gh pr create|edit``
        token to the end of that piece is a candidate. Everything else —
        greps, tag listings, unrelated commands — is never scanned, so
        reading is never blocked.
        """
        segments: list[str] = []
        for piece in _SEGMENT_SEPARATOR_PATTERN.split(command):
            token = _GIT_SUBCOMMAND_PATTERN.search(piece) or _GH_PR_BODY_PATTERN.search(piece)
            if token:
                segments.append(piece[token.start() :])
        return segments

    def _message_file_texts(self, segment: str, hook_input: dict[str, Any]) -> list[str]:
        """Content of every readable message file named in ``segment``."""
        texts: list[str] = []
        for match in _MESSAGE_FILE_PATTERN.finditer(segment):
            raw = next(group for group in match.groups() if group)
            if raw == _STDIN_MESSAGE_FILE:
                continue
            path = Path(raw)
            if not path.is_absolute():
                cwd = hook_input.get(_CWD_FIELD)
                if isinstance(cwd, str) and cwd:
                    path = Path(cwd) / path
            if not path.is_file() or not os.access(path, os.R_OK):
                # Missing/unreadable file: the commit itself will fail, and
                # that failure belongs to git, not to this guard. Checked
                # up-front rather than caught, so no exception is swallowed.
                _LOGGER.debug("Skipping unreadable message file %s", path)
                continue
            if path.stat().st_size > _MAX_MESSAGE_FILE_BYTES:
                _LOGGER.debug("Skipping oversized message file %s", path)
                continue
            texts.append(
                path.read_bytes().decode(_MESSAGE_FILE_ENCODING, errors=_MESSAGE_FILE_DECODE_ERRORS)
            )
        return texts

    def _compute_match(self, hook_input: dict[str, Any]) -> str | None:
        """First matched keyword+reference span across all message routes."""
        command = get_bash_command(hook_input)
        if not command:
            return None
        for segment in self._message_segments(command):
            direct = _AUTO_CLOSE_PATTERN.search(segment)
            if direct:
                return direct.group(0)
            for text in self._message_file_texts(segment, hook_input):
                file_match = _AUTO_CLOSE_PATTERN.search(text)
                if file_match:
                    return file_match.group(0)
        return None

    def _find_match(self, hook_input: dict[str, Any]) -> str | None:
        """Cached wrapper around :meth:`_compute_match` (one read per dispatch)."""
        command = get_bash_command(hook_input)
        if command is not None and command == self._cached_command:
            return self._cached_span
        span = self._compute_match(hook_input)
        self._cached_command = command
        self._cached_span = span
        return span

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a git/gh message segment carries an auto-closing
        keyword reference and no escape hatch is declared."""
        return self._find_match(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny (or, in warn mode, advise), quoting the matched span."""
        matched = self._find_match(hook_input)
        if matched is None:
            return GatingResult(decision=Decision.ALLOW)

        mode = self._mode.strip().lower()
        if mode == _MODE_WARN:
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
                "  • When this commit reaches the default branch (or the PR "
                "merges), GitHub AUTO-CLOSES the referenced issue/PR\n"
                "  • This cannot be disabled repository-side, and closures "
                "triggered this way are easy to miss\n\n"
                "USE A NON-CLOSING REFERENCE INSTEAD:\n"
                f"  {_REWRITE_EXAMPLES}\n"
                "  e.g. git commit -m 'Addresses #123: harden the retry path'\n\n"
                "THERE IS NO ESCAPE HATCH. If this project genuinely wants "
                "auto-close commits to work (closing keywords are part of its "
                "workflow), this handler should be disabled — suggest that to "
                "the user; do not try to work around the block.\n"
                "To disable: handlers.pre_tool_use.github_auto_close_keywords"
            ),
        )

    def get_claude_md(self) -> str:
        """Resident guidance for the project's CLAUDE.md."""
        return (
            "## github_auto_close_keywords — closing keywords in git messages "
            "are blocked\n\n"
            "A `git commit` (or `git merge -m` / `git tag -m`, or a "
            "`gh pr create`/`gh pr edit` body) whose message contains a "
            "GitHub closing keyword followed by an issue reference is DENIED. "
            "`Fixes #123`, `closes octo-org/octo-repo#42`, `Resolved GH-7`, "
            "or a keyword before a full issue URL all auto-close that issue "
            "the moment the commit reaches the default branch (or the PR "
            "merges) — GitHub offers no repo-side switch to turn this off. "
            "The nine keywords are close/closes/closed, fix/fixes/fixed, "
            "resolve/resolves/resolved, case-insensitive, with or without a "
            "colon; keyword and reference must share a line.\n\n"
            "**The keyword alone is fine.** `fixes the race condition` is "
            "prose and never matches; only keyword+reference forms trigger. "
            "A bare `#123` without a keyword is also fine, and READING is "
            "never blocked — a reference inside a `grep`/`git log` in the "
            "same compound command does not deny the commit segment.\n\n"
            "**All message routes are checked**: inline `-m` values (any "
            "quoting, any of several `-m` paragraphs), `gh pr` `--body`/`-b` "
            "values, AND the content of a `-F <file>` / `--file=<file>` / "
            "`--body-file <file>` scratch file, which is read at check time. "
            "A missing, unreadable, binary or oversized file is allowed "
            "through — the command fails on its own. `-t`/`--template` is "
            "not a message source.\n\n"
            "**Use a non-closing reference instead**: `Addresses #123`, "
            "`Refs #123`, `See #123` — GitHub links these but does not "
            "close.\n\n"
            "**There is deliberately NO escape hatch.** If this project "
            "genuinely wants auto-close commits to work — closing keywords "
            "are a deliberate part of its workflow — the handler should be "
            "DISABLED: suggest to the user that they set "
            "`handlers.pre_tool_use.github_auto_close_keywords.enabled: "
            "false`. Do not hunt for a bypass; rewrite the message or ask.\n\n"
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

        if self._mode.strip().lower() == _MODE_WARN:
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
                title="gh pr body with closing reference blocked",
                command="gh pr create --title 'x' --body 'Fixes #123'",
                description="A PR body is the primary auto-close vector",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"Fixes #123"],
                safety_notes="Denied before bash runs, so no PR is created.",
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
