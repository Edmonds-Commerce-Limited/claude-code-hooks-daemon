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
from claude_code_hooks_daemon.utils.command_evasion import git_subcommand_index
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    resolve_project_root,
)

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_COMMAND: Final[str] = "command"

# Neutral label for the offending thing named in a deny reason: a file path for
# Write/Edit, a command line for Bash. It was "File:" while only file writes
# were guarded, which now reads as a lie half the time.
_SUBJECT_LABEL: Final[str] = "Offending input"

# Git METADATA write surfaces. Contents and paths are only two of the seven
# places a term can enter a repository; the other five are metadata, and every
# one of them arrives as a Bash `git` invocation:
#
#   commit   -> commit messages          (filter-repo: --replace-message)
#   config   -> author/committer identity(filter-repo: --mailmap)
#   tag      -> tag names AND messages   (filter-repo: manual re-tag)
#   branch   -> branch names             (filter-repo: manual rename)
#   checkout -> `-b` creates a branch
#   switch   -> `-c` creates a branch
#   merge    -> `-m` writes a merge commit message
#
# Gated on a `git` invocation, never on the bare subcommand word: "commit",
# "tag" and "branch" are ordinary English, so matching them alone would deny
# any sentence mentioning a branch.
_GIT_EXECUTABLE: Final[str] = "git"
_GIT_METADATA_WRITE_SUBCOMMANDS: Final[tuple[str, ...]] = (
    "commit",
    "config",
    "tag",
    "branch",
    "checkout",
    "switch",
    "merge",
)

# Read-only git operations that TAKE a ref/pattern as an operand, so a term on
# the command line means the caller is INSPECTING one, not creating one. These
# must stay allowed: searching for a term and removing it are exactly the work
# of cleaning a repository, and a guard that blocks its own remedy gets
# switched off.
_GIT_READ_ONLY_FLAGS: Final[tuple[str, ...]] = ("--grep", "--list", "-l", "--get")

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
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
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
        haystacks = self._haystacks_for(hook_input)
        if not haystacks:
            return False

        if any(self._find_public_pattern_match(text) is not None for text in haystacks):
            return True

        terms = self._secret_terms()
        return any(sr.find_first_match_index(text, terms) is not None for text in haystacks)

    def _haystacks_for(self, hook_input: dict[str, Any]) -> list[str]:
        """Every piece of text this tool call would introduce, or ``[]``.

        The one place tool dispatch happens, so ``matches()`` and ``handle()``
        can never disagree about what was inspected — a divergence there would
        deny with a reason derived from text the match was not based on.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH:
            return self._git_metadata_haystacks(hook_input)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return []

        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = str(tool_input.get(_FIELD_FILE_PATH, ""))
        if not file_path or self._is_excluded(file_path):
            return []
        if self._is_secret_list_itself(file_path):
            return []
        return self._haystacks(hook_input, file_path)

    def _git_metadata_haystacks(self, hook_input: dict[str, Any]) -> list[str]:
        """The command, but ONLY when it writes git metadata.

        Five of the seven surfaces that can carry a term into a repository are
        git metadata, and none of them is a file write, so nothing else in this
        handler can see them: one ``git commit -m "<term>"`` re-contaminates a
        history that was just rewritten clean, and both this handler and the
        whole-tree QA scanner report all-clear afterwards.

        Deliberately NOT every Bash command. A term legitimately appears on the
        command line when searching for it, reading a file containing it, or
        running the tooling that REMOVES it. Denying those blocks the remedy,
        and a guard that obstructs its own cleanup gets switched off — which
        costs more than the leak it prevents.
        """
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        command = str(tool_input.get(_FIELD_COMMAND, ""))
        if not command or not self._writes_git_metadata(command):
            return []
        return [command]

    @staticmethod
    def _writes_git_metadata(command: str) -> bool:
        """True when ``command`` invokes git in a way that records metadata.

        Token-based, not substring: ``git`` must appear as its own token
        followed by a metadata subcommand, so neither a sentence about a branch
        nor a path like ``untracked/git-notes`` qualifies.

        The subcommand is located via ``git_subcommand_index`` rather than by
        reading the very next token, because git accepts GLOBAL OPTIONS first.
        Reading ``tokens[position + 1]`` blindly meant ``git -C /path commit``
        offered up ``-C`` as the subcommand, matched nothing, and let a blocked
        term through into a commit message — the one leak surface that cannot
        be undone without rewriting published history.
        """
        tokens = command.split()
        for position, token in enumerate(tokens[:-1]):
            if token != _GIT_EXECUTABLE and not token.endswith(f"/{_GIT_EXECUTABLE}"):
                continue
            subcommand_index = git_subcommand_index(tokens, position)
            if subcommand_index is None:
                continue
            subcommand = tokens[subcommand_index]
            if subcommand not in _GIT_METADATA_WRITE_SUBCOMMANDS:
                continue
            # `git tag -l <pattern>` / `git branch --list <pattern>` /
            # `git config --get <key>` take a ref pattern as an operand and
            # create nothing — inspecting what needs cleaning, not adding to it.
            if any(flag in tokens for flag in _GIT_READ_ONLY_FLAGS):
                continue
            return True
        return False

    def _haystacks(self, hook_input: dict[str, Any], file_path: str) -> list[str]:
        """Every piece of text this write would introduce: its PATH and its body.

        The path matters independently of the body. This repository's own
        history rewrite needed ``--path-rename`` for three files whose NAMES
        carried an identifier — ``--replace-text`` never touches a filename,
        and neither did this handler, so a file could be created with an
        identifier in its name and sail through on a clean body.
        """
        return [
            text
            for text in (self._relative_path_text(file_path), self._get_content(hook_input))
            if text
        ]

    @staticmethod
    def _relative_path_text(file_path: str) -> str:
        """``file_path`` relative to the project root, or ``""``.

        Deliberately NOT the absolute path. A project whose own root sits
        under a listed directory (a home directory on the secret list, say)
        would otherwise have EVERY write denied — a false positive so total
        it would force the handler to be switched off. Only the portion of
        the path the author actually chose is checked.
        """
        project_root = resolve_project_root()
        if project_root is None:
            return ""
        try:
            return str(Path(file_path).resolve().relative_to(Path(project_root).resolve()))
        except ValueError:
            # Outside the project root: not ours to judge.
            return ""

    def _secret_terms(self) -> tuple[str, ...]:
        """Terms from this handler's configured secret word list.

        A handler-level ``secret_word_list_path`` override always wins over
        the daemon-wide resolution in ``secret_redaction.get_active_secret_terms``
        (which has no handler-option visibility) so unit tests and per-handler
        overrides never depend on ``ProjectContext``/daemon config being
        initialised.
        """
        path = self._resolved_secret_list_path()
        if path is not None:
            return sr.get_cached_secret_terms(path)
        return sr.get_active_secret_terms()

    def _resolved_secret_list_path(self) -> Path | None:
        """Absolute path of this handler's configured secret word list, if any.

        The config value is repo-relative but every tool call carries an
        absolute ``file_path``, so both sides must be resolved before they can
        be compared (see ``_is_secret_list_itself``).
        """
        if not self._secret_word_list_path:
            return None
        path = Path(self._secret_word_list_path)
        if not path.is_absolute():
            project_root = resolve_project_root()
            if project_root is not None:
                path = Path(project_root) / path
        return path

    def _is_secret_list_itself(self, file_path: str) -> bool:
        """True when the write targets the word list that defines the terms.

        The list is the one file that MUST be allowed to contain its own
        terms. Without this the handler bricks its own configuration: the
        first write lands (nothing is configured yet, so nothing matches),
        and every later edit to add, remove or correct an entry is denied by
        the very terms the file exists to declare -- reported only as an
        opaque index, with no way to act on it. Found by dogfooding.

        Deliberately scoped to the resolved list path alone. The tracked
        ``.example`` seed is NOT exempt: it ships in the repo, so a real term
        pasted into it would be published -- exactly what this handler is for.
        """
        configured = self._resolved_secret_list_path()
        if configured is None:
            return False
        try:
            return Path(file_path).resolve() == configured.resolve()
        except (OSError, ValueError):
            # An unresolvable path is simply not the list; fall through to
            # normal scanning rather than failing open on the whole check.
            return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        haystacks = self._haystacks_for(hook_input)
        subject = self._subject(hook_input)

        for text in haystacks:
            public_match = self._find_public_pattern_match(text)
            if public_match is not None:
                return self._deny_public_pattern(subject, public_match)

        terms = self._secret_terms()
        for text in haystacks:
            index = sr.find_first_match_index(text, terms)
            if index is not None:
                # The subject is echoed back in the deny reason, and the
                # subject is now itself a thing that can MATCH — a file path,
                # or a whole git command line. Printing it raw would put the
                # term straight into the message the no-echo contract exists to
                # keep it out of: moving the leak, not closing it.
                return self._deny_secret_term(sr.redact_text(subject, terms), index, len(terms))

        return HookResult(decision=Decision.ALLOW)

    @staticmethod
    def _subject(hook_input: dict[str, Any]) -> str:
        """What the deny reason names as the offending thing.

        A file path for ``Write``/``Edit``; the command line for ``Bash``,
        where there is no file — the git metadata never lands in one.
        """
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.BASH:
            return str(tool_input.get(_FIELD_COMMAND, ""))
        return str(tool_input.get(_FIELD_FILE_PATH, ""))

    @staticmethod
    def _deny_public_pattern(subject: str, match: dict[str, str]) -> HookResult:
        name = match.get(_PATTERN_KEY_NAME, "unnamed")
        description = match.get(_PATTERN_KEY_DESCRIPTION, "")
        matched_text = match.get("_matched", "")
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "SENSITIVE CONTENT BLOCKED: content matches a configured public pattern\n\n"
                f"{_SUBJECT_LABEL}: {subject}\n"
                f"Pattern: {name}" + (f" — {description}" if description else "") + "\n"
                f"Matched: {matched_text}\n\n"
                "Remove or replace the matched text before retrying."
            ),
        )

    @staticmethod
    def _deny_secret_term(subject: str, index: int, total: int) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "SENSITIVE CONTENT BLOCKED: content matches a configured blocked term "
                f"(entry {index} of {total} in the secret word list).\n\n"
                f"{_SUBJECT_LABEL}: {subject}\n\n"
                "The term is deliberately not shown. Check "
                f"`{sr.DEFAULT_SECRET_WORD_LIST_PATH}` to see what is blocked, "
                "then remove it from the content."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## sensitive_content — blocked patterns and secret terms are never written\n\n"
            "A `Write`/`Edit` whose content matches a configured public pattern or a "
            "gitignored secret word list is blocked. Two sources, two different "
            "disclosure rules:\n\n"
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
            "**Git metadata is checked too.** File contents and file PATHS are only "
            "two of the seven places a term can enter a repository — the other five are "
            "git metadata, and none of them is a file write. So a `Bash` command that "
            "records metadata is also checked: `git commit` (messages), `git tag` "
            "(names and messages), `git branch` / `checkout -b` / `switch -c` (branch "
            "names), `git config user.name|user.email` (author identity), `git merge -m`. "
            "A match denies the command.\n\n"
            "**But a Bash command that writes a FILE is NOT checked, and that is the "
            "gap most likely to bite.** Git metadata is the only Bash surface this "
            "handler covers, so a term entering through `cat > f <<EOF`, `>`, `>>` or "
            "`tee` reaches disk unexamined — no block, no advisory, no record. Once "
            "pushed, removing it needs a history rewrite. Write file content with "
            "`Write`/`Edit` so this handler can see it.\n\n"
            "**Reading is never blocked.** Only commands that WRITE metadata are "
            "candidates, so `grep`, `cat`, `git log --grep=`, `git show`, "
            "`git branch --list` and `git tag -l` stay allowed even when the term is "
            "right there on the command line — searching for a term and removing it "
            "are exactly the work of cleaning a repository.\n\n"
            "If a compound command is denied because an unrelated part of it carries "
            "a term (`grep <term> f && git commit -m 'clean'`), split it into two "
            "calls rather than trying to disguise the term.\n\n"
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
                    "reason does not contain the actual secret term.\n"
                    "NEVER write to the operational secret list to set this test up. "
                    "Point `secret_word_list_path` at a TEMP file with a throwaway "
                    "term, restart, test, then restore the path. Overwriting the real "
                    "list fails silently: the guard simply stops guarding and the QA "
                    "scanner starts reporting a cleaner tree than reality, which is "
                    "exactly how a redaction gets declared finished with identifiers "
                    "still in it."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a secret-list term in a commit message",
                command=(
                    'Use the Bash tool to run `git commit -m "<term>"` where <term> '
                    "comes from `.claude/block-words.secret`"
                ),
                description=(
                    "Git METADATA is a leak surface no file write can reach. A term in "
                    "a commit message is denied with an entry index only, never the term."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"entry \d+ of \d+", r"deliberately not shown"],
                safety_notes=(
                    "Deny path — no commit is made. Verify the deny reason contains "
                    "neither the term nor the raw command line."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - allows a read command naming a term",
                command=(
                    "Use the Bash tool to run `git log --grep=<term>` where <term> "
                    "comes from `.claude/block-words.secret`"
                ),
                description=(
                    "Searching for a term must stay allowed — a guard that blocks its "
                    "own remedy gets switched off, which costs more than the leak."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Allow path — read-only git command, nothing is written",
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
